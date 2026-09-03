#!/usr/bin/env python3
"""intent 场景路由契约 — 不打外部网络。

覆盖 2026-08-30 review 修复的回归点：
1. portfolio/plan/present 的 ROUTES 必须是可调用 lambda（曾是裸 tuple → TypeError）
2. deep bond 路由到 wind bond_data 且保留标的代码
3. present 路由到本地 cmd_present（不再引用不存在的 Wind RenderHtmlToPdf）
4. classify 英文类型词精确匹配（bond/gold/commodity 不误判美股）
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cmd_intent import (  # noqa: E402
    ROUTES,
    _dispatch,
    classify,
)


def test_scene_routes_are_callable() -> None:
    """present/portfolio/plan 的 default 必须是 lambda，不能是裸 tuple。"""
    for scene in ("portfolio", "plan", "present"):
        r = ROUTES[scene]["default"]
        assert callable(r), f"{scene} default 不可调用: {r!r}"


def test_dispatch_scene_shapes() -> None:
    for scene, kind in (
        ("portfolio", "yingmi"),
        ("plan", "yingmi"),
        ("present", "present_html"),
    ):
        d = _dispatch(scene, "示例输入")
        assert d["route"][0] == kind, f"{scene} 应路由到 {kind}，实际 {d}"
    d = _dispatch("portfolio", '{"totalAssets": 1000000}')
    assert d["route"][0] == "yingmi"
    assert d["route"][2] == {"input": '{"totalAssets": 1000000}'}  # 原文打包；JSON 解析在 run() 层


def test_present_no_ghost_wind_tool() -> None:
    """不得再引用 wind-mcp-skill 中不存在的 RenderHtmlToPdf。"""
    assert "RenderHtmlToPdf" not in str(ROUTES)


def test_deep_bond_keeps_target() -> None:
    """deep bond 必须把标的代码带进路由（wind bond_data question）。"""
    d = _dispatch("deep", "bond 019547.SH")
    assert d["route"][0] == "wind_bond"
    assert "019547.SH" in str(d["route"][1])
    assert d["type"] == "bond"


def test_deep_commodity_routes_ttskill_gold() -> None:
    # ttfund 已退役：黄金深取改走官方 TTFUND_GOLD_INFO
    d = _dispatch("deep", "commodity AU9999")
    assert d["route"][0] == "ttskill_scene"
    assert d["route"][1] == "TTFUND_GOLD_INFO"
    assert d["route"][2] == {"query_scope": "gold"}


def test_classify_english_type_words() -> None:
    assert classify("bond") == "bond"
    assert classify("BOND") == "bond"
    assert classify("gold") == "commodity"
    assert classify("commodity") == "commodity"
    assert classify("AAPL") == "us"  # 真美股代码不受影响


if __name__ == "__main__":
    test_scene_routes_are_callable()
    test_dispatch_scene_shapes()
    test_present_no_ghost_wind_tool()
    test_deep_bond_keeps_target()
    test_deep_commodity_routes_ttskill_gold()
    test_classify_english_type_words()
    print("test_intent_scenes: OK")
