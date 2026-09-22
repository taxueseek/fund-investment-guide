#!/usr/bin/env python3
"""美股股息率单位回归测试 — 不联网，只测归一化与展示格式化。

背景：yfinance 0.2.x 的 dividendYield 是小数（0.0032），1.x 起改为百分数（0.32）。
展示层固定 ×100，导致 AAPL 曾显示 33.00%（真实约 0.32%）。
"""
from __future__ import annotations

import re

from cmd_us import _format_yfinance, normalize_dividend_yield


def test_prefer_rate_over_price() -> None:
    """有年化股息和现价时，用 rate/price 重算，忽略 dividendYield 的单位歧义。"""
    info = {"trailingAnnualDividendRate": 1.05, "dividendYield": 0.33}
    got = normalize_dividend_yield(info, 325.6)
    assert got is not None
    assert abs(got - 1.05 / 325.6) < 1e-9


def test_fallback_percent_raw() -> None:
    """无年化股息，且 dividendYield 是百分数（yfinance 1.x）。"""
    assert normalize_dividend_yield({"dividendYield": 5.52}, None) is not None
    got = normalize_dividend_yield({"dividendYield": 5.52}, None)
    assert abs(got - 0.0552) < 1e-9


def test_fallback_fraction_raw() -> None:
    """无年化股息，且 dividendYield 是小数（yfinance 0.2.x）。"""
    got = normalize_dividend_yield({"dividendYield": 0.0235}, None)
    assert abs(got - 0.0235) < 1e-9


def test_fallback_percent_one_boundary() -> None:
    """1.0 边界：1.x 百分数最小合法值 1.00%（=1.0），不得当小数放大成 100%。"""
    got = normalize_dividend_yield({"dividendYield": 1.0}, None)
    assert abs(got - 0.01) < 1e-9


def test_missing_and_zero_price() -> None:
    assert normalize_dividend_yield({}, None) is None
    assert normalize_dividend_yield({"dividendYield": None}, 100.0) is None
    # 现价为 0 时不能除零，回退到 dividendYield
    got = normalize_dividend_yield({"trailingAnnualDividendRate": 1.0, "dividendYield": 2.0}, 0)
    assert abs(got - 0.02) < 1e-9


def test_format_shows_percent_not_amplified() -> None:
    """端到端：低股息股不能被放大成 33.00%。"""
    data = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "currency": "USD",
        "timestamp": "2026-09-02T23:00:00",
        "quote": {"price": 325.6, "dividend_yield": 1.05 / 325.6, "beta": 1.08},
        "financial": {},
        "analyst": {},
        "risk": {},
        "business": {},
    }
    out = _format_yfinance(data)
    assert "0.32%" in out
    assert "33.00%" not in out


def test_format_high_yield_stock() -> None:
    data = {
        "symbol": "VZ",
        "name": "Verizon",
        "currency": "USD",
        "timestamp": "2026-09-02T23:00:00",
        "quote": {"price": 43.0, "dividend_yield": 2.37 / 43.0},
        "financial": {},
        "analyst": {},
        "risk": {},
        "business": {},
    }
    out = _format_yfinance(data)
    assert "5.51%" in out or "5.52%" in out


def test_minor_unit_currency_not_underestimated_by_100() -> None:
    """次单位报价（GBp）下不得把股息率算小 100 倍。

    实测 `us VOD.L`：currency=GBp、price=127.35、trailingAnnualDividendRate≈0.046（GBP）。
    旧公式 0.046/127.35 = 0.000361（0.036%），而同一时刻 yfinance 的
    dividendYield = 3.11（即 3.11%）。股息是**主单位**、价格是**次单位**，
    直接相除跨了单位。
    """
    info = {"trailingAnnualDividendRate": 0.046}
    got = normalize_dividend_yield(info, 127.35, "GBp")
    assert got is not None
    assert abs(got - 0.046 * 100 / 127.35) < 1e-9
    assert 0.03 < got < 0.04, f"股息率量级仍不对：{got}"


def test_major_unit_currency_unchanged() -> None:
    """反向用例：主单位报价（USD/JPY/HKD）不得被 ×100。"""
    info = {"trailingAnnualDividendRate": 1.05}
    for cur in ("USD", "JPY", "HKD", "EUR", ""):
        got = normalize_dividend_yield(info, 325.6, cur)
        assert abs(got - 1.05 / 325.6) < 1e-9, f"{cur} 被误放大"


def _payload(currency: str, target: float = 663.85) -> dict:
    return {
        "symbol": "00700", "name": "Tencent Holdings", "currency": currency,
        "timestamp": "2026-09-22T22:00:00",
        "quote": {"price": 451.6}, "financial": {},
        "analyst": {"recommendation": "strong_buy", "target_price": target,
                    "analyst_count": 41},
        "risk": {}, "business": {},
    }


def test_target_price_currency_follows_payload() -> None:
    """目标价的货币符号必须跟着载荷里的货币，不能写死 `$`。

    实测 `stock hk00700` 落到 yfinance 兜底时（东财港股查询失败时发生）：
    标题下一行印「货币: HKD」，分析师那段却印「$663.85」——同一屏两个币种，
    而 664 港币 ≈ 85 美元，读者按美元理解会差一个量级。
    """
    hk = _format_yfinance(_payload("HKD"), title="港股快照")
    assert "  货币: HKD" in hk
    assert "目标价: HK$663.85" in hk
    # 同一屏里不能出现「货币: HKD」却用裸 $ 标价
    # （不能写成 `"$663.85" not in hk`：HK$663.85 里含有这个子串，会误判）
    assert not re.search(r"目标价: \$\d", hk), "港币标价仍用了美元符号"
    # 美股口径不变（USD 仍走 $）
    us = _format_yfinance(_payload("USD", target=328.22))
    assert "目标价: $328.22" in us


def test_unknown_currency_reports_code_not_a_guess() -> None:
    """认不出的币种报代码，不挑一个近似的符号冒充（挑错比不挑更难发现）。"""
    out = _format_yfinance(_payload("XYZ"), title="快照")
    assert "目标价: 663.85 XYZ" in out
    assert not re.search(r"目标价: \$\d", out)
    # 老缓存/上游缺 currency 字段时沿用 yfinance 域的既有默认 USD（不炸、不空）
    assert "目标价: $663.85" in _format_yfinance(_payload(""), title="快照")
