"""screen 子命令：选股（**股票**筛选）。

用法:
    invest-cli screen <条件> [--json]

数据源：东方财富选股 API（stock-screen）——按定义只筛股票。
筛基金走 `invest-cli intent screen`（带「基金/ETF/债基」等词时路由到盈米）。

本模块与 cmd_sec / cmd_info / cmd_watchlist 同构：终端排版是命令自己的事，
入口 invest_cli.py 只负责 argparse 与分发。
"""
from __future__ import annotations

import json
import sys

from _common import pick_screen_columns, strip_paren_suffix

# 终端一次最多列多少行（东财 partialResults 只带首页，见下面 remaining 的注释）
MAX_ROWS = 15


def parse_markdown_table(md: str) -> list[dict]:
    """解析 markdown 表格为 list[dict]（东财 partialResults 的格式）。"""
    lines = [l.strip() for l in md.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:  # 跳过表头和分隔线
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def run(condition: str, as_json: bool = False) -> int:
    from sources.route import fetch

    res = fetch("screen", condition)
    if not res.get("ok"):
        print(f"错误: {res.get('error')}", file=sys.stderr)
        return 1
    result = res.get("data") or {}

    # 「上游没答上来」与「上游答了、但没有符合条件的股票」是两件不同的事，
    # 必须分开报——旧写法把两者都落进「未找到结果，请调整筛选条件」并 rc=0。
    #
    # 实测（monkeypatch 上游回包）：`data.data` 为 null（上游业务失败）与
    # `data.data = {"securityCount": 0, "partialResults": ""}`（真的零结果）
    # 输出**一模一样**，rc 都是 0。用户/agent 于是会去改筛选条件——改一个本来
    # 没问题的条件；真实原因是这次请求根本没拿到结果体（空条件即如此）。
    #
    # 判据：有没有拿到**结果体**。东财适配器对业务失败仍返回 ok=True（它只保证
    # 传输成功），所以区分只能在解析层做。
    d = (result.get("data") or {}).get("data")
    if not isinstance(d, dict) or not d:
        print(f"选股失败：上游未返回结果体（条件：{condition}）", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # 终端输出：东财选股返回 markdown 表格文本
    try:
        partial = d.get("partialResults") or ""
        security_count = d.get("securityCount") or 0
        total_condition = d.get("totalCondition") or ""

        rows = parse_markdown_table(partial)
        if not rows:
            # 走到这里说明上游**确实答了**（结果体非空）但没有匹配行，
            # 这时「未找到结果」才是真话。
            print("未找到结果，请调整筛选条件")
            return 0

        print(f"\n✅ 找到 {security_count} 只符合条件的股票\n")
        if total_condition:
            print(f"🔍 筛选条件: {total_condition}\n")

        # 取前 6 列展示（动态列名，不硬编码日期）
        keys = pick_screen_columns(list(rows[0].keys()), limit=6)
        short_names = [strip_paren_suffix(k)[:12] for k in keys]

        print("  " + "  ".join(f"{h:<14}" for h in short_names))
        print("  " + "-" * (16 * len(keys)))

        shown = rows[:MAX_ROWS]
        for row in shown:
            vals = [str(row.get(k, "-"))[:14] for k in keys]
            print("  " + "  ".join(f"{v:<14}" for v in vals))

        # 剩余条数必须按**实际打印的行数**算，不能按固定常量：
        # partialResults 只带首页（实测 pageSize=20 时仅 10 行），
        # 旧写法在 17 条结果时说「还有 2 条」，而实际少了 7 条。
        remaining = security_count - len(shown)
        if remaining > 0:
            print(f"\n  ... 还有 {remaining} 条结果")

    except (KeyError, IndexError, TypeError, ValueError) as e:
        print(f"解析结果失败: {e}")
        return 1
    return 0


if __name__ == "__main__":  # 便于单独调试：python3 cmd_screen.py "市盈率低于10的银行股"
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "", as_json="--json" in sys.argv))
