"""capabilities 子命令：数据源能力发现层。

为什么需要（2026-09-03 教训）：invest-cli 曾因"不知道外部源有什么"而重复低效——
盈米 69 工具只收敛 5 个、ttskill 37 包只封装 4 个，其余靠记忆必然遗忘，
Agent 遇到未封装场景只能现场翻官方包学调用（低效且易错）。
本命令让三件事一处可见：外部源有什么、invest-cli 收敛到哪、怎么调。

用法:
    invest-cli capabilities              数据源总览 + 高层入口速查
    invest-cli capabilities yingmi       盈米 69 工具清单（动态）+ 收敛标注
    invest-cli capabilities ttskill      天天基金 37 包清单（动态）+ 收敛标注
    invest-cli capabilities <source> --json    JSON 输出（给 skill 层做路由决策）

注意：本命令只列清单与标注，不取业务数据。取数仍走 fund/stock/intent 高层入口
或 yingmi/ttskill/wind 透传。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# —— 已收敛到 invest-cli 高层入口的外部工具（改 cmd_intent/适配器时同步维护） ——
YINGMI_CONVERGED: dict[str, str] = {
    "GuessFundCode": "自动分类/名称→代码（intent classify）",
    "SearchFunds": "intent screen fund（关键词搜基金）",
    "GetFundDiagnosis": "intent deep fund（先诊断，快照链回退）",
    "DiagnoseFundPortfolio": "intent portfolio（持仓组合诊断）",
    "GetAssetAllocationPlan": "intent plan（资产配置方案）",
}
TTSKILL_CONVERGED: dict[str, str] = {
    "TTFUND_SEARCH": "fund 快照链内嵌（名称→代码）",
    "TTFUND_BASE_INFOS": "fund 快照链内嵌（详情+业绩+风险族）",
    "TTFUND_HOLDING_INFO": "fund 快照链内嵌（重仓+行业+资产配置）",
    "TTFUND_GOLD_INFO": "intent deep commodity（黄金）",
}
# 账户/交易域：invest-cli 定位只读数据分析，不为这些建高层入口（透传不新增权限，
# 但分析链路不消费持仓/下单类数据）。列在此处仅为清单标注。
_TTSKILL_BOUNDARY = {
    "ACCOUNT_HOLDING", "ACCOUNT_PROFIT", "TRADE_QUERY", "CONDITION_ORDER",
    "SIM_TRADE", "SUBACCOUNT", "RATION_PLAN",
}


def converge_status(source: str, tool_id: str) -> str:
    """外部工具 → invest-cli 收敛状态：✅ 已收敛 / 🔒 边界外 / ⬜ 透传可用。"""
    table = YINGMI_CONVERGED if source == "yingmi" else TTSKILL_CONVERGED
    if tool_id in table:
        return f"✅ {table[tool_id]}"
    if source == "ttskill" and tool_id in _TTSKILL_BOUNDARY:
        return "🔒 账户/交易域（不建高层入口，数据链路不消费）"
    return "⬜ 透传: invest-cli yingmi <tool> 或 ttskill <skill_id>"


# —— 动态清单获取（官方 CLI 为准，不手写第二份数据） ——
def _yingmi_tools() -> list[dict]:
    """yingmi-skill-cli mcp list → [{name, description}]；不可用返回 []。"""
    import shutil
    import subprocess

    exe = shutil.which("yingmi-skill-cli")
    if not exe:
        return []
    try:
        proc = subprocess.run([exe, "mcp", "list"], capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        tools = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [
        {"name": t.get("name", ""), "description": (t.get("description") or t.get("summary") or "").strip()}
        for t in tools if t.get("name")
    ]


def _ttskill_skills() -> list[dict]:
    """ttskill skill list --json → [{skill_id, status, install_path, description}]。

    description 从本地 SKILL.md frontmatter 提取（skill list 不返回描述）。
    不可用时返回 []。
    """
    import shutil
    import subprocess

    exe = shutil.which("ttskill")
    if not exe:
        return []
    try:
        proc = subprocess.run([exe, "skill", "list", "--json"], capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout or "{}")
        skills = (data.get("skills") if isinstance(data, dict) else None) or []
    except json.JSONDecodeError:
        return []

    desc_cache: dict[str, str] = {}
    for s in skills:
        sid = s.get("skill_id", "")
        ip = (s.get("install_path") or "").replace("\\", "/")
        # 安装目录树：<root>/<skill_id>/<version>/SKILL.md 或 <root>/<skill_id>/SKILL.md
        candidates = [Path(ip) / "SKILL.md"]
        if ip:
            root = Path(ip)
            for cand in (root / "SKILL.md", root.parent / "SKILL.md", root.parent.parent / "SKILL.md"):
                candidates.append(cand)
        for cand in candidates:
            if cand.is_file():
                text = cand.read_text(encoding="utf-8", errors="ignore")[:600]
                m = re.search(r"(?ms)^description:\s*[>|-]?\s*\n?(.*?)\n---", text)
                if m:
                    raw = m.group(1).strip().splitlines()
                    desc_cache[sid] = (raw[0] if raw else "")[:150]
                break
    return [
        {
            "skill_id": s.get("skill_id", ""),
            "status": s.get("status", ""),
            "description": desc_cache.get(s.get("skill_id", ""), ""),
        }
        for s in skills
    ]


def _fmt_row(cells: list[str], widths: list[int]) -> str:
    return "  " + "  ".join(f"{c[:w]:<{w}}" for c, w in zip(cells, widths))


def run(source: str, as_json: bool = False) -> int:
    if source in ("", "sources", "all"):
        from sources import registry

        states = registry.detect_all()
        rows = [
            ["源", "优先级", "覆盖", "可用", "说明"],
            ["---", "---", "---", "---", "---"],
        ]
        for sid in sorted(states, key=lambda k: -states[k].get("priority", 0)):
            st = states[sid]
            avail = "✅" if st.get("available") else "❌"
            rows.append([st.get("name", sid), str(st.get("priority", "")),
                         ",".join(st.get("coverage", [])), avail, str(st.get("detail", ""))[:60]])
        if as_json:
            print(json.dumps({k: {"available": v["available"], "detail": v["detail"]}
                              for k, v in states.items()}, ensure_ascii=False, indent=2))
            return 0
        print("\n  数据源总览（invest-cli datasources 同源）\n")
        for row in rows:
            print(_fmt_row(row, [26, 6, 24, 4, 62]))
        print("\n  高层入口速查：")
        print("    fund <代码> / stock <代码> / us <代码> / screen <条件>")
        print("    intent deep <fund|stock|bond|commodity> <标的>   意图深取")
        print("    intent screen/portfolio/plan/macro                意图筛选/组合/方案/宏观")
        print("    info <词> / watchlist                             资讯(argo)/自选")
        print("    透传（高级/补漏）：wind / yingmi / ttskill — 清单见下方子命令")
        print("    capabilities yingmi | ttskill                     官方能力清单+收敛标注")
        return 0

    if source == "yingmi":
        tools = _yingmi_tools()
        if not tools:
            print("盈米不可用或未安装 yingmi-skill-cli", file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps([{"name": t["name"], "status": converge_status("yingmi", t["name"]),
                               "description": t["description"]} for t in tools],
                             ensure_ascii=False, indent=2))
            return 0
        print(f"\n  盈米且慢工具清单（官方 mcp list 动态，共 {len(tools)} 个）\n")
        for t in sorted(tools, key=lambda x: (converge_status("yingmi", x["name"]).startswith("⬜"), x["name"])):
            line = f"  {t['name']:<38} {converge_status('yingmi', t['name'])}"
            print(line)
            desc = (t["description"] or "").replace("\n", " ")[:150]
            if desc:
                print(f"      {desc}")
        print("\n  参数以官方 schema 为准；拿不准先取官方工具描述，或搜 examples。")
        return 0

    if source == "ttskill":
        skills = _ttskill_skills()
        if not skills:
            print("ttskill 不可用或未安装（先 ttskill login --env prod）", file=sys.stderr)
            return 1
        if as_json:
            print(json.dumps([{"skill_id": s["skill_id"], "status": converge_status("ttskill", s["skill_id"]),
                               "description": s["description"]} for s in skills],
                             ensure_ascii=False, indent=2))
            return 0
        print(f"\n  天天基金官方业务包（ttskill skill list 动态，共 {len(skills)} 个）\n")
        for s in sorted(skills, key=lambda x: (converge_status("ttskill", x["skill_id"]).startswith("⬜"), x["skill_id"])):
            st = converge_status("ttskill", s["skill_id"])
            line = f"  {s['skill_id']:<34} {st}"
            print(line)
            if s["description"]:
                print(f"      {s['description'][:140]}")
        print("\n  透传调用示例：invest-cli ttskill MANAGER_INFO --input '{\"manager_name\":\"谢治宇\"}'")
        print("  参数以官方包 examples/*.example.json 为准。")
        return 0

    print(f"未知 source: {source}（可选: yingmi / ttskill / 空=总览）", file=sys.stderr)
    return 1
