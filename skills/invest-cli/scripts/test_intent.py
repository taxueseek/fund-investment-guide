#!/usr/bin/env python3
"""intent 分类与选股路由契约 — 不打盈米/东财网络。"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cmd_intent import (  # noqa: E402
    _dispatch,
    classify,
    kind_from_code,
)


def test_kind_from_code() -> None:
    assert kind_from_code("600519") == "stock"
    assert kind_from_code("000858") is None  # 与基金 00xxxx 重叠
    assert kind_from_code("300750") == "stock"
    assert kind_from_code("688981") == "stock"
    assert kind_from_code("110011") == "fund"
    assert kind_from_code("161725") == "fund"
    assert kind_from_code("510300") == "fund"
    assert kind_from_code("00700") == "stock"
    assert kind_from_code("茅台") is None


def test_classify_does_not_call_yingmi_for_shanghai() -> None:
    import cmd_intent as m

    def boom(_t: str) -> bool:
        raise AssertionError("600519 不得打盈米 GuessFundCode")

    orig = m._is_fund_by_yingmi
    m._is_fund_by_yingmi = boom  # type: ignore[assignment]
    try:
        assert classify("600519") == "stock"
        assert classify("300750") == "stock"
        assert classify("110011") == "fund"
        assert classify("AAPL") == "us"
        assert classify("易方达蓝筹精选混合") == "fund"
    finally:
        m._is_fund_by_yingmi = orig


def test_screen_defaults_to_eastmoney() -> None:
    d = _dispatch("screen", "市盈率低于10的银行股")
    assert d["route"][0] == "eastmoney_screen"
    d2 = _dispatch("screen", "夏普大于1的基金")
    assert d2["route"][0] == "yingmi"


if __name__ == "__main__":
    test_kind_from_code()
    test_classify_does_not_call_yingmi_for_shanghai()
    test_screen_defaults_to_eastmoney()
    print("test_intent: OK")
