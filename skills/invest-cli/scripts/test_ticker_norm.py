#!/usr/bin/env python3
"""yfinance ticker 规范化回归测试 — 不联网。

背景：yfinance 兜底 A股/港股（route.fetch('stock') 末位）。
6 位 A 股代码须带 .SS/.SZ 后缀，5 位港股须去前导零 + .HK（00700 → 0700.HK）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cmd_us import normalize_ticker  # noqa: E402


def test_hk_five_digit() -> None:
    assert normalize_ticker("00700") == "0700.HK"
    assert normalize_ticker("09988") == "9988.HK"
    assert normalize_ticker("03690") == "3690.HK"


def test_cn_sh_sz() -> None:
    assert normalize_ticker("600519") == "600519.SS"
    assert normalize_ticker("688981") == "688981.SS"
    assert normalize_ticker("000858") == "000858.SZ"
    assert normalize_ticker("300750") == "300750.SZ"


def test_us_passthrough() -> None:
    assert normalize_ticker("AAPL") == "AAPL"
    assert normalize_ticker("brk.b") == "BRK.B"


if __name__ == "__main__":
    test_hk_five_digit()
    test_cn_sh_sz()
    test_us_passthrough()
    print("test_ticker_norm: OK")
