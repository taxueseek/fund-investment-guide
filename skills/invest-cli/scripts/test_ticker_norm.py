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
    assert normalize_ticker("MSFT") == "MSFT"


def test_dotted_symbols_are_not_rewritten_by_shape() -> None:
    """点号**不得**按字符串形状改写。

    点号在美股语境里既可能是类别股（BRK.B → BRK-B），也可能是交易所后缀
    （VOD.L 伦敦、VOW3.F 法兰克福）。按「纯字母基名 + 单字母后缀」改写后，
    `us VOD.L` 从有数据变成报错（实测）。类别股改由空壳回退判定（见
    test_perf_guards 的 `test_us_class_share_falls_back_to_hyphen`）。
    """
    assert normalize_ticker("BRK.B") == "BRK.B"
    assert normalize_ticker("VOD.L") == "VOD.L"
    assert normalize_ticker("VOW3.F") == "VOW3.F"
    assert normalize_ticker("0700.HK") == "0700.HK"
    assert normalize_ticker("600519.SS") == "600519.SS"


if __name__ == "__main__":
    test_hk_five_digit()
    test_cn_sh_sz()
    test_us_passthrough()
    test_dotted_symbols_are_not_rewritten_by_shape()
    print("test_ticker_norm: OK")
