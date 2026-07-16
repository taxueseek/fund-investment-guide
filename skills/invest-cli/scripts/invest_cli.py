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

示例:
    invest-cli stock 600519
    invest-cli stock 茅台 --json
    invest-cli fund 005827
    invest-cli us AAPL
    invest-cli screen "市盈率低于10的银行股"

路径:
    从任意 cwd 调用本脚本均可；依赖通过 scripts/ 注入 sys.path。
    环境变量 EASTMONEY_APIKEY 用于 stock/fund/screen。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _reexec_skill_venv_if_needed() -> None:
    """Prefer skill-local .venv so `us` works without system yfinance (PEP 668).

    Do not compare resolved binaries: venv/bin/python often symlinks to the
    same Homebrew python, while site-packages differ.
    """
    root = Path(__file__).resolve().parent.parent
    venv_root = root / ".venv"
    vpy = venv_root / "bin" / "python"
    if not vpy.is_file():
        return
    if Path(sys.prefix).resolve() == venv_root.resolve():
        return
    try:
        import yfinance  # noqa: F401
        return
    except ImportError:
        os.execv(str(vpy), [str(vpy), str(Path(__file__).resolve()), *sys.argv[1:]])


_reexec_skill_venv_if_needed()

from _common import (
    ensure_script_dir_on_path,
    json_out,
    pick_screen_columns,
    strip_paren_suffix,
)

ensure_script_dir_on_path()


def _fail(msg: str, code: int = 1) -> None:
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def cmd_stock(args) -> None:
    from cmd_stock import fetch_stock_data, format_terminal, resolve_code

    code = resolve_code(args.keyword)
    try:
        data = fetch_stock_data(code)
    except Exception as e:
        _fail(str(e))
    if args.json:
        print(json_out(data))
    else:
        print(format_terminal(data))


def cmd_fund(args) -> None:
    from cmd_fund import fetch_fund_data, format_terminal, resolve_fund_code

    code = resolve_fund_code(args.keyword)
    try:
        data = fetch_fund_data(code)
    except Exception as e:
        _fail(str(e))
    if args.json:
        print(json_out(data))
    else:
        print(format_terminal(data))


def cmd_us(args) -> None:
    from cmd_us import fetch_us_data, format_terminal

    try:
        data = fetch_us_data(args.symbol)
    except Exception as e:
        _fail(str(e))
    if args.json:
        print(json_out(data))
    else:
        print(format_terminal(data))


def parse_markdown_table(md: str) -> list[dict]:
    lines = [l.strip() for l in md.strip().split("\n") if l.strip()]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
    return rows


def cmd_screen(args) -> None:
    import requests

    api_key = os.getenv("EASTMONEY_APIKEY")
    if not api_key:
        print("错误: 未启用东财能力 — 请设置 EASTMONEY_APIKEY。见 docs/data-sources.md", file=sys.stderr)
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
    if isinstance(result, dict) and (result.get("success") is False or result.get("data") is None):
        msg = result.get("message") or result.get("code") or "unknown"
        print(f"错误: 东财选股 API 失败: {msg}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json_out(result))
        return

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

    except (KeyError, IndexError, TypeError) as e:
        print(f"解析结果失败: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="invest-cli — 投资分析 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    p_stock = subparsers.add_parser("stock", help="A股/港股分析")
    p_stock.add_argument("keyword", help="股票代码或名称")
    p_stock.add_argument("--json", action="store_true")

    p_fund = subparsers.add_parser("fund", help="基金分析")
    p_fund.add_argument("keyword", help="基金代码或名称")
    p_fund.add_argument("--json", action="store_true")

    p_us = subparsers.add_parser("us", help="美股分析")
    p_us.add_argument("symbol", help="美股代码")
    p_us.add_argument("--json", action="store_true")

    p_screen = subparsers.add_parser("screen", help="选股")
    p_screen.add_argument("condition", help="选股条件")
    p_screen.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    {
        "stock": cmd_stock,
        "fund": cmd_fund,
        "us": cmd_us,
        "screen": cmd_screen,
    }[args.command](args)


if __name__ == "__main__":
    main()
