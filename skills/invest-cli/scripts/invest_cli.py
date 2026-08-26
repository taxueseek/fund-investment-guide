#!/usr/bin/env python3
"""
invest-cli — 投资分析 CLI 工具（主入口）

用法:
    invest-cli stock <代码/名称>    A股/港股分析（东财）
    invest-cli fund <代码/名称>     基金分析（东财）
    invest-cli us <代码>            美股分析（yfinance）
    invest-cli screen <条件>        选股（东财）
    invest-cli datasources          列出并探测数据源可用性
    invest-cli wind <server_type> <tool> --input '<json>'  透传万得 Wind
    invest-cli yingmi <tool> --input '<json>'              透传盈米且慢

选项:
    --json      输出结构化 JSON（给 skill 层用）
    --refresh   跳过缓存

示例:
    invest-cli stock 600519
    invest-cli stock 茅台 --json
    invest-cli fund 006195
    invest-cli us AAPL
    invest-cli screen "市盈率低于10的银行股"
    invest-cli datasources
    invest-cli wind stock_data get_stock_price_indicators --input '{"windcode":"600519.SH"}'
    invest-cli yingmi GetCurrentTime
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

        # 取前 6 列展示（动态列名，不硬编码日期）
        from _common import pick_screen_columns, strip_paren_suffix
        all_keys = list(rows[0].keys())
        keys = pick_screen_columns(all_keys, limit=6)
        short_names = [strip_paren_suffix(k)[:12] for k in keys]

        print("  " + "  ".join(f"{h:<14}" for h in short_names))
        print("  " + "-" * (16 * len(keys)))

        for row in rows[:15]:
            vals = [str(row.get(k, "-"))[:14] for k in keys]
            print("  " + "  ".join(f"{v:<14}" for v in vals))

        if security_count > 15:
            print(f"\n  ... 还有 {security_count - 15} 条结果")

    except (KeyError, IndexError) as e:
        print(f"解析结果失败: {e}")


def cmd_datasources(args):
    from cmd_datasources import run
    sys.exit(run(as_json=args.json))


def cmd_wind(args):
    from cmd_wind import run
    sys.exit(run(args.server_type, args.tool_name, args.input, as_json=args.json))


def cmd_yingmi(args):
    from cmd_yingmi import run
    sys.exit(run(args.tool_name, args.input, as_json=args.json))


def cmd_ttfund(args):
    from cmd_ttfund import run
    sys.exit(run(args.args, as_json=args.json))


def cmd_intent(args):
    from cmd_intent import run
    value = list(args.value)
    as_json = args.json
    if "--json" in value:
        value.remove("--json")
        as_json = True
    sys.exit(run(args.scene, " ".join(value), as_json=as_json))


def cmd_info(args):
    from cmd_info import run
    sys.exit(run(args.query, engine=args.engine, as_json=args.json))


def cmd_watchlist(args):
    from cmd_watchlist import run
    sys.exit(run(args.action, code=args.code, name=getattr(args, "name", ""),
                 typ=getattr(args, "type", ""), with_quote=getattr(args, "with_quote", False),
                 as_json=args.json))


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

    # datasources
    p_ds = subparsers.add_parser("datasources", help="列出并探测数据源可用性")
    p_ds.add_argument("--json", action="store_true")

    # wind（万得透传）
    p_wind = subparsers.add_parser("wind", help="透传万得 Wind 数据源")
    p_wind.add_argument("server_type", help="server_type，如 stock_data/fund_data/index_data")
    p_wind.add_argument("tool_name", help="工具名，如 get_stock_price_indicators")
    p_wind.add_argument("--input", default="{}", help="参数 JSON")
    p_wind.add_argument("--json", action="store_true")

    # yingmi（盈米透传）
    p_ym = subparsers.add_parser("yingmi", help="透传盈米且慢数据源")
    p_ym.add_argument("tool_name", help="工具名，如 GuessFundCode/GetFundDiagnosis")
    p_ym.add_argument("--input", default="{}", help="参数 JSON")
    p_ym.add_argument("--json", action="store_true")

    # ttfund（天天基金场景透传）
    p_tt = subparsers.add_parser("ttfund", help="透传天天基金 ttfund 场景命令")
    p_tt.add_argument("args", nargs=argparse.REMAINDER, help="ttfund 子命令与参数")
    p_tt.add_argument("--json", action="store_true")

    # intent（意图层，收敛接口面）
    p_int = subparsers.add_parser("intent", help="按意图取数（deep/screen/portfolio/plan/macro/present）")
    p_int.add_argument("scene", help="语义场景：deep/screen/portfolio/plan/macro/present")
    p_int.add_argument("value", nargs=argparse.REMAINDER, help="场景参数（deep 为 <type> <标的>）")
    p_int.add_argument("--json", action="store_true")

    # info（财经检索，走 argo）
    p_info = subparsers.add_parser("info", help="财经检索/资讯/舆情（走 argo，省配额）")
    p_info.add_argument("query", help="检索词")
    p_info.add_argument("--engine", default="eastmoney", help="eastmoney/zhihu/cninfo/cn-web-search")
    p_info.add_argument("--json", action="store_true")

    # watchlist（本地自选股）
    p_wl = subparsers.add_parser("watchlist", help="本地自选股（add/remove/list）")
    p_wl.add_argument("action", help="add/remove/list")
    p_wl.add_argument("code", nargs="?", default="", help="标的代码（add/remove 用）")
    p_wl.add_argument("--name", default="", help="自选名称")
    p_wl.add_argument("--type", default="", help="fund/stock")
    p_wl.add_argument("--with-quote", action="store_true", help="列表时附行情")
    p_wl.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    dispatch = {
        "stock": cmd_stock,
        "fund": cmd_fund,
        "us": cmd_us,
        "screen": cmd_screen,
        "datasources": cmd_datasources,
        "wind": cmd_wind,
        "yingmi": cmd_yingmi,
        "ttfund": cmd_ttfund,
        "intent": cmd_intent,
        "info": cmd_info,
        "watchlist": cmd_watchlist,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
