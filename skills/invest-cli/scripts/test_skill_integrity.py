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


# ── 全家族交叉引用守卫（2026-09-22 补）
#
# 成因实录：`invest-analyst` 的 **frontmatter description**（常驻加载层）写着
# 「invest-industry 做『行业是什么』」，而全机四套 skills 根都没有 invest-industry——
# 它在 skills 列表里查无此名，是重命名（现名 taxue-industry）后没跟上的悬空指针。
# 常驻层里的悬空指针每次会话都要付 token，而且会把路由引向不存在的技能。
#
# 判据：invest-* / taxue-* 形式的技能名，只要出现在**非归档语境**里，
# 就必须能在 skills 根里找到同名目录。归档名走显式白名单（它们出现在
# 「已归档路由」「维护」这类历史记录里，是正确内容）。

INVEST_FAMILY = ("invest", "invest-stock", "invest-fund", "invest-asset", "invest-allocation",
                 "invest-discuss", "invest-macro", "invest-analyst", "invest-cli")

# 历史上真实存在、已被合并/归档的技能名（会出现在归档记录里，允许出现）
_ARCHIVED = frozenset({
    "invest-bond", "invest-convertible", "invest-commodity", "invest-reit",
    "invest-report", "invest-fund-manager", "invest-us", "invest-hk-a",
    "invest-institutional", "invest-fund-read", "invest-industry-historical",
})
# 归档语境的标记词：命中则该行不参与检查
_ARCHIVE_CTX = ("归档", "已并入", "合并", "原文", "已删除", "退役", "archive", "旧名", "废弃")


def _installed_skill_names() -> set[str]:
    names: set[str] = set()
    for root in (Path.home() / ".agents" / "skills", Path.home() / ".claude" / "skills"):
        if root.is_dir():
            names.update(p.name for p in root.iterdir() if p.is_dir())
    return names


def test_skill_pointers_resolve() -> None:
    """invest-* / taxue-* 活引用必须指向真实存在的技能目录。"""
    installed = _installed_skill_names()
    missing: list[str] = []
    # 别用 \b 收尾：中文里技能名后面紧跟着汉字是常态（「invest-industry做…」），
    # 而 Python 的 \w 默认把汉字算作词字符，`y`→`做` 之间**不存在**词边界，
    # 于是 \b 会让这条守卫静默失效——首版就是这么写的，跑在出问题的旧文本上
    # 依然"通过"（空断言）。改用负向断言：前后不得紧跟同类字符。
    pattern = re.compile(r"(?<![a-z0-9-])(?:invest|taxue)-[a-z0-9]+(?:-[a-z0-9]+)*(?![a-z0-9-])")
    for skill in INVEST_FAMILY:
        md = SKILLS / skill / "SKILL.md"
        if not md.is_file():
            continue
        for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            if any(mark in line for mark in _ARCHIVE_CTX):
                continue
            for tok in pattern.findall(line):
                if tok in installed or tok in _ARCHIVED or tok == skill:
                    continue
                missing.append(f"{skill}/SKILL.md:{lineno} → {tok}")
    assert not missing, (
        "技能名悬空引用（重命名后没跟上，会把路由引向不存在的技能）：\n  " + "\n  ".join(missing)
    )


def test_shared_references_are_symlinks_not_copies() -> None:
    """共享方法论只允许软链，不允许在成员目录留副本（副本必然漂移）。"""
    shared = SKILLS / "invest" / "_shared" / "references"
    if not shared.is_dir():
        return
    names = {p.name for p in shared.glob("*.md")}
    copies: list[str] = []
    for skill in INVEST_FAMILY:
        refs = SKILLS / skill / "references"
        if not refs.is_dir():
            continue
        for name in names:
            cand = refs / name
            if cand.exists() and not cand.is_symlink():
                copies.append(f"{skill}/references/{name}")
    assert not copies, f"共享方法论出现实体副本（应为软链）: {copies}"


def test_cli_runtime_doc_is_cited_and_marked() -> None:
    """`invest/references/cli-runtime.md` 的两个派生表已作废，必须带作废标记。

    实测它曾同时具备三种病：① 无任何 SKILL.md 引用（孤儿）；② 载着第三份
    「数据源分工」表（真源是 invest 入口的映射表）；③ 内容陈旧到与运行态相反
    （写「宏观 → argo」，实际 FRED 优先；写「东财缺 key 当前空链」，实际已配；
    写 wind 依赖 wind-mcp-skill 目录，实际直连 MCP）。孤儿 + 陈旧 + 重复三合一。
    """
    doc = SKILLS / "invest" / "references" / "cli-runtime.md"
    if not doc.is_file():
        return
    txt = doc.read_text(encoding="utf-8")
    assert "已作废" in txt or "作废" in txt, "陈旧表未带作废标记，读者会把它们当真源"
    invest_md = (SKILLS / "invest" / "SKILL.md").read_text(encoding="utf-8")
    assert "cli-runtime" in invest_md, "cli-runtime.md 又是孤儿（没有任何 SKILL.md 指向它）"


def test_pointer_guard_regex_actually_matches() -> None:
    """守卫自检：正则必须能抓到「技能名紧贴汉字」这种最常见形态。

    首版用 `\b` 收尾，汉字被 Python 的 `\w` 视为词字符，`invest-industry做`
    之间没有词边界 → 正则匹配不到 → 守卫在出问题的旧文本上也能"通过"。
    这条用例专门钉住那个失效模式。
    """
    import re as _re

    pattern = _re.compile(r"(?<![a-z0-9-])(?:invest|taxue)-[a-z0-9]+(?:-[a-z0-9]+)*(?![a-z0-9-])")
    samples = [
        "invest-industry做「行业是什么」",          # 紧贴汉字（旧文本的真实形态）
        "该走 taxue-industry，不是别的",            # 后跟全角逗号
        "见 invest-stock/references/x.md",          # 后跟斜杠：只应匹配 invest-stock
        "invest-us 已归档",
    ]
    assert "invest-industry" in pattern.findall(samples[0]), "紧贴汉字时抓不到"
    assert "taxue-industry" in pattern.findall(samples[1])
    assert pattern.findall(samples[2]) == ["invest-stock"], "路径形态应只取技能名部分"
    assert "invest-us" in pattern.findall(samples[3])


# ── 引用路径可达性（全家族，2026-09-22 补）
#
# 首版扫描只认反引号包住的 `references/x.md`，于是漏掉两件不同的事：
#   ① 跨技能写法 `../invest-stock/references/x.md` 会被截成 `references/x.md`
#      再拿去本目录找，误报缺失（实测 invest-fund 的两处都被误报）；
#   ② 工作区根相对写法 `invest-fund/references/data-pipeline.md`（invest-cli 第 167 行）
#      同样被截断误报。
# 这些都是**检查器自己的毛病**，不是文档的毛病——所以判据改成：把整条路径 token
# 完整取出，分别按「相对该 skill 目录」「相对 skills 根」两条解析，任一命中即可。
# 真正测出来的只有一条：invest-asset 把 `commodity-gold.md` 写成裸文件名（同文件
# 其余四处都带 `references/` 前缀），读者得靠猜目录——已修正。

_PATH_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_./-])((?:\.\./)?(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.*-]+\.md)(?![A-Za-z0-9_-])"
)


def test_reference_paths_resolve() -> None:
    """SKILL.md 里出现的每个 .md 路径都必须能按书写形式解析到真实文件。"""
    unresolved: list[str] = []
    for skill in INVEST_FAMILY:
        md = SKILLS / skill / "SKILL.md"
        if not md.is_file():
            continue
        for lineno, line in enumerate(md.read_text(encoding="utf-8").splitlines(), 1):
            for m in _PATH_TOKEN.finditer(line):
                rel = m.group(1)
                ok = False
                for cand in (SKILLS / skill / rel, SKILLS / rel):
                    if "*" in str(cand):
                        ok = bool(list(cand.parent.glob(cand.name)))
                    else:
                        ok = cand.exists()
                    if ok:
                        break
                if not ok:
                    unresolved.append(f"{skill}/SKILL.md:{lineno} → {rel}")
    assert not unresolved, "引用路径按书写形式解析不到（读者/agent 只能靠猜目录）：\n  " + "\n  ".join(unresolved)


def test_reference_path_guard_catches_bare_filename() -> None:
    """守卫自检：裸文件名必须被判为不可解析（它正是实测出的那一类）。

    同时必须**不**误报跨技能写法与 skills 根相对写法——首版就是因为把这两种截断
    才报了 3 个假阳性。
    """
    samples = {
        "（见 commodity-gold.md）": False,                 # 裸名 → 应报
        "见 `references/asset-bond.md`": True,             # 本目录 → 应通过
        "详见 `../invest-stock/references/manager-patterns.md`": True,   # 跨技能 → 应通过
        "真源 = `invest-fund/references/data-pipeline.md`": True,        # 根相对 → 应通过
        "见 `references/asset-*.md`": True,                # glob → 应通过
    }
    for line, should_pass in samples.items():
        rels = [m.group(1) for m in _PATH_TOKEN.finditer(line)]
        assert rels, f"匹配器没抓到路径 token: {line}"
        # 用 invest-asset 作为基准目录判定
        ok = True
        for rel in rels:
            hit = False
            for cand in (SKILLS / "invest-asset" / rel, SKILLS / rel):
                if "*" in str(cand):
                    hit = bool(list(cand.parent.glob(cand.name)))
                else:
                    hit = cand.exists()
                if hit:
                    break
            ok = ok and hit
        assert ok is should_pass, f"{line!r} 判定错误（期望 {'通过' if should_pass else '报错'}）"


# ── 跨根引用守卫 ────────────────────────────────────────────────────────────
# 上面那些守卫只覆盖本仓的 skills 树。但 workbuddy 侧的入口页（tencent-invest 的
# 路由页）**恰恰是用来指路到本仓技能的**，它落在另一个根目录下，路径守卫管不到。
# 这类引用一旦悬空，用户会被指到一个不存在的技能（第四轮修过 invest-industry 那一次，
# 就是同一类；本轮新增路由页时我自己又写错了一次 invest-us）。
_WORKBUDDY_ROUTING = Path.home() / ".workbuddy" / "skills" / "tencent-invest" / "SKILL.md"
# 「已并入/已归档」这类说明句里出现的历史技能名不算悬空引用 —— 它们是在解释去向
_HISTORICAL = ("已并入", "归档", "archive", "已合并", "已删除")


def test_workbuddy_routing_page_only_points_to_live_skills():
    if not _WORKBUDDY_ROUTING.is_file():
        pytest.skip("本机没有 workbuddy 路由页（非目标环境）")
    text = _WORKBUDDY_ROUTING.read_text(encoding="utf-8")
    missing: list[str] = []
    for line in text.splitlines():
        if any(mark in line for mark in _HISTORICAL):
            continue
        # 前一个字符不能是 `-` 或 `_`：否则会命中**路径/文件名**里的片段。
        # 实测假阳性：`2026-09-22_tencent-invest-absorbed-scripts/` 被切出
        # `invest-absorbed-scripts`，把一条正确的归档说明报成悬空引用。
        for name in re.findall(r"(?<![-_\w])invest[a-z-]*", line):
            name = name.rstrip("-")
            if name and not (SKILLS / name / "SKILL.md").is_file():
                missing.append(f"{name} （出现在: {line.strip()[:70]}）")
    assert not missing, "路由页指向了不存在的技能：\n  " + "\n  ".join(missing)
