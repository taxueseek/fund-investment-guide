#!/usr/bin/env python3
"""美股股息率单位回归测试 — 不联网，只测归一化与展示格式化。

背景：yfinance 0.2.x 的 dividendYield 是小数（0.0032），1.x 起改为百分数（0.32）。
展示层固定 ×100，导致 AAPL 曾显示 33.00%（真实约 0.32%）。
"""
from __future__ import annotations

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
