#!/usr/bin/env python3
"""FRED 适配器回归测试 — 不联网，mock _fetch_series。

背景：intent macro 净流动性 = WALCL − WDTGAL − RRPONTSYD。
单位换算：WALCL/WDTGAL 是百万美元，RRPONTSYD 是十亿美元，统一为十亿。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sources.fred as fred  # noqa: E402


def test_net_liquidity_formula() -> None:
    """核心公式：净流动性 = 总资产 − TGA − ON RRP。"""
    assert fred._net_liquidity(7000.0, 500.0, 300.0) == 6200.0
    assert fred._net_liquidity(100.0, 100.0, 0.0) == 0.0


def test_unit_conversion() -> None:
    """WALCL 百万美元 → 十亿美元（÷1000）；RRPONTSYD 已是十亿。"""
    rows = [{"date": "2026-09-02", "value": 6_450_000.0}]  # WALCL 百万
    mult = fred.SERIES["WALCL"]["mult"]
    assert round(rows[0]["value"] * mult, 2) == 6450.0
    assert fred.SERIES["RRPONTSYD"]["mult"] == 1.0


def test_missing_key() -> None:
    """无 key 时返回 ok=False，不清零也不抛异常（走 argo 兜底）。"""
    orig = fred.load_api_key
    fred.load_api_key = lambda: None  # type: ignore[assignment]
    try:
        res = fred.liquidity()
        assert res["ok"] is False and res["data"] is None
    finally:
        fred.load_api_key = orig


if __name__ == "__main__":
    test_net_liquidity_formula()
    test_unit_conversion()
    test_missing_key()
    print("test_fred: OK")
