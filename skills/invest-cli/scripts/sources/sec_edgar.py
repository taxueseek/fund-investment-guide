"""SEC EDGAR 美股财报适配器（免费、无 key，SEC 官方 XBRL API）。

定位：美股财报「原文级」数据源，与 Wind / yfinance 的结构化数字交叉验证。
数据通道（全部官方公开，无需注册）：
  - company_tickers.json  ticker → CIK 映射（全市场，磁盘缓存 7 天）
  - companyfacts          单公司全量 XBRL 事实（缓存 24h；AAPL 约 3.7MB）
  - submissions           最近申报清单（缓存 6h）

口径：年报只取 form=10-K + fp=FY；时长型事实（利润表/现金流）要求
start~end 跨度 300~400 天，避免误取季度值；时点型事实（资产/权益）取最近 end。
标签存在漂移（如 Apple 的 Revenues 标签停在 2018 财年），按 METRIC_TAGS
的优先级列表逐级回退，取「优先级最高且存在」的标签。

SEC 要求 User-Agent 声明调用方身份：www.sec.gov 域强制 UA 含邮箱，否则 403
（data.sec.gov 不校验）。默认 UA 用占位邮箱通过校验，建议用 SEC_EDGAR_USER_AGENT
覆盖为真实联系方式（形如 "your-name your@email"）。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SOURCE_LABEL = "SEC EDGAR 美股财报"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{doc}"
BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"

ENV_UA = "SEC_EDGAR_USER_AGENT"
# www.sec.gov 要求 UA 含邮箱；example.com 为占位域，建议用环境变量覆盖为真实联系方式
DEFAULT_UA = "invest-cli/0.1 personal-research (contact: user@example.com)"
DEFAULT_TIMEOUT = 30
RETRIES = 3
ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 400

# 指标 → 候选 us-gaap 标签（按优先级回退；标签漂移时取第一个存在的）
METRIC_TAGS: dict[str, list[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
    ],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "operating_income": ["OperatingIncomeLoss"],
    "gross_profit": ["GrossProfit"],
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "assets": ["Assets"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
}

METRIC_LABELS: dict[str, str] = {
    "revenue": "营业收入",
    "net_income": "净利润",
    "operating_income": "营业利润",
    "gross_profit": "毛利润",
    "operating_cash_flow": "经营现金流",
    "assets": "总资产",
    "equity": "股东权益",
    "eps_diluted": "稀释每股收益",
    "eps_basic": "基本每股收益",
}


def detect() -> tuple[bool, str]:
    """SEC 官方 API 免费无 key；UA 声明可选。"""
    return True, f"免费无 key（SEC 官方 XBRL API；可用 {ENV_UA} 声明身份）"


def _user_agent() -> str:
    from .env import read_env

    return read_env(ENV_UA) or DEFAULT_UA


def cache_dir() -> Path:
    """SEC 原始 JSON 的磁盘缓存目录（原始文件大，缓存是必需品不是优化）。

    位置收敛到 _common.cache_root()/'sec'，避免本模块与 _common 各维护
    一套平台判断（同一件事两份实现必然漂移）。
    """
    _ensure_scripts_on_path()
    from _common import cache_root

    base = cache_root() / "sec"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ensure_scripts_on_path() -> None:
    scripts = str(Path(__file__).resolve().parent.parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def _http_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """带重试的 GET JSON。404 立即失败，其余错误退避重试。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": _user_agent(), "Accept": "application/json"}
    )
    last: Optional[Exception] = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
            if e.code == 403:
                raise RuntimeError(
                    f"SEC 403（{url}）：UA 需含邮箱声明，"
                    f"请设置 {ENV_UA}（如 \"your-name your@email\"）"
                ) from e
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            last = e
        time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"SEC 请求失败: {url}（{last}）")


def _cached_json(cache_name: str, url: str, ttl_hours: float) -> Any:
    """磁盘缓存统一走 _common.cache_get/cache_set（单真源），本函数只负责回源。

    TTL 对调用方保持小时口径，内部换算成统一层的秒；缓存名并入键，
    不同端点互不命中。缓存读写失败不阻断取数（统一层本身 fail-open）。
    旧版自实现的「TTL + 原子写」与统一层是同一件事的两份实现，已收敛。
    """
    _ensure_scripts_on_path()
    from _common import cache_get, cache_set

    key = f"{cache_name}|{url}"
    hit = cache_get("sec", key, ttl_hours * 3600)
    if hit is not None:
        return hit
    data = _http_json(url)
    cache_set("sec", key, data)
    return data


def _norm_ticker(ticker: str) -> str:
    """BRK.B → BRK-B（SEC 用连字符）。"""
    return (ticker or "").strip().upper().replace(".", "-")


def _ticker_index(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for item in (mapping or {}).values():
        if not isinstance(item, dict):
            continue
        tk = (item.get("ticker") or "").upper()
        if tk:
            idx.setdefault(tk, item)
            # 连字符与点号两种写法互相兼容（SEC 文件用 BRK-B，用户可能写 BRK.B）
            idx.setdefault(tk.replace(".", "-"), item)
            if "-" in tk:
                idx.setdefault(tk.replace("-", "."), item)
    return idx


def resolve_cik(ticker: str) -> tuple[str, str]:
    """ticker → (10 位 CIK, 公司名)。找不到抛 RuntimeError。"""
    mapping = _cached_json("company_tickers.json", TICKERS_URL, ttl_hours=24 * 7)
    hit = _ticker_index(mapping).get(_norm_ticker(ticker))
    if not hit:
        raise RuntimeError(f"SEC 未收录该 ticker: {ticker}（仅美股发行人）")
    return _cik10(hit["cik_str"]), str(hit.get("title") or ticker.upper())


def _cik10(cik: Any) -> str:
    return f"{int(cik):010d}"


def _annual_rows(unit_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤 10-K / FY，时长型事实要求年跨度，按期间升序返回。"""
    out: list[dict[str, Any]] = []
    for r in unit_rows or []:
        if r.get("form") != "10-K" or r.get("fp") != "FY":
            continue
        start, end = r.get("start"), r.get("end")
        if start:
            try:
                days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days
            except (TypeError, ValueError):
                continue
            if not (ANNUAL_MIN_DAYS <= days <= ANNUAL_MAX_DAYS):
                continue
        out.append(r)
    out.sort(key=lambda r: (r.get("end", ""), r.get("start", "")))
    return out


def _unit_of(units: dict[str, Any]) -> str:
    for preferred in ("USD", "USD/shares"):
        if preferred in units:
            return preferred
    return next(iter(units), "")


def extract_annual(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """从 companyfacts 抽取年报关键指标。纯函数，供离线测试。"""
    gaap = ((facts.get("facts") or {}).get("us-gaap")) or {}
    out: dict[str, dict[str, Any]] = {}
    for metric, tags in METRIC_TAGS.items():
        for tag in tags:
            node = gaap.get(tag)
            if not isinstance(node, dict):
                continue
            units = node.get("units") or {}
            unit = _unit_of(units)
            rows = _annual_rows(units.get(unit) or [])
            if not rows:
                continue
            last = rows[-1]
            out[metric] = {
                "value": last.get("val"),
                "unit": unit,
                "tag": tag,
                "fy": last.get("fy"),
                "start": last.get("start"),
                "end": last.get("end"),
                "form": last.get("form"),
            }
            break
    return out


def _err(message: str, kind: str = "us_fundamentals") -> dict[str, Any]:
    return {"source": "sec_edgar", "kind": kind, "ok": False, "data": None, "error": message}


def fundamentals(ticker: str) -> dict[str, Any]:
    """年报关键指标（10-K XBRL）。返回 invest-cli 信封。"""
    try:
        cik, title = resolve_cik(ticker)
        facts = _cached_json(f"companyfacts_{cik}.json", FACTS_URL.format(cik=cik), ttl_hours=24)
    except RuntimeError as e:
        return _err(str(e))
    metrics = extract_annual(facts)
    if not metrics:
        return _err(f"{title} 无可用 10-K 年报事实（可能为外国私人发行人 20-F 或新上市）")
    fy = max((m.get("fy") or 0) for m in metrics.values()) or None
    return {
        "source": "sec_edgar",
        "kind": "us_fundamentals",
        "ok": True,
        "data": {
            "ticker": _norm_ticker(ticker),
            "cik": cik,
            "name": title,
            "fiscal_year": fy,
            "metrics": metrics,
            "source_url": BROWSE_URL.format(cik=cik),
        },
        "error": None,
    }


def filings(ticker: str, forms: Optional[list[str]] = None, limit: int = 5) -> dict[str, Any]:
    """最近申报清单（默认 10-K/10-Q/8-K 取前 N 条，带原文链接）。"""
    try:
        cik, title = resolve_cik(ticker)
        subs = _cached_json(f"submissions_{cik}.json", SUBMISSIONS_URL.format(cik=cik), ttl_hours=6)
    except RuntimeError as e:
        return _err(str(e), kind="filings")
    recent = ((subs.get("filings") or {}).get("recent")) or {}
    forms_set = {f.strip().upper() for f in (forms or []) if f and f.strip()}
    rows: list[dict[str, Any]] = []
    total = len(recent.get("form") or [])
    for i in range(total):
        form = (recent.get("form") or [""])[i]
        if forms_set and str(form).upper() not in forms_set:
            continue
        accn = ((recent.get("accessionNumber") or [""])[i] or "").strip()
        doc = ((recent.get("primaryDocument") or [""])[i] or "").strip()
        if accn and doc:
            url = ARCHIVES_URL.format(cik_int=int(cik), accession=accn.replace("-", ""), doc=doc)
        elif accn:
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/"
        else:
            url = BROWSE_URL.format(cik=cik)
        rows.append({
            "form": form,
            "filing_date": ((recent.get("filingDate") or [""])[i] or ""),
            "accession": accn,
            "url": url,
        })
        if len(rows) >= max(1, limit):
            break
    return {
        "source": "sec_edgar",
        "kind": "filings",
        "ok": True,
        "data": {"ticker": _norm_ticker(ticker), "cik": cik, "name": title, "filings": rows},
        "error": None,
    }


def snapshot(ticker: str, forms: Optional[list[str]] = None, limit: int = 5) -> dict[str, Any]:
    """年报指标 + 最近申报，一次取全（给 CLI 的单一入口）。"""
    fund = fundamentals(ticker)
    if not fund.get("ok"):
        return fund
    fil = filings(ticker, forms=forms, limit=limit)
    data = dict(fund["data"])
    data["filings"] = (fil.get("data") or {}).get("filings") if fil.get("ok") else []
    if not fil.get("ok"):
        data["filings_error"] = fil.get("error")
    return {"source": "sec_edgar", "kind": "us_fundamentals", "ok": True, "data": data, "error": None}


if __name__ == "__main__":  # 快速自检：在 scripts/ 目录下 python3 -m sources.sec_edgar AAPL
    import json as _json

    _t = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(_json.dumps(snapshot(_t), ensure_ascii=False, indent=2, default=str)[:3000])
