"""同花顺金融数据服务（hithink / 扶摇）适配器。

只覆盖 invest 系列分析框架真正要的字段，不包装全部 REST 端点。

- A 股个股：行情 + 五项估值 + 近 5 年年报 + 最新年报官方指标（三关：好不好/贵不贵）
- 公募基金：资料/费率/净值收益/回撤/重仓（三关：策略/业绩/成本）
- 不覆盖：港股、美股、自然语言选股、全市场 dump、集合竞价、特色数据

认证：环境变量 HITHINK_FINANCE_API_KEY，否则用户级 credentials.env。
HTTP 仅 stdlib；Key 只进 Header，不进 URL、日志、返回信封。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

API_BASE = "https://fuyao.aicubes.cn"
DEFAULT_TIMEOUT = 15
USER_AGENT = "invest-cli/hithink"
SOURCE_LABEL = "同花顺金融数据服务"
ENV_KEY = "HITHINK_FINANCE_API_KEY"
RETRYABLE_CODES = {4001, 5001, 5002, 5003}
MAX_RETRIES = 3
# 官方契约：避免过高并发；单标的快照 3 路封顶，4001 仍走单请求有界退避。
MAX_PARALLEL = 3

A_SHARE_ASSETS = frozenset({"a-share"})
FUND_ASSETS = frozenset({"fund-otc", "fund-etf", "fund-lof", "fund-reits"})
ASSET_TO_FUND_TYPE = {
    "fund-otc": "otc",
    "fund-etf": "exchange",
    "fund-lof": "exchange",
    "fund-reits": "reits",
}

# 财务指标端点 index_id → 三关字段。取值已是百分数原值，禁止再乘 100。
INDICATOR_MAP = {
    "index_weighted_avg_roe": "roe",
    "index_deduct_weighted_avg_roe": "roe_deducted",
    "sale_gross_margin": "gross_margin",
    "sale_net_interest_ratio": "net_margin",
    "assets_debt_ratio": "debt_ratio",
    "net_profit_cash_content": "ocf_to_ni",
    "calculate_operating_income_yoy_growth_ratio": "revenue_yoy",
    "calculate_parent_holder_net_profit_yoy_growth_ratio": "np_yoy",
}

_HttpGet = Callable[..., tuple[int, str]]


def credential_files() -> list[Path]:
    home = Path.home()
    files = [
        home / "Library" / "Application Support" / "hithink-finance" / "credentials.env",
    ]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    files.append(Path(xdg) / "hithink-finance" / "credentials.env" if xdg else home / ".config" / "hithink-finance" / "credentials.env")
    appdata = os.environ.get("APPDATA")
    if appdata:
        files.append(Path(appdata) / "hithink-finance" / "credentials.env")
    # 去重保序
    seen: set[str] = set()
    out: list[Path] = []
    for p in files:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _parse_env_line(line: str) -> tuple[str, str] | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    if raw.startswith("export "):
        raw = raw[7:].strip()
    if "=" not in raw:
        return None
    name, val = raw.split("=", 1)
    name = name.strip()
    val = val.strip().strip('"').strip("'")
    if not name:
        return None
    return name, val


def load_api_key() -> Optional[str]:
    env = os.environ.get(ENV_KEY)
    if env and env.strip():
        return env.strip()
    for path in credential_files():
        try:
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                parsed = _parse_env_line(line)
                if parsed and parsed[0] == ENV_KEY and parsed[1]:
                    return parsed[1]
        except OSError:
            continue
    return None


def file_has_key(path: Path, var: str = ENV_KEY) -> bool:
    try:
        if not path.is_file():
            return False
        for line in path.read_text(encoding="utf-8").splitlines():
            parsed = _parse_env_line(line)
            if parsed and parsed[0] == var and parsed[1]:
                return True
    except OSError:
        return False
    return False


def detect() -> tuple[bool, str]:
    if os.environ.get(ENV_KEY, "").strip():
        return True, f"{ENV_KEY} 已配置"
    for path in credential_files():
        if file_has_key(path):
            return True, "读到 credentials.env"
    return False, f"缺少 {ENV_KEY} 且无凭据文件"


def looks_like_hk(keyword: str) -> bool:
    t = (keyword or "").strip()
    if t.isdigit() and len(t) == 5:
        return True
    return t.upper().endswith(".HK")


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None:
        return None
    if den == 0:
        return None
    return num / den


def _ms_iso(ms: Any) -> Optional[str]:
    val = _to_float(ms)
    if val is None:
        return None
    try:
        return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _ms_date(ms: Any) -> Optional[str]:
    iso = _ms_iso(ms)
    return iso[:10] if iso else None


def _items(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    item = data.get("item")
    if not isinstance(item, list):
        return []
    return [x for x in item if isinstance(x, dict)]


def _first(data: Any) -> Optional[dict[str, Any]]:
    rows = _items(data)
    return rows[0] if rows else None


def _envelope(kind: str, ok: bool, data: Any = None, error: Optional[str] = None) -> dict[str, Any]:
    return {"source": "hithink", "kind": kind, "ok": ok, "data": data, "error": error}


def _default_http_get(url: str, headers: Optional[dict[str, str]] = None) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return resp.getcode() or 200, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return int(e.code), body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectionError(f"hithink 请求失败: {e}") from e


def _request(
    path: str,
    params: dict[str, Any],
    *,
    api_key: str,
    http_get: Optional[_HttpGet] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    getter = http_get or _default_http_get
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{API_BASE}{path}" + (f"?{qs}" if qs else "")
    headers = {
        "X-api-key": api_key,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    last_err: Optional[str] = None
    for attempt in range(MAX_RETRIES):
        try:
            status, body = getter(url, headers)
        except TypeError:
            # 兼容只接收 url 的旧 mock
            status, body = getter(url)  # type: ignore[misc]
        except ConnectionError as e:
            return None, str(e)
        except Exception as e:
            return None, f"hithink 请求异常: {e}"

        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            return None, f"hithink 返回非 JSON (HTTP {status})"

        if not isinstance(payload, dict):
            return None, f"hithink 响应格式异常 (HTTP {status})"

        code = payload.get("code")
        msg = payload.get("message") or ""
        rid = payload.get("request_id")
        rid_s = f" request_id={rid}" if rid else ""
        if status == 200 and code == 0:
            return payload, None

        retryable = code in RETRYABLE_CODES or status >= 500
        last_err = f"hithink HTTP {status} code={code}: {msg}{rid_s}".strip()
        if retryable and attempt < MAX_RETRIES - 1:
            sleep(0.4 * (attempt + 1))
            continue
        return None, last_err
    return None, last_err or "hithink 请求失败"


def _request_many(
    jobs: list[tuple[str, str, dict[str, Any]]],
    *,
    api_key: str,
    http_get: Optional[_HttpGet] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, tuple[Optional[dict[str, Any]], Optional[str]]]:
    """独立 GET 的有界并发。注入 http_get 时保持串行，方便测试 mock 保序。"""

    def one(job: tuple[str, str, dict[str, Any]]) -> tuple[str, tuple[Optional[dict[str, Any]], Optional[str]]]:
        key, path, params = job
        return key, _request(path, params, api_key=api_key, http_get=http_get, sleep=sleep)

    out: dict[str, tuple[Optional[dict[str, Any]], Optional[str]]] = {}
    if not jobs:
        return out
    if http_get is not None or len(jobs) == 1:
        for job in jobs:
            key, res = one(job)
            out[key] = res
        return out
    workers = min(MAX_PARALLEL, len(jobs))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, job) for job in jobs]
        for fut in as_completed(futs):
            key, res = fut.result()
            out[key] = res
    return out


def _search(
    q: str,
    *,
    api_key: str,
    asset_type: Optional[str] = None,
    http_get: Optional[_HttpGet] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    params: dict[str, Any] = {"q": q, "limit": 10}
    if asset_type:
        params["asset_type"] = asset_type
    payload, err = _request(
        "/api/meta/tickers/search",
        params,
        api_key=api_key,
        http_get=http_get,
        sleep=sleep,
    )
    if err:
        return [], err
    return _items((payload or {}).get("data")), None


def pick_ticker(
    items: list[dict[str, Any]],
    keyword: str,
    allowed: frozenset[str],
) -> tuple[Optional[dict[str, Any]], str]:
    """消歧为唯一标的。不允许猜交易所后缀。"""
    kw = (keyword or "").strip()
    pool = [i for i in items if i.get("asset_type") in allowed]
    if not pool:
        return None, f"未找到匹配标的: {kw}"

    up = kw.upper()
    for i in pool:
        if str(i.get("thscode") or "").upper() == up:
            return i, ""
    for i in pool:
        if str(i.get("ticker") or "") == kw:
            return i, ""
    for i in pool:
        if str(i.get("name") or "") == kw:
            return i, ""
    if len(pool) == 1:
        return pool[0], ""

    name_hits = [i for i in pool if kw in str(i.get("name") or "")]
    if len(name_hits) == 1:
        return name_hits[0], ""

    cands = ", ".join(
        f"{i.get('thscode')} {i.get('name')} ({i.get('asset_type')})" for i in pool[:6]
    )
    return None, f"多个候选无法唯一消歧: {cands}"


def parse_indicators(abilities: Any) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {v: None for v in INDICATOR_MAP.values()}
    if not isinstance(abilities, list):
        return out
    for block in abilities:
        if not isinstance(block, dict):
            continue
        for ind in block.get("indicators") or []:
            if not isinstance(ind, dict):
                continue
            idx = ind.get("index_id")
            dest = INDICATOR_MAP.get(idx)
            if not dest:
                continue
            out[dest] = _to_float(ind.get("value"))
    return out


def _history_row(year: int, inc: dict, bal: dict, cf: dict) -> dict[str, Any]:
    oi = _to_float(inc.get("operating_income"))
    oc = _to_float(inc.get("operating_costs"))
    np_ = _to_float(inc.get("net_profit"))
    pnp = _to_float(inc.get("parent_holder_net_profit"))
    if pnp is None:
        pnp = np_
    eq = _to_float(bal.get("holder_equity_total"))
    assets = _to_float(bal.get("assets_total"))
    debt = _to_float(bal.get("total_debt"))
    ocf = _to_float(cf.get("act_cash_flow_net"))
    gm = _ratio((oi - oc) if oi is not None and oc is not None else None, oi)
    nm = _ratio(np_, oi)
    roe_e = _ratio(pnp, eq)
    dr = _ratio(debt, assets)
    ocf_ni = _ratio(ocf, np_)
    return {
        "fiscal_year": year,
        "revenue": oi,
        "net_profit": np_,
        "eps": _to_float(inc.get("basic_eps")),
        "ocf": ocf,
        "assets": assets,
        "equity": eq,
        "debt": debt,
        "gross_margin": None if gm is None else gm * 100.0,
        "net_margin": None if nm is None else nm * 100.0,
        "debt_ratio": None if dr is None else dr * 100.0,
        "roe_ending": None if roe_e is None else roe_e * 100.0,
        "ocf_to_ni": None if ocf_ni is None else ocf_ni * 100.0,
        "roe_ending_basis": "parent_net_profit/ending_equity",
    }


def build_history(
    income_items: list[dict[str, Any]],
    balance_items: list[dict[str, Any]],
    cash_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    def by_year(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for row in rows:
            y = row.get("fiscal_year")
            try:
                out[int(y)] = row
            except (TypeError, ValueError):
                continue
        return out

    inc = by_year(income_items)
    bal = by_year(balance_items)
    cf = by_year(cash_items)
    years = sorted(set(inc) | set(bal) | set(cf), reverse=True)
    return [_history_row(y, inc.get(y, {}), bal.get(y, {}), cf.get(y, {})) for y in years[:5]]


def _fee(rate_info: Any, rate_type: str) -> Optional[str]:
    if not isinstance(rate_info, list):
        return None
    rows = [r for r in rate_info if isinstance(r, dict) and r.get("rate_type") == rate_type]
    if not rows:
        return None
    return rows[0].get("standard_rate")


def stock(
    keyword: str,
    *,
    http_get: Optional[_HttpGet] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    kw = (keyword or "").strip()
    if not kw:
        return _envelope("stock", False, error="空代码")
    if looks_like_hk(kw):
        return _envelope("stock", False, error="hithink 不覆盖港股，请走东财/Wind")

    api_key = load_api_key()
    if not api_key:
        return _envelope("stock", False, error=f"未配置 {ENV_KEY}")

    items, err = _search(kw, api_key=api_key, http_get=http_get, sleep=sleep)
    if err:
        return _envelope("stock", False, error=err)
    picked, err = pick_ticker(items, kw, A_SHARE_ASSETS)
    if err or not picked:
        return _envelope("stock", False, error=err or "未找到 A 股")

    thscode = picked["thscode"]
    warnings: list[str] = []

    got = _request_many(
        [
            ("snap", "/api/a-share/prices/snapshot", {"thscodes": thscode}),
            ("val", "/api/a-share/valuations/snapshot", {"thscodes": thscode}),
            ("inc", "/api/a-share/financials/income-statements",
             {"thscode": thscode, "period": "annual", "limit": 5}),
            ("bal", "/api/a-share/financials/balance-sheets",
             {"thscode": thscode, "period": "annual", "limit": 5}),
            ("cf", "/api/a-share/financials/cash-flow-statements",
             {"thscode": thscode, "period": "annual", "limit": 5}),
        ],
        api_key=api_key,
        http_get=http_get,
        sleep=sleep,
    )
    snap_payload, snap_err = got["snap"]
    if snap_err:
        return _envelope("stock", False, error=f"行情: {snap_err}")
    quote_row = _first((snap_payload or {}).get("data"))
    if not quote_row:
        return _envelope("stock", False, error=f"行情为空: {thscode}")

    val_payload, val_err = got["val"]
    val_row: dict[str, Any] = {}
    if val_err:
        warnings.append(f"估值: {val_err}")
    else:
        val_row = _first((val_payload or {}).get("data")) or {}

    inc_payload, inc_err = got["inc"]
    bal_payload, bal_err = got["bal"]
    cf_payload, cf_err = got["cf"]
    for label, e in (("利润表", inc_err), ("资产负债表", bal_err), ("现金流", cf_err)):
        if e:
            warnings.append(f"{label}: {e}")

    history = build_history(
        _items((inc_payload or {}).get("data")) if inc_payload else [],
        _items((bal_payload or {}).get("data")) if bal_payload else [],
        _items((cf_payload or {}).get("data")) if cf_payload else [],
    )

    indicators: dict[str, Optional[float]] = {}
    latest_year = history[0]["fiscal_year"] if history else None
    if latest_year is not None:
        ind_payload, ind_err = _request(
            "/api/a-share/financials/indicators",
            {"thscode": thscode, "report": f"{latest_year}-4"},
            api_key=api_key,
            http_get=http_get,
            sleep=sleep,
        )
        if ind_err:
            warnings.append(f"财务指标: {ind_err}")
        else:
            data = (ind_payload or {}).get("data") or {}
            indicators = parse_indicators(data.get("abilities") if isinstance(data, dict) else None)

    latest = history[0] if history else {}
    last_price = _to_float(quote_row.get("last_price"))
    open_price = _to_float(quote_row.get("open_price"))
    prev_price = _to_float(quote_row.get("prev_price"))
    if last_price is None and prev_price is not None:
        warnings.append(
            f"未开盘或无成交（{datetime.now(timezone.utc).strftime('%H:%M UTC')}）：当日 last/open 为空，参考昨收 {prev_price}"
        )
    pe_ttm = _to_float(val_row.get("pe_ttm"))
    pb = _to_float(val_row.get("pb_mrq"))
    roe = indicators.get("roe")
    if roe is None:
        roe = latest.get("roe_ending")
    gross = indicators.get("gross_margin")
    if gross is None:
        gross = latest.get("gross_margin")
    net_m = indicators.get("net_margin")
    if net_m is None:
        net_m = latest.get("net_margin")
    debt_r = indicators.get("debt_ratio")
    if debt_r is None:
        debt_r = latest.get("debt_ratio")

    name = picked.get("name") or val_row.get("name") or thscode
    aliases = {
        "收盘价": last_price,
        "开盘价": open_price,
        "昨收": prev_price,
        "市盈率PE(TTM)": pe_ttm,
        "市净率PB": pb,
        "净资产收益率ROE": roe,
        "销售毛利率": gross,
        "销售净利率": net_m,
        "资产负债率": debt_r,
        "每股收益EPS": latest.get("eps"),
        "营业收入": latest.get("revenue"),
        "净利润": latest.get("net_profit"),
        "经营活动产生的现金流量净额": latest.get("ocf"),
    }
    snap = {
        "code": picked.get("ticker") or kw,
        "thscode": thscode,
        "name": name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "hithink",
        "source_label": SOURCE_LABEL,
        "currency": picked.get("currency") or "CNY",
        "quote": {
            "last": last_price,
            "open": open_price,
            "high": _to_float(quote_row.get("high_price")),
            "low": _to_float(quote_row.get("low_price")),
            "prev": _to_float(quote_row.get("prev_price")),
            "change": _to_float(quote_row.get("price_change")),
            "change_pct": _to_float(quote_row.get("price_change_ratio_pct")),
            "volume": _to_float(quote_row.get("volume")),
            "turnover": _to_float(quote_row.get("turnover")),
        },
        "valuation": {
            "pe_ttm": pe_ttm,
            "pe_mrq": _to_float(val_row.get("pe_mrq")),
            "pb_mrq": pb,
            "ps_ttm": _to_float(val_row.get("ps_ttm")),
            "pcf_ttm": _to_float(val_row.get("pcf_ttm")),
        },
        "financials": {
            "fiscal_year": latest_year,
            "report": f"{latest_year}-4" if latest_year is not None else None,
            "revenue": latest.get("revenue"),
            "net_profit": latest.get("net_profit"),
            "eps": latest.get("eps"),
            "ocf": latest.get("ocf"),
            "assets": latest.get("assets"),
            "equity": latest.get("equity"),
            "debt": latest.get("debt"),
            "roe": roe,
            "roe_source": "index_weighted_avg_roe" if indicators.get("roe") is not None else "ending_equity",
            "roe_deducted": indicators.get("roe_deducted"),
            "gross_margin": gross,
            "net_margin": net_m,
            "debt_ratio": debt_r,
            "ocf_to_ni": indicators.get("ocf_to_ni") if indicators.get("ocf_to_ni") is not None else latest.get("ocf_to_ni"),
            "revenue_yoy": indicators.get("revenue_yoy"),
            "np_yoy": indicators.get("np_yoy"),
        },
        "financials_history": history,
        "data": aliases,
        "warnings": warnings,
    }
    return _envelope("stock", True, data=snap)


def fund(
    keyword: str,
    *,
    http_get: Optional[_HttpGet] = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    kw = (keyword or "").strip()
    if not kw:
        return _envelope("fund", False, error="空代码")

    api_key = load_api_key()
    if not api_key:
        return _envelope("fund", False, error=f"未配置 {ENV_KEY}")

    items, err = _search(
        kw,
        api_key=api_key,
        asset_type="fund-otc,fund-etf,fund-lof,fund-reits",
        http_get=http_get,
        sleep=sleep,
    )
    if err:
        return _envelope("fund", False, error=err)
    if not items:
        items, err = _search(kw, api_key=api_key, http_get=http_get, sleep=sleep)
        if err:
            return _envelope("fund", False, error=err)
    picked, err = pick_ticker(items, kw, FUND_ASSETS)
    if err or not picked:
        return _envelope("fund", False, error=err or "未找到基金")

    thscode = picked["thscode"]
    asset_type = picked.get("asset_type")
    fund_type = ASSET_TO_FUND_TYPE.get(str(asset_type))
    if not fund_type:
        return _envelope("fund", False, error=f"无法映射 fund_type: {asset_type}")

    warnings: list[str] = []
    # 业绩/回撤/持仓任一失败 = 三关核心块缺失 → 整单 ok=False 让 route 回退到
    # ttskill/eastmoney；不输出缺块残缺快照（429 部分失败实测教训 2026-09-03）。
    errors: list[str] = []
    prof_payload, prof_err = _request(
        "/api/fund/profile/detail",
        {"fund_type": fund_type, "thscode": thscode},
        api_key=api_key,
        http_get=http_get,
        sleep=sleep,
    )
    if prof_err:
        return _envelope("fund", False, error=f"资料: {prof_err}")
    profile = _first((prof_payload or {}).get("data"))
    if not profile:
        return _envelope("fund", False, error=f"基金资料为空: {thscode}")

    got = _request_many(
        [
            ("ret", "/api/fund/performance/returns",
             {"fund_type": fund_type, "thscode": thscode}),
            ("dd", "/api/fund/performance/drawdowns",
             {"fund_type": fund_type, "thscode": thscode}),
            ("hold", "/api/fund/portfolio/holdings",
             {"fund_type": fund_type, "thscode": thscode}),
        ],
        api_key=api_key,
        http_get=http_get,
        sleep=sleep,
    )
    ret_payload, ret_err = got["ret"]
    ret_row: dict[str, Any] = {}
    if ret_err:
        errors.append(f"收益: {ret_err}")
    else:
        ret_row = _first((ret_payload or {}).get("data")) or {}

    dd_payload, dd_err = got["dd"]
    dd_row: dict[str, Any] = {}
    if dd_err:
        errors.append(f"回撤: {dd_err}")
    else:
        dd_row = _first((dd_payload or {}).get("data")) or {}

    hold_payload, hold_err = got["hold"]
    hold_rows: list[dict[str, Any]] = []
    if hold_err:
        errors.append(f"持仓: {hold_err}")
    else:
        hold_data = (hold_payload or {}).get("data") or {}
        hold_rows = _items(hold_data)

    rate_info = profile.get("rate_info") or []
    mgrs = profile.get("manager_info") or []
    primary_mgr = None
    if isinstance(mgrs, list):
        dicts = [m for m in mgrs if isinstance(m, dict)]
        dicts.sort(key=lambda m: _to_float(m.get("tenure_days")) or 0, reverse=True)
        primary_mgr = dicts[0] if dicts else None
    manager_name = (primary_mgr or {}).get("manager_name") or profile.get("manager_name")

    holdings = []
    for row in hold_rows:
        name = row.get("stock_name")
        ratio = _to_float(row.get("hold_ratio"))
        holdings.append(
            {
                "entityName": name,
                "stock_name": name,
                "ticker": row.get("ticker"),
                "thscode": row.get("thscode"),
                "hold_ratio": ratio,
                "占净值比例": ratio,
                "investment_rank": row.get("investment_rank"),
            }
        )

    aliases = {
        "基金名称": profile.get("fund_name") or picked.get("name"),
        "基金类型": asset_type,
        "成立日期": _ms_date(profile.get("estab_date")),
        "基金规模": _to_float(profile.get("fund_scale")),
        "基金管理人": profile.get("mgmt_name"),
        "单位净值": _to_float(profile.get("unit_nav")),
        "近1月回报": _to_float(ret_row.get("return_month")),
        "近3月回报": _to_float(ret_row.get("return_tmonth")),
        "近6月回报": _to_float(ret_row.get("return_hyear")),
        "近1年回报": _to_float(ret_row.get("return_year")),
        "近3年回报": _to_float(ret_row.get("return_tyear")),
        "今年来回报": _to_float(ret_row.get("return_nowyear")),
        "最大回撤": _to_float(dd_row.get("year")),
        "经理姓名": manager_name,
        "管理费率": _fee(rate_info, "management"),
        "托管费率": _fee(rate_info, "custody"),
        "申购费率": _fee(rate_info, "purchase"),
    }
    snap = {
        "code": picked.get("ticker") or kw,
        "thscode": thscode,
        "fund_type": fund_type,
        "asset_type": asset_type,
        "name": profile.get("fund_name") or picked.get("name") or thscode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "hithink",
        "source_label": SOURCE_LABEL,
        "profile": {
            "mgmt_name": profile.get("mgmt_name"),
            "manager_name": manager_name,
            "managers": mgrs if isinstance(mgrs, list) else [],
            "estab_date": _ms_date(profile.get("estab_date")),
            "fund_scale": _to_float(profile.get("fund_scale")),
            "unit_nav": _to_float(profile.get("unit_nav")),
            "company_id": profile.get("company_id"),
        },
        "returns": {
            "month": _to_float(ret_row.get("return_month")),
            "tmonth": _to_float(ret_row.get("return_tmonth")),
            "hyear": _to_float(ret_row.get("return_hyear")),
            "year": _to_float(ret_row.get("return_year")),
            "tyear": _to_float(ret_row.get("return_tyear")),
            "nowyear": _to_float(ret_row.get("return_nowyear")),
            "inception": _to_float(ret_row.get("return_now")),
        },
        "risk": {
            "max_drawdown_1y": _to_float(dd_row.get("year")),
            "max_drawdown_3y": _to_float(dd_row.get("tyear")),
            "drawdowns": {k: _to_float(dd_row.get(k)) for k in ("week", "month", "tmonth", "hyear", "year", "twoyear", "tyear", "fyear", "nowyear", "now")},
        },
        "fees": {
            "management": _fee(rate_info, "management"),
            "custody": _fee(rate_info, "custody"),
            "purchase": _fee(rate_info, "purchase"),
        },
        "data": aliases,
        "holdings": holdings,
        "warnings": warnings,
    }
    if errors:
        return _envelope("fund", False, error="; ".join(errors))
    return _envelope("fund", True, data=snap)
