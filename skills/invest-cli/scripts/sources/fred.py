"""FRED 宏观时序适配器（invest-cli 数据源）。

定位：宏观流动性专项——净流动性 = 美联储总资产 − TGA − ON RRP（invest-macro 核心公式）。
FRED 免费注册即用（api.stlouisfed.org），key 走环境变量或用户级凭据文件，不硬编码。

序列口径（单位统一为十亿美元，2026-09-03 实测）：
  - WALCL      美联储总资产，百万美元（周度 H.4.1）→ /1000
  - WDTGAL     TGA 财政部现金余额，百万美元（周度）→ /1000
  - RRPONTSYD  隔夜逆回购 ON RRP，十亿美元（日度）→ 原值
  - SOFR       担保隔夜融资利率，%（日度）→ 原值（%）

YAML 声明在 data-sources.yaml（coverage: [macro]），正常路径走
`intent macro`（fred 先行，argo nbs_stats 检索兜底）。
"""
from __future__ import annotations

import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SOURCE_LABEL = "FRED 宏观序列"
API_BASE = "https://api.stlouisfed.org/fred/series/observations"
ENV_KEY = "FRED_API_KEY"
DEFAULT_TIMEOUT = 20
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
        return True, f"{ENV_KEY} 已配置"
    return False, f"缺少 {ENV_KEY}（FRED 免费注册：https://fred.stlouisfed.org/docs/api/api_key.html）"


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


def _net_liquidity(walcl: float, tga: float, onrrp: float) -> float:
    """净流动性 = 美联储总资产 − TGA − ON RRP（invest-macro 核心公式，十亿美元）。"""
    return walcl - tga - onrrp


def liquidity() -> dict[str, Any]:
    """净流动性三序列 + 派生计算。返回 envelope（route 风格 {source,kind,ok,data,error}）。"""
    api_key = load_api_key()
    if not api_key:
        return {"source": "fred", "kind": "macro", "ok": False, "data": None,
                "error": f"缺少 {ENV_KEY}"}
    series: dict[str, Any] = {}
    errors: list[str] = []
    for sid, meta in SERIES.items():
        rows, err = _fetch_series(sid, api_key)
        if err:
            errors.append(f"{sid}: {err}")
            continue
        vals = [{"date": r["date"], "value": round(r["value"] * meta["mult"], 2)} for r in rows]
        series[sid] = {"label": meta["label"], "unit": meta["unit"], "obs": vals}
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
    return {"source": "fred", "kind": "macro", "ok": True, "data": data, "error": None}


if __name__ == "__main__":  # 快速自检：python3 sources/fred.py
    import json

    print(json.dumps(liquidity(), ensure_ascii=False, indent=2, default=str)[:2000])
