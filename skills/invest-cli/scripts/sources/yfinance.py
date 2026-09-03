"""Yahoo Finance (yfinance) 数据源适配器。

复用 scripts/cmd_us.py 的取数与输出，返回结构一致。
yfinance 天然支持 .SS/.SZ/.HK 后缀，因此除美股外也担当
A股/港股快照链的兜底源（route.fetch 末位；A股主路仍是同花顺/东财）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def us(symbol: str) -> dict:
    return _fetch("us", symbol)


def stock(keyword: str) -> dict:
    """A股/港股兜底（yfinance 支持 .SS/.SZ/.HK）。"""
    return _fetch("stock", keyword)


def _fetch(kind: str, symbol: str) -> dict:
    try:
        from cmd_us import fetch_us_data
    except ImportError as e:
        return {"source": "yfinance", "kind": kind, "ok": False, "data": None,
                "error": f"yfinance 未安装: {e}"}
    try:
        return {"source": "yfinance", "kind": kind, "ok": True, "data": fetch_us_data(symbol.upper()), "error": None}
    except Exception as e:
        return {"source": "yfinance", "kind": kind, "ok": False, "data": None, "error": f"yfinance 取数失败: {e}"}
