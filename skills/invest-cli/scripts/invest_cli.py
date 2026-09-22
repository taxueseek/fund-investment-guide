#!/usr/bin/env python3
"""
invest-cli — 投资分析 CLI 工具（主入口）

用法:
    invest-cli stock <代码/名称>    A股/港股分析（A股同花顺优先，港股东财）
    invest-cli fund <代码/名称>     基金分析（同花顺优先，失败回退东财）
    invest-cli us <代码>            美股分析（yfinance，缺省回退腾讯行情/Bitget）
    invest-cli quote <代码...>      免鉴权实时行情（一次请求多标的、跨市场，130ms 量级）
    invest-cli kline <代码>         K线（原生 ~130ms；分钟级转 westock CLI）
    invest-cli sec <代码>           SEC EDGAR 美股财报原文（10-K XBRL 指标 + 最近申报）
    invest-cli screen <条件>        选股（东财）
    invest-cli westock <args...>   透传腾讯微证券 CLI（筹码/龙虎榜/资金流/一致预期/产业链/板块…）
    invest-cli datasources          列出并探测数据源可用性
    invest-cli wind <server_type> <tool> --input '<json>'  透传万得 Wind
    invest-cli yingmi <tool> --input '<json>'              透传盈米且慢
    invest-cli ttskill <skill_id> --input '<json>'         透传天天基金官方业务包
    invest-cli capabilities [yingmi|ttskill]               能力清单+收敛标注（发现层）

选项:
    --json      输出结构化 JSON（给 skill 层用）

示例:
    invest-cli stock 600519
    invest-cli stock 茅台 --json
    invest-cli fund 110011
    invest-cli us AAPL
    invest-cli quote 600519,00700,AAPL
    invest-cli kline 600519 --period month --limit 12
    invest-cli westock chip 600519
    invest-cli sec AAPL --filings 5
    invest-cli screen "市盈率低于10的银行股"
    invest-cli datasources
    invest-cli wind stock_data get_stock_price_indicators --input '{"windcode":"600519.SH"}'
    invest-cli yingmi GetCurrentTime
    invest-cli ttskill MANAGER_INFO --input '{"manager_name":"谢治宇"}'
    invest-cli capabilities ttskill
"""

import sys
import os
import argparse
import warnings

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 第三方库在导入期发出的告警（典型：urllib3 2.x 在 LibreSSL 下报
# NotOpenSSLWarning）会直接写到 stderr，污染正常输出与错误信息——
# CLI 的 stderr 是给人和 agent 读的错误通道，不该被库噪音占据。
#
# category 必须写 **Warning**：该告警继承链为
#   NotOpenSSLWarning → SecurityWarning → HTTPWarning → Warning
# 与 UserWarning **无继承关系**，用 UserWarning 或 message 正则都拦不住
# （实测两者均无效，只有 Warning + module 生效）。
# 这里覆盖所有走本入口的命令；被单独执行的 cmd_*.py 在各自文件里同样装了
# 这条过滤器（entry point 不止一个，过滤器就得跟着入口走）。
warnings.filterwarnings("ignore", category=Warning, module=r"urllib3.*")


def _relax_output_encoding() -> None:
    """把 stdout/stderr 的编码错误处理放宽为 replace，避免整条命令崩掉。

    实测：`PYTHONIOENCODING=ascii invest-cli stock 600519` 直接抛
    `UnicodeEncodeError: 'ascii' codec can't encode characters ...` 并打出完整
    traceback（在一轮 78 次真实调用里，这是**唯一**一条 traceback）。

    CLI 的输出契约是「中文指标名 + 数值」：环境编码表达不了中文时，正确行为是
    **降级输出**（不可编码字符替成 `?`）并保持 rc=0，而不是抛异常、丢掉整份数据、
    把栈帧倒给用户。只在编码确实非 UTF-8 时才动，正常环境零影响。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            enc = (getattr(stream, "encoding", "") or "").lower()
            if enc and enc.replace("-", "") != "utf8":
                stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass


def cmd_stock(args):
    from cmd_stock import fetch_stock_with_fallback, format_terminal
    try:
        data = fetch_stock_with_fallback(args.keyword)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_fund(args):
    from cmd_fund import fetch_fund_with_fallback, format_terminal
    try:
        data = fetch_fund_with_fallback(args.keyword)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_us(args):
    from cmd_us import fetch_us_with_fallback, format_terminal
    try:
        data = fetch_us_with_fallback(args.symbol)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    if args.json:
        import json
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


def cmd_quote(args):
    from cmd_quote import run
    sys.exit(run(args.symbols, as_json=args.json))


def cmd_kline(args):
    from cmd_kline import run
    sys.exit(run(args.code, period=args.period, limit=args.limit, as_json=args.json))


def cmd_westock(args):
    from cmd_westock import run
    if getattr(args, "ws_help", False):
        sys.exit(run(["--help"], as_json=False))
    sys.exit(run(list(args.args), as_json=args.json))


def cmd_sec(args):
    from cmd_sec import run
    sys.exit(run(args.ticker, forms=args.forms, limit=args.filings, as_json=args.json))


def cmd_screen(args):
    from cmd_screen import run
    sys.exit(run(args.condition, as_json=args.json))


def cmd_datasources(args):
    from cmd_datasources import run
    sys.exit(run(as_json=args.json))


def cmd_wind(args):
    from cmd_wind import run
    sys.exit(run(args.server_type, args.tool_name, args.input, as_json=args.json))


def cmd_yingmi(args):
    from cmd_yingmi import run
    sys.exit(run(args.tool_name, args.input, as_json=args.json))


def cmd_ttskill(args):
    from cmd_ttskill import run
    sys.exit(run(args.skill_id, args.input, as_json=args.json))


def cmd_capabilities(args):
    from cmd_capabilities import run
    sys.exit(run(args.source, as_json=args.json))


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
    _relax_output_encoding()
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

    # quote（免鉴权批量实时行情：一次请求、跨市场、130ms 量级）
    p_quote = subparsers.add_parser("quote", help="免鉴权多标的实时行情（一次请求，跨市场）")
    p_quote.add_argument("symbols", help="一个或多个标的，逗号分隔：600519,00700,AAPL 或 贵州茅台")
    p_quote.add_argument("--json", action="store_true")

    # kline（K线：原生快路径 + CLI 兜底）
    p_kl = subparsers.add_parser("kline", help="K线（原生快路径，分钟级自动转 westock CLI）")
    p_kl.add_argument("code", help="标的代码或名称")
    p_kl.add_argument("--period", default="day",
                      help="day/week/month/year 或 m1/m5/m15/m30/m60/m120（默认 day）")
    p_kl.add_argument("--limit", type=int, default=60, help="根数（默认 60）")
    p_kl.add_argument("--json", action="store_true")

    # westock（腾讯微证券 CLI 长尾能力透传：筹码/龙虎榜/资金流/一致预期/板块…）
    p_ws = subparsers.add_parser("westock", add_help=False,
                                 help="透传腾讯微证券 CLI（筹码/龙虎榜/资金流/一致预期/ESG/产业链/板块估值…）")
    # add_help=False：不加的话 `invest-cli westock --help` 会被本层 argparse 截获，
    # 只打出 5 行自己的 usage，而用户要的是 westock 那 19 组 / 85 行命令树。
    # 让 `--help` 透传给真实 CLI（`invest-cli westock -h` 的语义因此与直接敲
    # `westock --help` 一致），本层的参数说明由 `--json` 与文档承担。
    p_ws.add_argument("args", nargs=argparse.REMAINDER,
                      help="westock 子命令与参数，如 chip sh600519 / lhb / screen strategy --list")
    # 自己接住 --help 并转发给真实 CLI：add_help=False 只是关掉本层帮助，
    # 不定义这个旗标的话 argparse 会报 "unrecognized arguments: --help"，
    # 用户就再也看不到 westock 那 19 组 / 85 行命令树了。
    p_ws.add_argument("-h", "--help", action="store_true", dest="ws_help",
                      help="透传 westock CLI 的帮助（真实命令树）")
    p_ws.add_argument("--json", action="store_true")

    # sec（SEC EDGAR 财报原文，免费官方源）
    p_sec = subparsers.add_parser("sec", help="SEC EDGAR 美股财报原文（10-K XBRL + 最近申报）")
    p_sec.add_argument("ticker", help="美股代码，如 AAPL / MSFT / BRK.B")
    p_sec.add_argument("--forms", default="10-K,10-Q,8-K", help="申报类型过滤（逗号分隔，默认 10-K,10-Q,8-K）")
    p_sec.add_argument("--filings", type=int, default=5, help="返回最近申报条数（默认 5）")
    p_sec.add_argument("--json", action="store_true")

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

    # ttskill（天天基金官方透传，37 包可达）
    p_tt = subparsers.add_parser("ttskill", help="透传天天基金官方业务包（如 MANAGER_INFO/NAV_INFO/STOCK_PRICE_QUERY）")
    p_tt.add_argument("skill_id", help="业务包 ID，如 TTFUND_MANAGER_INFO")
    p_tt.add_argument("--input", default="{}", help="参数 JSON")
    p_tt.add_argument("--json", action="store_true")

    # capabilities（能力发现层）
    p_cap = subparsers.add_parser("capabilities", help="列出外部数据源能力清单与收敛状态（yingmi/ttskill/空=总览）")
    p_cap.add_argument("source", nargs="?", default="", help="yingmi / ttskill / 空=总览")
    p_cap.add_argument("--json", action="store_true")

    # intent（意图层，收敛接口面）
    p_int = subparsers.add_parser("intent", help="按意图取数（deep/screen/portfolio/plan/macro/present）")
    p_int.add_argument("scene", help="语义场景：deep/screen/portfolio/plan/macro/present")
    p_int.add_argument("value", nargs=argparse.REMAINDER, help="场景参数（deep 为 <type> <标的>）")
    p_int.add_argument("--json", action="store_true")

    # info（财经检索，走 argo）
    p_info = subparsers.add_parser("info", help="财经检索/资讯/舆情（走 argo，省配额）")
    p_info.add_argument("query", help="检索词")
    p_info.add_argument("--engine", default="eastmoney", help="argo 引擎名（如 eastmoney/zhihu/cninfo/anysearch；清单见 argo search.py --list-engines）")
    p_info.add_argument("--json", action="store_true")

    # watchlist（本地自选股）
    p_wl = subparsers.add_parser("watchlist", help="本地自选股（add/remove/list）")
    # action 默认 list：真实调用里 `watchlist`（不带 action）比 `watchlist list` 更多，
    # 而旧定义要求它必填 —— 最常见的写法直接吃 argparse 的 rc=2 + usage。
    # 「看自选股」是这条命令的自然默认意图，与 `docker ps`、`git branch` 同类。
    p_wl.add_argument("action", nargs="?", default="list", help="add/remove/list（默认 list）")
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
        "quote": cmd_quote,
        "sec": cmd_sec,
        "westock": cmd_westock,
        "kline": cmd_kline,
        "screen": cmd_screen,
        "datasources": cmd_datasources,
        "wind": cmd_wind,
        "yingmi": cmd_yingmi,
        "ttskill": cmd_ttskill,
        "capabilities": cmd_capabilities,
        "intent": cmd_intent,
        "info": cmd_info,
        "watchlist": cmd_watchlist,
    }

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
