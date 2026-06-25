#!/usr/bin/env python3
"""
A股/港股分析 - 东方财富数据源
输出：实时行情 + 估值指标 + 财务数据（对标 invest-stock 三关框架）
"""

import os
import sys
import json
import requests
from datetime import datetime

EASTMONEY_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"


def get_api_key():
    key = os.getenv("EASTMONEY_APIKEY")
    if not key:
        print("错误: 未设置 EASTMONEY_APIKEY 环境变量", file=sys.stderr)
        sys.exit(1)
    return key


def query_eastmoney(query: str) -> dict:
    """调用东方财富 API，返回原始响应"""
    resp = requests.post(
        EASTMONEY_URL,
        headers={"apikey": get_api_key(), "Content-Type": "application/json"},
        json={"toolQuery": query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_tables(raw: dict) -> list[dict]:
    """
    解析东财 API 返回的表格数据。

    东财返回结构：
    raw.data.data.searchDataResultDTO.dataTableDTOList[].{
      entityName: "贵州茅台(600519.SH)",
      nameMap: { "326809": "总市值", "328664": "市净率PB", ... },
      table: { "326809": ["1.616万亿", "1.642万亿", ...], ... }
    }

    返回：[{ "entityName": ..., "总市值": "1.616万亿", "市净率PB": "5.964倍", ... }, ...]
    每个 dict 的值为最新（第一个）值。
    """
    try:
        dtos = raw["data"]["data"]["searchDataResultDTO"]["dataTableDTOList"]
    except (KeyError, TypeError):
        return []

    results = []
    for item in dtos:
        name_map = item.get("nameMap", {})
        table = item.get("table", {})
        row = {"entityName": item.get("entityName", "")}
        for col_id, col_name in name_map.items():
            if col_id in table:
                vals = table[col_id]
                if isinstance(vals, list) and len(vals) > 0:
                    row[col_name] = vals[0]  # 最新值
        if len(row) > 1:  # 至少有 entityName + 一个数据列
            results.append(row)
    return results


def resolve_code(keyword: str) -> str:
    """名称 → 代码映射"""
    known = {
        "茅台": "600519", "贵州茅台": "600519",
        "五粮液": "000858", "宁德时代": "300750",
        "中国平安": "601318", "招商银行": "600036",
        "腾讯": "00700", "阿里巴巴": "09988",
        "美团": "03690", "京东": "09618",
        "比亚迪": "002594", "工商银行": "601398",
    }
    if keyword.isdigit() and len(keyword) in (5, 6):
        return keyword
    return known.get(keyword, keyword)


def fetch_stock_data(code: str) -> dict:
    """获取股票完整数据"""

    # 1. 行情 + 估值
    r1 = query_eastmoney(f"{code}股票最新行情 市盈率PE 市净率PB 总市值 收盘价 开盘价")
    t1 = parse_tables(r1)

    # 2. 财务指标（ROE/毛利率/净利率/负债率）
    r2 = query_eastmoney(f"{code}股票财务指标 净资产收益率ROE 销售毛利率 销售净利率 资产负债率 每股收益EPS")
    t2 = parse_tables(r2)

    # 3. 年报业绩
    r3 = query_eastmoney(f"{code}股票年报 营业收入 净利润 营收增速 净利润增速 经营活动产生的现金流量净额")
    t3 = parse_tables(r3)

    # 合并：取每个结果的第一行（最新数据）
    quote = t1[0] if t1 else {}
    financial = t2[0] if t2 else {}
    annual = t3[0] if t3 else {}

    # 合并所有字段到一个 flat dict
    merged = {}
    for d in [quote, financial, annual]:
        for k, v in d.items():
            if k != "entityName" and v:
                merged[k] = v

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

    # 行情
    quote_keys = [
        ("收盘价", "收盘价"), ("开盘价", "开盘价"),
        ("市盈率PE(TTM)", "PE(TTM)"), ("市净率PB", "PB"),
        ("总市值", "总市值"),
    ]
    lines.append(f"\n  {'指标':<14} {'数值':>16}")
    lines.append(f"  {'-' * 32}")
    for api_key, label in quote_keys:
        val = d.get(api_key, "-")
        lines.append(f"  {label:<14} {str(val):>16}")

    # 财务
    fin_keys = [
        ("净资产收益率ROE", "ROE"), ("销售毛利率", "毛利率"),
        ("销售净利率", "净利率"), ("资产负债率", "负债率"),
        ("每股收益EPS", "EPS"),
    ]
    has_fin = any(d.get(k) for k, _ in fin_keys)
    if has_fin:
        lines.append(f"\n  {'财务指标':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in fin_keys:
            val = d.get(api_key, "-")
            lines.append(f"  {label:<14} {str(val):>16}")

    # 年报
    ann_keys = [
        ("营业收入", "营业收入"), ("净利润", "净利润"),
        ("经营活动产生的现金流量净额", "经营现金流"),
    ]
    has_ann = any(d.get(k) for k, _ in ann_keys)
    if has_ann:
        lines.append(f"\n  {'年报数据':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in ann_keys:
            val = d.get(api_key, "-")
            lines.append(f"  {label:<14} {str(val):>16}")

    lines.append(f"\n  数据时间: {data['timestamp']}")
    lines.append(f"  数据来源: 东方财富")
    return "\n".join(lines)


def main():
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
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
