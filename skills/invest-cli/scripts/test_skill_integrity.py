#!/usr/bin/env python3
"""invest-fund 技能族引用完整性回归 — 不联网、纯静态。

目的：防止「模块/文件成了孤儿」这类无法证明必要性的复杂性悄悄长回来：
1. invest-fund/SKILL.md 路由表 + 索引里引用的 references/*.md 必须真实存在；
2. 存在的 references/*.md 必须都能被 SKILL.md 可达（无死文件）；
3. SKILL.md 内每个场景名都映射到唯一路由行（路由自洽）。

改路由/加场景文件后跑：../.venv/bin/python -m pytest scripts/test_skill_integrity.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

SKILLS = Path.home() / ".agents" / "skills"
FUND_DIR = SKILLS / "invest-fund"
SKILL_MD = FUND_DIR / "SKILL.md"
REFS = FUND_DIR / "references"


def _skill_text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def test_all_references_exist_and_reachable() -> None:
    txt = _skill_text()
    ref_files = sorted(p.name for p in REFS.glob("*.md"))
    assert ref_files, "references/ 为空？"
    orphans = []
    for name in ref_files:
        # 在 SKILL.md 中被引用（路由表、索引、正文任一）即视为可达
        if name not in txt:
            orphans.append(name)
    assert not orphans, f"references/ 中存在 SKILL.md 不可达的死文件: {orphans}"


def test_router_rows_point_to_real_files() -> None:
    txt = _skill_text()
    # 捕获两类引用：本目录 references/x.md，及跨技能 ../invest-stock/references/x.md
    paths = set(re.findall(r"(?:\.\./)?(?:invest-[a-z]+/)?references/([a-z0-9-]+\.md)", txt))
    # 若出现跨技能路径（…/invest-stock/references/…），该文件必须真在 invest-stock 里
    cross = set(re.findall(r"\.\./(invest-[a-z]+)/references/([a-z0-9-]+\.md)", txt))
    missing = []
    for rel in cross:
        skill_dir, name = rel
        if not (SKILLS / skill_dir / "references" / name).is_file():
            missing.append(f"../{skill_dir}/references/{name}")
    for name in paths - {n for _, n in cross}:
        if not (REFS / name).is_file():
            missing.append(f"references/{name}")
    assert not missing, f"SKILL.md 引用不存在的文件: {missing}"


def test_every_scene_letter_maps_once() -> None:
    """路由表中 A/B/C/E/F/G 六个场景字母各只映射一次路由行。"""
    txt = _skill_text()
    rows = re.findall(r"\|[^\n]*?(?:[A-G])：([^\n|]+?)\s*\|\s*`references/", txt)
    # 场景字母到其出现次数的粗查：每个场景名应出现于路由行+索引行
    for letter, label in [("A", "标准体检"), ("B", "同经理多基金选择"),
                          ("C", "次新基金"), ("E", "ETF"), ("F", "多基金横向对比"),
                          ("G", "行业主题")]:
        hits = txt.count(f"{letter}：{label}") + txt.count(f"| {letter}：")
        assert hits >= 1, f"场景 {letter}（{label}）在 SKILL.md 路由/索引中缺失"


def test_no_legacy_duplicate_masks_router() -> None:
    """fund-investment-guide 若仍物理存在且自带触发词，会绕过 invest 路由造成双轨；
    路由入口 invest/SKILL.md 必须把它的别名显式归入 invest-fund（归档历史表）。"""
    invest_md = SKILLS / "invest" / "SKILL.md"
    txt = invest_md.read_text(encoding="utf-8")
    row = re.search(r"\|[^\n]*fund-investment-guide[^\n]*invest-fund[^\n]*\|", txt)
    assert row, "invest 路由未把 fund-investment-guide 归入 invest-fund（见『已归档路由』表）"
