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
from sources import load_registry


def test_stock_code_pass_through() -> None:
    assert resolve_code("600519") == "600519"
    assert resolve_code("00700") == "00700"


def test_fund_code_pass_through() -> None:
    assert resolve_fund_code("005827") == "005827"
    assert resolve_fund_code("006195") == "006195"
    # 易方达蓝筹(精选) = 005827；110011 现为「易方达优质精选(QDII)」，旧映射指向它属错误
    assert resolve_fund_code("易方达蓝筹") == "005827"
    assert resolve_fund_code("易方达蓝筹精选") == "005827"


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


def test_hithink_registered() -> None:
    reg = load_registry()
    assert "hithink" in reg
    assert reg["hithink"]["priority"] == 60
    assert set(reg["hithink"]["coverage"]) == {"stock", "fund"}


def test_ttskill_registered() -> None:
    reg = load_registry()
    assert "ttskill" in reg
    assert reg["ttskill"]["priority"] == 55  # 自带 hithink(60) 之上不再：官方为可选深取
    assert set(reg["ttskill"]["coverage"]) == {"fund"}
    assert reg["ttskill"]["adapters"] == ["ttskill"]
    # 登录态探测走模块 detect()（status --json 的 is_expired），不是文本匹配
    assert reg["ttskill"]["detect"]["type"] == "env_or_file"
    from sources.ttskill import detect

    assert callable(detect)


def test_ttskill_common_run_guard() -> None:
    from sources.ttskill import _common_run

    # 正常名：查询与候选名共享 ≥3 字连续片段
    assert _common_run("兴全合润", "兴全合润混合A") >= 3
    assert _common_run("蓝筹", "易方达蓝筹精选混合") >= 2
    # 垃圾名：最长公共片段只有「基金」2 字，且查询有效汉字 ≥3 → 阈值 3 → 拒绝
    assert _common_run("不存在的基金xyz999", "招商行业精选股票基金") < 3


def test_ttskill_code_pass_through() -> None:
    from sources.ttskill import resolve_fcode

    assert resolve_fcode("163406") == ("163406", "163406")
    assert resolve_fcode("110011") == ("110011", "110011")


def test_ttskill_fund_live() -> None:
    """联网深度用例：ttskill 未登录或不在 PATH 时跳过；163406 为冒烟基准。"""
    import shutil
    import subprocess

    from sources.ttskill import fund

    if shutil.which("ttskill") is None:
        return
    status = subprocess.run(["ttskill", "status"], capture_output=True, text=True, timeout=15)
    if "auth token: present" not in (status.stdout or ""):
        return
    res = fund("163406")
    assert res["ok"], res["error"]
    d = res["data"]
    assert d["code"] == "163406" and d["name"], "代码/名称缺失"
    assert d["data"].get("基金类型"), "类型缺失"
    assert d["data"].get("基金规模"), "规模缺失"
    assert d["data"].get("经理姓名") == "谢治宇", "经理解析漂移"
    assert d["data"].get("近1年回报") is not None, "近1年收益缺失"
    assert d["data"].get("最大回撤"), "回撤缺失"
    assert d["data"].get("申购费率") is not None, "申购费缺失"
    assert len(d["holdings"]) == 10, "重仓不足10只"


if __name__ == "__main__":
    test_stock_code_pass_through()
    test_fund_code_pass_through()
    test_screen_columns()
    test_find_cli()
    test_hithink_registered()
    test_ttskill_registered()
    test_ttskill_common_run_guard()
    test_ttskill_code_pass_through()
    test_ttskill_fund_live()
    print("test_contract: OK")
