#!/usr/bin/env python3
"""ttskill 数据源接入的离线契约测试 — 不联网。

守护三件事：
1. yaml 声明与适配器文件必须同步存在（防「文档有、实现无」复发）；
2. ttskill 优先级必须高于 hithink（fund 默认链首位，官方结构化优先）；
3. period 标题→中文标签映射不被误改（110011 实测反推，改了会错位）。
"""
from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SKILL = SCRIPTS.parent

from sources.ttskill import PERIOD_LABELS  # noqa: E402


def test_yaml_and_adapter_both_present() -> None:
    yaml_text = (SKILL / "data-sources.yaml").read_text(encoding="utf-8")
    assert "ttskill:" in yaml_text, "data-sources.yaml 缺少 ttskill 声明"
    assert (SCRIPTS / "sources" / "ttskill.py").is_file(), "适配器 sources/ttskill.py 缺失"
    assert "adapters: [ttskill]" in yaml_text


def test_native_primary_then_optional_ttskill() -> None:
    """fund 主路=自带 hithink(60) > ttskill 可选(55) > eastmoney(50)。"""
    import re
    yaml_text = (SKILL / "data-sources.yaml").read_text(encoding="utf-8")

    def prio_of(name: str) -> int:
        m = re.search(rf"\n  {name}:\n(?:\s+\S[^\n]*\n)*?\s+priority:\s*(\d+)", yaml_text)
        return int(m.group(1)) if m else -1

    assert prio_of("hithink") > prio_of("ttskill") > prio_of("eastmoney"), "应为 hithink>ttskill>eastmoney"


def test_period_label_mapping_intact() -> None:
    """实测（110011）反推的映射，关键码不得缺失/错位。"""
    assert PERIOD_LABELS["Y"] == "近1月回报"
    assert PERIOD_LABELS["3Y"] == "近3月回报"
    assert PERIOD_LABELS["1N"] == "近1年回报"
    assert PERIOD_LABELS["JN"] == "今年来回报"
    assert PERIOD_LABELS["LN"] == "成立来回报"


def test_module_exposes_fund() -> None:
    import importlib
    mod = importlib.import_module("sources.ttskill")
    assert callable(getattr(mod, "fund"))
    assert getattr(mod, "SOURCE_LABEL") == "天天基金 ttskill"
