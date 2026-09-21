#!/usr/bin/env python3
"""FRED 适配器回归测试 — 不联网，mock 两条取数通道。

所有用例走 liquidity(use_cache=False)：本文件测的是「取数通道与口径」，
缓存读写由 test_source_guards.py 单独守卫，避免缓存命中把 mock 短路。
缓存目录隔离由 conftest.py 统一提供（这里不再各文件各写一份）。

背景：intent macro 净流动性 = WALCL − WDTGAL − RRPONTSYD。
单位换算：WALCL/WDTGAL 是百万美元，RRPONTSYD 是十亿美元，统一为十亿。
通道：有 key 走官方 API；无 key 回退 fredgraph.csv（transport=csv）。
"""
from __future__ import annotations

from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

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


def test_keyless_fallback() -> None:
    """无 key 时回退 fredgraph.csv（transport=csv），不再直接判不可用。"""
    orig_key = fred.load_api_key
    orig_csv = fred._fetch_series_keyless
    fred.load_api_key = lambda: None  # type: ignore[assignment]
    fred._fetch_series_keyless = lambda sid, **kw: ([{"date": "2026-09-16", "value": 100.0}], None)  # type: ignore[assignment]
    try:
        res = fred.liquidity(use_cache=False)
        assert res["ok"] is True
        assert res["data"]["transport"] == "csv"
    finally:
        fred.load_api_key = orig_key  # type: ignore[assignment]
        fred._fetch_series_keyless = orig_csv  # type: ignore[assignment]


def test_both_transports_fail() -> None:
    """两条通道都失败 → ok=False（走 argo 兜底），不抛异常。"""
    orig_key = fred.load_api_key
    orig_csv = fred._fetch_series_keyless
    fred.load_api_key = lambda: None  # type: ignore[assignment]
    fred._fetch_series_keyless = lambda sid, **kw: (None, "FRED CSV 请求失败: timeout")  # type: ignore[assignment]
    try:
        res = fred.liquidity(use_cache=False)
        assert res["ok"] is False and res["data"] is None
    finally:
        fred.load_api_key = orig_key  # type: ignore[assignment]
        fred._fetch_series_keyless = orig_csv  # type: ignore[assignment]


if __name__ == "__main__":
    test_net_liquidity_formula()
    test_unit_conversion()
    test_keyless_fallback()
    test_both_transports_fail()
    print("test_fred: OK")
