#!/usr/bin/env python3
"""
invest-cli — 投资分析 CLI 工具（主入口）

用法:
    invest-cli stock <代码/名称>    A股/港股分析
    invest-cli fund <代码/名称>     基金分析
    invest-cli us <代码>            美股分析
    invest-cli screen <条件>        选股（东方财富）

选项:
    --json      输出结构化 JSON（给 skill 层用）
    --refresh   跳过缓存

示例:
    invest-cli stock 600519
    invest-cli stock 茅台 --json
    invest-cli fund 006195
    invest-cli us AAPL
    invest-cli screen "市盈率低于10的银行股"
"""

import sys
import os
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def cmd_stock(args):
    from cmd_stock import resolve_code, fetch_stock_data, format_terminal
    code = resolve_code(args.keyword)
    data = fetch_stock_data(code)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_fund(args):
    from cmd_fund import resolve_fund_code, fetch_fund_data, format_terminal
    code = resolve_fund_code(args.keyword)
    data = fetch_fund_data(code)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_us(args):
    from cmd_us import fetch_us_data, format_terminal
    data = fetch_us_data(args.symbol)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def parse_markdown_table(md: str) -> list[dict]:
    """解析 markdown 表格为 list[dict]"""
    lines = [l.strip() for l in md.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    # 表头
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:  # 跳过表头和分隔线
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def cmd_screen(args):
    """选股 - 调用东方财富选股 API"""
    import requests
    api_key = os.getenv("EASTMONEY_APIKEY")
    if not api_key:
        print("错误: 未设置 EASTMONEY_APIKEY", file=sys.stderr)
        sys.exit(1)

    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen"
    resp = requests.post(
        url,
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json={"keyword": args.condition, "pageNo": 1, "pageSize": 20},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()

    if args.json:
        import json
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 终端输出：东财选股返回 markdown 表格文本
    try:
        d = result["data"]["data"]
        partial = d.get("partialResults", "")
        security_count = d.get("securityCount", 0)
        total_condition = d.get("totalCondition", "")

        rows = parse_markdown_table(partial)

        if not rows:
            print("未找到结果，请调整筛选条件")
            return

        print(f"\n✅ 找到 {security_count} 只符合条件的股票\n")
        if total_condition:
            print(f"🔍 筛选条件: {total_condition}\n")

        # 取前 6 列展示
        all_keys = list(rows[0].keys())
        # 优先展示这些列
        priority = ["代码", "名称", "最新价(元)(2026.05.22)", "涨跌幅(%)(2026.05.22)", "市盈率(TTM)(倍)(2026.05.22)", "市净率(倍)(2026.05.22)", "总市值(元)(2026.05.22)"]
        keys = [k for k in priority if k in all_keys][:6]
        if not keys:
            keys = all_keys[:6]

        # 缩短列名
        short_names = []
        for k in keys:
            # 去掉括号内的日期后缀
            import re
            short = re.sub(r'\(.*?\)$', '', k).strip()
            short_names.append(short[:12])

        print("  " + "  ".join(f"{h:<14}" for h in short_names))
        print("  " + "-" * (16 * len(keys)))

        for row in rows[:15]:
            vals = [str(row.get(k, "-"))[:14] for k in keys]
            print("  " + "  ".join(f"{v:<14}" for v in vals))

        if security_count > 15:
            print(f"\n  ... 还有 {security_count - 15} 条结果")

    except (KeyError, IndexError) as e:
        print(f"解析结果失败: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="invest-cli — 投资分析 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # stock
    p_stock = subparsers.add_parser("stock", help="A股/港股分析")
    p_stock.add_argument("keyword", help="股票代码或名称")
    p_stock.add_argument("--json", action="store_true")

    # fund
    p_fund = subparsers.add_parser("fund", help="基金分析")
    p_fund.add_argument("keyword", help="基金代码或名称")
    p_fund.add_argument("--json", action="store_true")

    # us
    p_us = subparsers.add_parser("us", help="美股分析")
    p_us.add_argument("symbol", help="美股代码")
    p_us.add_argument("--json", action="store_true")

    # screen
    p_screen = subparsers.add_parser("screen", help="选股")
    p_screen.add_argument("condition", help="选股条件")
    p_screen.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "stock": cmd_stock,
        "fund": cmd_fund,
        "us": cmd_us,
        "screen": cmd_screen,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
