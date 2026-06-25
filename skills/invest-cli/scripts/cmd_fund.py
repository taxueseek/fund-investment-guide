#!/usr/bin/env python3
"""
基金分析 - 东方财富数据源
输出：净值 + 业绩 + 持仓 + 经理 + 费率（对标 invest-fund 三关框架）
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
    返回：[{ "entityName": ..., "列名": "最新值", ... }, ...]
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
                    row[col_name] = vals[0]
        if len(row) > 1:
            results.append(row)
    return results


def resolve_fund_code(keyword: str) -> str:
    known = {
        "易方达蓝筹": "110011", "易方达蓝筹精选": "110011",
        "中欧医疗": "003096", "中欧医疗健康": "003096",
        "招商中证白酒": "161725",
        "富国天惠": "161005",
        "兴全趋势": "163402",
        "诺安成长": "320007",
    }
    if keyword.isdigit() and len(keyword) == 6:
        return keyword
    return known.get(keyword, keyword)


def fetch_fund_data(code: str) -> dict:
    # 1. 基础信息
    r1 = query_eastmoney(f"{code}基金基本信息 基金名称 基金类型 成立日期 基金规模 基金管理人")
    t1 = parse_tables(r1)

    # 2. 净值 + 业绩
    r2 = query_eastmoney(f"{code}基金最新净值 近1月回报 近3月回报 近6月回报 近1年回报 近3年回报 今年来回报")
    t2 = parse_tables(r2)

    # 3. 风险指标
    r3 = query_eastmoney(f"{code}基金风险指标 最大回撤 波动率 夏普比率 卡玛比率")
    t3 = parse_tables(r3)

    # 4. 费率
    r4 = query_eastmoney(f"{code}基金费率 管理费率 托管费率 申购费率")
    t4 = parse_tables(r4)

    # 5. 经理
    r5 = query_eastmoney(f"{code}基金经理 经理姓名 管理年限 管理基金数量 总管理规模")
    t5 = parse_tables(r5)

    # 6. 重仓
    r6 = query_eastmoney(f"{code}基金最新十大重仓股 重仓股名称 占净值比例")
    t6 = parse_tables(r6)

    basic = t1[0] if t1 else {}
    perf = t2[0] if t2 else {}
    risk = t3[0] if t3 else {}
    fees = t4[0] if t4 else {}
    manager = t5[0] if t5 else {}

    merged = {}
    for d in [basic, perf, risk, fees, manager]:
        for k, v in d.items():
            if k != "entityName" and v:
                merged[k] = v

    return {
        "code": code,
        "name": basic.get("基金名称", basic.get("entityName", code)),
        "timestamp": datetime.now().isoformat(),
        "data": merged,
        "holdings": t6,
        "raw_tables": {"basic": t1, "performance": t2, "risk": t3, "fees": t4, "manager": t5, "holdings": t6},
    }


def format_terminal(data: dict) -> str:
    lines = []
    d = data.get("data", {})
    h = data.get("holdings", [])
    name = data.get("name", data["code"])

    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {name}（{data['code']}）— 基金快照")
    lines.append(f"{'=' * 60}")

    # 基础
    lines.append(f"\n  {'基础信息':<14} {'数值':>16}")
    lines.append(f"  {'-' * 32}")
    for api_key, label in [("基金类型", "类型"), ("成立日期", "成立日期"), ("基金规模", "规模"), ("基金管理人", "管理人")]:
        val = d.get(api_key, "-")
        lines.append(f"  {label:<14} {str(val):>16}")

    # 业绩
    perf_keys = [
        ("单位净值", "最新净值"), ("近1月回报", "近1月"), ("近3月回报", "近3月"),
        ("近6月回报", "近6月"), ("近1年回报", "近1年"), ("近3年回报", "近3年"), ("今年来回报", "今年来"),
    ]
    has_perf = any(d.get(k) for k, _ in perf_keys)
    if has_perf:
        lines.append(f"\n  {'业绩表现':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in perf_keys:
            val = d.get(api_key)
            if val:
                lines.append(f"  {label:<14} {str(val):>16}")

    # 风险
    risk_keys = [("最大回撤", "最大回撤"), ("波动率", "波动率"), ("夏普比率", "夏普比率"), ("卡玛比率", "卡玛比率")]
    has_risk = any(d.get(k) for k, _ in risk_keys)
    if has_risk:
        lines.append(f"\n  {'风险指标':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in risk_keys:
            val = d.get(api_key)
            if val:
                lines.append(f"  {label:<14} {str(val):>16}")

    # 费率
    fee_keys = [("管理费率", "管理费"), ("托管费率", "托管费"), ("申购费率", "申购费")]
    has_fees = any(d.get(k) for k, _ in fee_keys)
    if has_fees:
        lines.append(f"\n  {'费率结构':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in fee_keys:
            val = d.get(api_key)
            if val:
                lines.append(f"  {label:<14} {str(val):>16}")

    # 经理
    mgr_keys = [("经理姓名", "经理"), ("管理年限", "管理年限"), ("总管理规模", "管理规模")]
    has_mgr = any(d.get(k) for k, _ in mgr_keys)
    if has_mgr:
        lines.append(f"\n  {'基金经理':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in mgr_keys:
            val = d.get(api_key)
            if val:
                lines.append(f"  {label:<14} {str(val):>16}")

    # 重仓
    if h:
        lines.append(f"\n  十大重仓股:")
        lines.append(f"  {'-' * 40}")
        for stock in h[:10]:
            sname = stock.get("entityName", "")
            # 尝试从 nameMap 或 table 取占比
            ratio = ""
            for k, v in stock.items():
                if k != "entityName" and v:
                    ratio = str(v)
                    break
            lines.append(f"  {sname:<20} {ratio:>10}")

    lines.append(f"\n  数据时间: {data['timestamp']}")
    lines.append(f"  数据来源: 东方财富")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="基金分析")
    parser.add_argument("keyword", help="基金代码或名称")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    code = resolve_fund_code(args.keyword)
    try:
        data = fetch_fund_data(code)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
