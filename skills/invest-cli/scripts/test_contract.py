#!/usr/bin/env python3
"""Contract tests — no live Eastmoney required."""
from __future__ import annotations

from cmd_fund import normalize_fields as fund_norm
from cmd_fund import resolve_fund_code
from cmd_stock import normalize_fields as stock_norm
from cmd_stock import resolve_code
from _common import find_invest_cli, pick_screen_columns, strip_paren_suffix


def test_stock_aliases() -> None:
    m = stock_norm(
        {
            "净资产收益率ROE(加权)": "10.57%",
            "每股收益EPS(基本)": "21.76元",
            "市盈率PE(TTM)": "18.91倍",
        }
    )
    assert m["净资产收益率ROE"] == "10.57%"
    assert m["每股收益EPS"] == "21.76元"
    assert resolve_code("茅台") == "600519"
    assert resolve_code("600519") == "600519"


def test_fund_map() -> None:
    assert resolve_fund_code("易方达蓝筹") == "005827"
    assert resolve_fund_code("易方达蓝筹精选") == "005827"
    assert resolve_fund_code("005827") == "005827"
    m = fund_norm({"今年以来回报": "-17", "Sharpe": "-0.9", "波动率(年化)": "9%"})
    assert m["今年来回报"] == "-17"
    assert m["夏普比率"] == "-0.9"
    assert m["波动率"] == "9%"


def test_screen_columns() -> None:
    keys = [
        "代码",
        "名称",
        "最新价(元)(2026.05.22)",
        "涨跌幅(%)(2026.05.22)",
        "市盈率(TTM)(倍)(2026.05.22)",
    ]
    cols = pick_screen_columns(keys)
    assert "代码" in cols
    assert any("最新价" in c for c in cols)
    assert strip_paren_suffix("最新价(元)(2026.05.22)") == "最新价"


def test_find_cli() -> None:
    p = find_invest_cli()
    assert p.is_file() and p.name == "invest_cli.py"


if __name__ == "__main__":
    test_stock_aliases()
    test_fund_map()
    test_screen_columns()
    test_find_cli()
    print("test_contract: OK")
