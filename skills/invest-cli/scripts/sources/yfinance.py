"""Yahoo Finance (yfinance) 数据源适配器。

复用 scripts/cmd_us.py 的取数与输出，返回结构一致。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SCRIPTS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def detect() -> tuple[bool, str]:
    from .registry import _probe_python

    return _probe_python("yfinance")


def us(symbol: str) -> dict:
    try:
        from cmd_us import fetch_us_data
    except ImportError as e:
        return {"source": "yfinance", "kind": "us", "ok": False, "data": None,
                "error": f"yfinance 未安装: {e}"}
    try:
        return {"source": "yfinance", "kind": "us", "ok": True, "data": fetch_us_data(symbol.upper()), "error": None}
    except Exception as e:
        return {"source": "yfinance", "kind": "us", "ok": False, "data": None, "error": f"yfinance 取数失败: {e}"}
