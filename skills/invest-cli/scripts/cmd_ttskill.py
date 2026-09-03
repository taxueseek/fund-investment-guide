"""ttskill 子命令：透传天天基金官方业务包。

用法:
    invest-cli ttskill <skill_id> --input '<json>' [--json]

背景（2026-09-03）：invest-cli 曾长期缺本命令，37 个官方业务包除基金三合一
（SEARCH/BASE_INFOS/HOLDING_INFO，内嵌 fund 快照链）与 GOLD_INFO（intent deep
commodity）外全部"声明不可达"，Agent 遇到未封装场景只能现场翻官方包学调用。
本命令补齐"面"的可达性；某包用得多再收敛成高层入口（登记 docs/capability-gap.md）。

参数以官方业务包 schema 为准（examples/*.example.json 是权威示例）。常用：
    NAV_INFO        {"fund_id": "001938", "range": "n"}      历史净值
    MANAGER_INFO    {"manager_name": "谢治宇"}                经理画像/在管列表
    STOCK_PRICE_QUERY {"query": "东方财富"}                   实时股价
    MACRO_DATA      {"region": "cn", "categories": "gdp,cpi"} 中美宏观
    VALUATION_MAP   {"group": "全部"}                         指数/行业估值分位
    INDEX_FUND_SELECTION {"top_n": 10, "period_codes": ["03"], "index_codes": ["000300"]}
    CONDITION_SELECT 条件选基（参数多，先看 capabilities ttskill 或官方包示例）
查看全部 37 包：invest-cli capabilities ttskill
"""
from __future__ import annotations

import json
import sys

from sources import ttskill as ttskill_src


def run(skill_id: str, params_json: str, as_json: bool = False) -> int:
    ok, detail = ttskill_src.detect()
    if not ok:
        print(f"ttskill 不可用: {detail}", file=sys.stderr)
        print("提示: 先 ttskill login --env prod 扫码登录并 ttskill install <skill_id>。", file=sys.stderr)
        return 1
    # 参数：--input 显式 JSON 优先；空则原样传 {} 让服务端走默认
    try:
        body = json.loads(params_json) if params_json and params_json.strip() else {}
    except json.JSONDecodeError as e:
        print(f"--input 不是合法 JSON: {e}", file=sys.stderr)
        return 1
    res = ttskill_src.invoke_scene(skill_id, body)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if res.get("ok"):
        print(json.dumps(res.get("data"), ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"ttskill {skill_id} 调用失败: {res.get('error')}", file=sys.stderr)
    return 1
