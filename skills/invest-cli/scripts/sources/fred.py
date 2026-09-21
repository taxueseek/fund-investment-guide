"""FRED 宏观时序适配器（invest-cli 数据源）。

定位：宏观流动性专项——净流动性 = 美联储总资产 − TGA − ON RRP（invest-macro 核心公式）。

取数双通道（2026-09-18 实测）：
  - 有 FRED_API_KEY：走官方 API（api.stlouisfed.org），key 走环境变量或用户级凭据文件；
  - 无 key：回退 fredgraph.csv 免 key 通道（同源同口径，仅缺 API 元数据能力）。
  免 key 通道偶发超时，已内置重试；长期使用仍建议注册免费 key。

序列口径（单位统一为十亿美元，2026-09-03 实测）：
  - WALCL      美联储总资产，百万美元（周度 H.4.1）→ /1000
  - WDTGAL     TGA 财政部现金余额，百万美元（周度）→ /1000
  - RRPONTSYD  隔夜逆回购 ON RRP，十亿美元（日度）→ 原值
  - SOFR       担保隔夜融资利率，%（日度）→ 原值（%）

YAML 声明在 data-sources.yaml（coverage: [macro]），正常路径走
`intent macro`（fred 先行，argo nbs_stats 检索兜底）。
"""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

SOURCE_LABEL = "FRED 宏观序列"
API_BASE = "https://api.stlouisfed.org/fred/series/observations"
GRAPH_CSV_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ENV_KEY = "FRED_API_KEY"
DEFAULT_TIMEOUT = 20
CSV_RETRIES = 3
MAX_OBS = 6  # 周度/日度序列取最近 6 个观测，够趋势判断

# 序列 → (说明, 单位乘数 → 十亿美元, 是否百分数)
SERIES: dict[str, dict[str, Any]] = {
    "WALCL": {"label": "美联储总资产", "mult": 1 / 1000.0, "unit": "十亿美元"},
    "WDTGAL": {"label": "TGA 财政部现金余额", "mult": 1 / 1000.0, "unit": "十亿美元"},
    "RRPONTSYD": {"label": "ON RRP 隔夜逆回购", "mult": 1.0, "unit": "十亿美元"},
    "SOFR": {"label": "SOFR 担保隔夜融资利率", "mult": 1.0, "unit": "%"},
}


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "fred.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "fred.env",
    ]
    return [p for p in cands if p.is_file()]


def _file_has_key(path: Path) -> bool:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{ENV_KEY}=") and line.split("=", 1)[1].strip():
                return True
    except OSError:
        return False
    return False


def load_api_key() -> Optional[str]:
    from .env import read_env

    val = read_env(ENV_KEY)
    if val:
        return val
    for p in credential_files():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{ENV_KEY}="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return None


def detect() -> tuple[bool, str]:
    if load_api_key():
        return True, f"{ENV_KEY} 已配置（官方 API）"
    return True, "未配置 key，走 fredgraph.csv 免 key 回退（建议免费注册以用官方 API）"


def _fetch_series(series_id: str, api_key: str) -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
    qs = urllib.parse.urlencode(
        {"series_id": series_id, "api_key": api_key, "file_type": "json", "sort_order": "desc", "limit": MAX_OBS}
    )
    url = f"{API_BASE}?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return None, f"FRED HTTP {e.code}: {e.reason}"
    except (urllib.error.URLError, OSError) as e:
        return None, f"FRED 请求失败: {e}"
    import json

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return None, "FRED 返回非 JSON"
    obs = (payload or {}).get("observations") or []
    rows = []
    for o in obs:
        val = (o or {}).get("value")
        try:
            num = float(val)
        except (TypeError, ValueError):
            continue
        rows.append({"date": (o or {}).get("date", ""), "value": num})
    if not rows:
        return None, f"FRED {series_id} 无有效观测"
    return rows, None


def _fetch_series_keyless(
    series_id: str, retries: int = CSV_RETRIES
) -> tuple[Optional[list[dict[str, Any]]], Optional[str]]:
    """免 key 通道：fredgraph.csv（与 API 同源同口径，默认近 10 年窗口）。

    返回最近 MAX_OBS 个观测，降序（与 API 通道一致）。CSV 里缺失值写作 "."，跳过。
    """
    url = f"{GRAPH_CSV_BASE}?id={series_id}"
    body = ""
    last_err = ""
    for attempt in range(max(1, retries)):
        try:
            with urllib.request.urlopen(url, timeout=DEFAULT_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            return None, f"FRED CSV HTTP {e.code}: {e.reason}"
        except (urllib.error.URLError, OSError) as e:
            last_err = str(e)
            time.sleep(1.0 * (attempt + 1))
    if not body:
        return None, f"FRED CSV 请求失败: {last_err or '超时'}"
    lines = [ln for ln in body.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None, f"FRED {series_id} CSV 无数据"
    rows: list[dict[str, Any]] = []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) < 2:
            continue
        try:
            num = float(parts[1])
        except (TypeError, ValueError):
            continue  # "." 或空值
        rows.append({"date": parts[0].strip(), "value": num})
    if not rows:
        return None, f"FRED {series_id} CSV 无有效观测"
    rows = rows[-MAX_OBS:]
    rows.reverse()
    return rows, None


def _net_liquidity(walcl: float, tga: float, onrrp: float) -> float:
    """净流动性 = 美联储总资产 − TGA − ON RRP（invest-macro 核心公式，十亿美元）。"""
    return walcl - tga - onrrp


def _collect_series(api_key: Optional[str]) -> tuple[dict[str, Any], list[str]]:
    """并发取全部序列，返回 (series, errors)。

    四条序列互不依赖，串行等于把四段 RTT 相加（实测 2.34s，占 intent macro
    总耗时的 96%）；并发后收敛到最慢那条。`pool.map` 保序，错误列表顺序稳定。
    """
    def one(sid: str) -> tuple[str, Optional[list[dict[str, Any]]], Optional[str]]:
        rows, err = (_fetch_series(sid, api_key) if api_key else _fetch_series_keyless(sid))
        return sid, rows, err

    series: dict[str, Any] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=len(SERIES)) as pool:
        for sid, rows, err in pool.map(one, list(SERIES)):
            if err:
                errors.append(f"{sid}: {err}")
                continue
            meta = SERIES[sid]
            series[sid] = {
                "label": meta["label"],
                "unit": meta["unit"],
                "obs": [{"date": r["date"], "value": round(r["value"] * meta["mult"], 2)} for r in rows],
            }
    return series, errors


def liquidity(use_cache: bool = True) -> dict[str, Any]:
    """净流动性三序列 + 派生计算。返回 envelope（route 风格 {source,kind,ok,data,error}）。

    有 key 走官方 API；无 key 走 fredgraph.csv 免 key 回退。两者取数结果同源同口径。
    结果按 CACHE_TTL_MACRO 落盘缓存：FRED 序列是周度/日度口径，30 分钟内不可能变。

    use_cache=False 供测试/强制刷新用：**完全不碰缓存**（不读也不写）——
    只绕过读而仍然写，会让测试的 mock 数据落进生产缓存（实测污染过
    ~/Library/Caches/invest-cli/macro，之后的真实查询会拿到 mock 值）。
    """
    api_key = load_api_key()
    transport = "api" if api_key else "csv"
    cache_key = f"liquidity|{transport}"
    if use_cache:
        try:
            from _common import CACHE_TTL_MACRO, cache_get

            hit = cache_get("macro", cache_key, CACHE_TTL_MACRO)
        except Exception:
            hit = None
        if isinstance(hit, dict) and hit.get("ok"):
            return {**hit, "cached": True}

    series, errors = _collect_series(api_key)
    if not series:
        return {"source": "fred", "kind": "macro", "ok": False, "data": None,
                "error": "; ".join(errors) or "FRED 无任何序列"}

    def latest(sid: str) -> tuple[Optional[float], str]:
        obs = (series.get(sid) or {}).get("obs") or []
        if not obs:
            return None, ""
        return obs[0]["value"], obs[0]["date"]

    walcl, d1 = latest("WALCL")
    tga, d2 = latest("WDTGAL")
    onrrp, d3 = latest("RRPONTSYD")
    net = None
    if walcl is not None and tga is not None and onrrp is not None:
        net = round(_net_liquidity(walcl, tga, onrrp), 2)
    data = {
        "formula": "净流动性 = 美联储总资产 − TGA − ON RRP",
        "unit": "十亿美元（USD bn）",
        "transport": transport,
        "net_liquidity": net,
        "net_asof": (d1 or d2 or d3 or ""),
        "components": {
            "walcl": {"value": walcl, "asof": d1, "label": "美联储总资产"},
            "tga": {"value": tga, "asof": d2, "label": "TGA"},
            "on_rrp": {"value": onrrp, "asof": d3, "label": "ON RRP"},
        },
        "series_detail": series,
        "series_errors": errors,
    }
    res = {"source": "fred", "kind": "macro", "ok": True, "data": data, "error": None}
    # 只在**完整**结果上写缓存：四条序列里有一条失败时，缓存会把「缺一条」的
    # 半成品固定 30 分钟（净流动性可能因此算不出或口径不全）。
    if use_cache and not errors:
        try:
            from _common import cache_set

            cache_set("macro", cache_key, res)
        except Exception:
            pass
    return res


if __name__ == "__main__":  # 快速自检：在 scripts/ 目录下 python3 -m sources.fred
    import json

    print(json.dumps(liquidity(), ensure_ascii=False, indent=2, default=str)[:2000])
