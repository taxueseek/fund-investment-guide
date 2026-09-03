#!/usr/bin/env python3
"""声称回归门 — 声明（yaml/SKILL 文档）↔ 实现 一致性。

背景：fund 链优先级一天内改向多次（ttskill 75→55），声明散布在 6 处人肉同步，
每次都漏（docs 说「首位」、入口表缺行、退役命令仍被引用）。漂移必须在此变红，
不等 agent 拿着错误地图取数。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources import load_registry  # noqa: E402

SKILL = _SCRIPTS.parent                 # invest-cli/
SKILLS_ROOT = SKILL.parent              # skills/

# 参与「同一份链序声明」的活文档（退役/归档语境除外）
LIVE_DOCS = [
    SKILL / "SKILL.md",
    SKILL / "docs" / "data-sources.md",
    SKILLS_ROOT / "invest" / "SKILL.md",
    SKILLS_ROOT / "invest-fund" / "SKILL.md",
    SKILLS_ROOT / "invest-fund" / "references" / "data-pipeline.md",
    SKILLS_ROOT / "invest-macro" / "SKILL.md",
]

INFRA_MODULES = {"__init__", "registry", "route"}


def test_yaml_adapters_bijection() -> None:
    """yaml 声明的适配器必须有文件；sources/ 下的适配器必须在 yaml 登记（单一真源闭环）。"""
    src_dir = SKILL / "scripts" / "sources"
    on_disk = {p.stem for p in src_dir.glob("*.py")} - INFRA_MODULES
    registry = load_registry()
    assert registry, "data-sources.yaml 解析为空"
    declared: set[str] = set()
    for sid, conf in registry.items():
        for name in conf.get("adapters") or [sid]:
            declared.add(name)
            assert (src_dir / f"{name}.py").is_file(), f"yaml 声明的适配器 sources/{name}.py 不存在"
    assert on_disk == declared, (
        f"适配器与 yaml 不同步：磁盘多出 {sorted(on_disk - declared)}，"
        f"yaml 多出 {sorted(declared - on_disk)}（argo 类资讯源也必须入册，门闩不允许旁路）"
    )


def test_fund_chain_prose_order() -> None:
    """所有活文档的链序声明必须一致：主路 = hithink，ttskill 只是可选深取。

    用负向断言钉住已知漂移形态（比「出现顺序」启发式更准——表格行的主语
    本身可以是 ttskill，先出现不代表它在链前）：
      1. 箭头链把 ttskill 排在 hithink 之前
      2. 声称 ttskill 是「首位」
      3. 把「主路」判给 ttskill
    """
    wrong_forms = [
        re.compile(r"ttskill[^→\n]*→\s*hithink"),
        re.compile(r"(链)?首位[^。\n|]*ttskill|ttskill[^。\n|]*首位"),
        re.compile(r"主路\s*[=:：]\s*[^。\n|]*ttskill"),
    ]
    somewhere_claims_primary = False
    for doc in LIVE_DOCS:
        assert doc.is_file(), f"活文档缺失: {doc}"
        for i, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if "hithink" in line and "主路" in line:
                somewhere_claims_primary = True
            for pat in wrong_forms:
                assert not pat.search(line), (
                    f"{doc.relative_to(SKILLS_ROOT)}:{i} 链序声明漂移: {line.strip()}"
                )
    assert somewhere_claims_primary, "活文档必须至少有一处声明 hithink 为主路"


def test_retired_ttfund_command_absent() -> None:
    """ttfund 老 CLI 已退役：命令形态不得再出现在活文档（agent 会照抄执行）。"""
    forbidden = re.compile(
        r"invest-cli ttfund|invest_cli\.py ttfund|`ttfund (login|status|macro|bond|gold|diagnose|pick|allocate|research)"
    )
    for doc in LIVE_DOCS:
        text = doc.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{doc.name} 仍引用已退役的 ttfund 命令"
    for py in (_SCRIPTS / "invest_cli.py",):
        assert "ttfund" not in py.read_text(encoding="utf-8"), "invest_cli.py 不得再挂 ttfund 子命令"


def test_entry_source_table_covers_all_sources() -> None:
    """invest 入口的「数据源门闩」表必须覆盖 yaml 全部源（含不经链的 argo），且无 ttfund 残留。"""
    entry = SKILLS_ROOT / "invest" / "SKILL.md"
    text = entry.read_text(encoding="utf-8")
    cn_names = {
        "hithink": "同花顺", "eastmoney": "东方财富", "yfinance": "yfinance",
        "bitget": "Bitget", "wind": "Wind", "yingmi": "盈米",
        "ttskill": "ttskill", "argo": "argo",
    }
    for sid in load_registry():
        assert sid in text or cn_names.get(sid, sid) in text, f"入口数据源表缺 {sid}"
    assert "ttfund" not in text, "入口 SKILL.md 仍有小写 ttfund 残留（TTFUND_* 官方包名不受限）"


if __name__ == "__main__":
    test_yaml_adapters_bijection()
    test_fund_chain_prose_order()
    test_retired_ttfund_command_absent()
    test_entry_source_table_covers_all_sources()
    print("test_claims: OK")
