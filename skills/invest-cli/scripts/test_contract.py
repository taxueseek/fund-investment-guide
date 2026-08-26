#!/usr/bin/env python3
"""Contract tests — no live Eastmoney required."""
from __future__ import annotations

from cmd_stock import resolve_code
from cmd_fund import resolve_fund_code
from _common import (
    find_invest_cli,
    pick_screen_columns,
    strip_paren_suffix,
)


def test_stock_code_pass_through() -> None:
    assert resolve_code("600519") == "600519"
    assert resolve_code("00700") == "00700"


def test_fund_code_pass_through() -> None:
    assert resolve_fund_code("005827") == "005827"
    assert resolve_fund_code("006195") == "006195"


def test_screen_columns() -> None:
    keys = [
        "代码",
        "名称",
        "最新价(元)(2026.09.01)",
        "涨跌幅(%)(2026.09.01)",
        "市盈率(TTM)(倍)(2026.09.01)",
    ]
    cols = pick_screen_columns(keys)
    assert "代码" in cols
    assert any("最新价" in c for c in cols)
    assert strip_paren_suffix("最新价(元)(2026.05.22)") == "最新价"


def test_find_cli() -> None:
    p = find_invest_cli()
    assert p.is_file() and p.name == "invest_cli.py"


if __name__ == "__main__":
    test_stock_code_pass_through()
    test_fund_code_pass_through()
    test_screen_columns()
    test_find_cli()
    print("test_contract: OK")
