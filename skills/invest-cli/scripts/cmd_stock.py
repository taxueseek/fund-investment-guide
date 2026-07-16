#!/usr/bin/env python3
"""
A股/港股分析 - 东方财富数据源
输出：实时行情 + 估值指标 + 财务数据（对标 invest-stock 三关框架）
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from _common import (
    ensure_script_dir_on_path,
    eastmoney_ensure_ok,
    json_out,
    parse_eastmoney_tables,
)

ensure_script_dir_on_path()

import requests

EASTMONEY_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"

# Stable keys expected by investment-agent / format_terminal.
# Eastmoney often returns longer labels; map suffix variants → canonical.
_FIELD_ALIASES = {
    "净资产收益率ROE(加权)": "净资产收益率ROE",
    "净资产收益率ROE(摊薄)": "净资产收益率ROE",
    "每股收益EPS(基本)": "每股收益EPS",
    "每股收益EPS(稀释)": "每股收益EPS",
    "净利润/营业总收入(销售净利率)": "销售净利率",
    "市盈率PE": "市盈率PE(TTM)",
}


def get_api_key() -> str:
    key = os.getenv("EASTMONEY_APIKEY")
    if not key:
        print("错误: 未启用东财能力 — 请设置环境变量 EASTMONEY_APIKEY 后重试。\n配置说明: 见仓库 docs/data-sources.md", file=sys.stderr)
        sys.exit(1)
    return key


def query_eastmoney(query: str) -> dict:
    resp = requests.post(
        EASTMONEY_URL,
        headers={"apikey": get_api_key(), "Content-Type": "application/json"},
        json={"toolQuery": query},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()
    eastmoney_ensure_ok(raw, context=" (stock query)")
    return raw


def normalize_fields(merged: dict) -> dict:
    """Expose canonical keys without dropping original Eastmoney labels."""
    out = dict(merged)
    for src, dst in _FIELD_ALIASES.items():
        if src in out and dst not in out:
            out[dst] = out[src]
    return out


def resolve_code(keyword: str) -> str:
    known = {
        "茅台": "600519",
        "贵州茅台": "600519",
        "五粮液": "000858",
        "宁德时代": "300750",
        "中国平安": "601318",
        "招商银行": "600036",
        "腾讯": "00700",
        "阿里巴巴": "09988",
        "美团": "03690",
        "京东": "09618",
        "比亚迪": "002594",
        "工商银行": "601398",
    }
    if keyword.isdigit() and len(keyword) in (5, 6):
        return keyword
    return known.get(keyword, keyword)


def fetch_stock_data(code: str) -> dict:
    r1 = query_eastmoney(f"{code}股票最新行情 市盈率PE 市净率PB 总市值 收盘价 开盘价")
    t1 = parse_eastmoney_tables(r1)

    r2 = query_eastmoney(
        f"{code}股票财务指标 净资产收益率ROE 销售毛利率 销售净利率 资产负债率 每股收益EPS"
    )
    t2 = parse_eastmoney_tables(r2)

    r3 = query_eastmoney(
        f"{code}股票年报 营业收入 净利润 营收增速 净利润增速 经营活动产生的现金流量净额"
    )
    t3 = parse_eastmoney_tables(r3)

    quote = t1[0] if t1 else {}
    financial = t2[0] if t2 else {}
    annual = t3[0] if t3 else {}

    merged: dict = {}
    for d in (quote, financial, annual):
        for k, v in d.items():
            if k != "entityName" and v:
                merged[k] = v

    merged = normalize_fields(merged)

    return {
        "code": code,
        "name": quote.get("entityName", code),
        "timestamp": datetime.now().isoformat(),
        "data": merged,
        "raw_tables": {"quote": t1, "financial": t2, "annual": t3},
    }


def format_terminal(data: dict) -> str:
    lines = []
    d = data.get("data", {})
    name = data.get("name", data["code"])

    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {name} — 行情快照")
    lines.append(f"{'=' * 60}")

    quote_keys = [
        ("收盘价", "收盘价"),
        ("开盘价", "开盘价"),
        ("市盈率PE(TTM)", "PE(TTM)"),
        ("市净率PB", "PB"),
        ("总市值", "总市值"),
    ]
    lines.append(f"\n  {'指标':<14} {'数值':>16}")
    lines.append(f"  {'-' * 32}")
    for api_key, label in quote_keys:
        val = d.get(api_key, "-")
        lines.append(f"  {label:<14} {str(val):>16}")

    fin_keys = [
        ("净资产收益率ROE", "ROE"),
        ("销售毛利率", "毛利率"),
        ("销售净利率", "净利率"),
        ("资产负债率", "负债率"),
        ("每股收益EPS", "EPS"),
    ]
    if any(d.get(k) for k, _ in fin_keys):
        lines.append(f"\n  {'财务指标':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in fin_keys:
            val = d.get(api_key, "-")
            lines.append(f"  {label:<14} {str(val):>16}")

    ann_keys = [
        ("营业收入", "营业收入"),
        ("净利润", "净利润"),
        ("经营活动产生的现金流量净额", "经营现金流"),
    ]
    if any(d.get(k) for k, _ in ann_keys):
        lines.append(f"\n  {'年报数据':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in ann_keys:
            val = d.get(api_key, "-")
            lines.append(f"  {label:<14} {str(val):>16}")

    lines.append(f"\n  数据时间: {data['timestamp']}")
    lines.append("  数据来源: 东方财富")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="A股/港股分析")
    parser.add_argument("keyword", help="股票代码或名称，如 600519 或 茅台")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    code = resolve_code(args.keyword)
    try:
        data = fetch_stock_data(code)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json_out(data))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
