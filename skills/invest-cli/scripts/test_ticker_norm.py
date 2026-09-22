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


def test_cn_all_segments_covered() -> None:
    """反回归：每个真实号段都必须拿到后缀。

    此前用逐个号段枚举（`^00[013]\\d{3}$|^30[01]\\d{3}$`），002 段被漏掉——
    `002594`（比亚迪）拿不到 `.SZ`，末位兜底的 yfinance 直接判「未找到」，
    用户看到的是「三个源都没有这只票」。枚举必然漂移，故此用例按**号段族**
    逐个钉住，新增号段漏掉时会在这里失败。

    沪市：600/601/603/605（主板）、688/689（科创板）
    深市：000/001/002/003（主板/原中小板）、300/301（创业板）
    """
    sh = ["600519", "601398", "603259", "605499", "688981", "689009"]
    sz = ["000858", "001979", "002594", "003816", "300750", "301236"]
    for code in sh:
        assert normalize_ticker(code) == f"{code}.SS", f"沪市 {code} 后缀丢失"
    for code in sz:
        assert normalize_ticker(code) == f"{code}.SZ", f"深市 {code} 后缀丢失"


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
    test_cn_all_segments_covered()
    test_us_passthrough()
    test_dotted_symbols_are_not_rewritten_by_shape()
    print("test_ticker_norm: OK")


def test_internal_whitespace_is_cleaned() -> None:
    """代码里的**内部空格**必须清掉。

    实测 `us "A A P L"`：yfinance 那条不清洗、判为「不存在的标的」，
    而 bitget 那条会自己清洗成 AAPL 并成功——同一个输入两条源结论相反，
    用户拿到一个 USDT 代币价（非官方价）而不是真实报价，且 rc=0。
    """
    assert normalize_ticker("A A P L") == "AAPL"
    assert normalize_ticker(" AAPL ") == "AAPL"
    assert normalize_ticker("6 00519") == "600519.SS"
    assert normalize_ticker("0 0 7 0 0") == "0700.HK"
