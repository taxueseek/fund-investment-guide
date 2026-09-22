"""westock 子命令：透传腾讯微证券 CLI 的长尾能力。

用法:
    invest-cli westock chip sh600519                     # 筹码分布
    invest-cli westock lhb                               # 全市场龙虎榜
    invest-cli westock fund flow sh600519                # 个股资金流向
    invest-cli westock consensus sh600519                # 一致预期
    invest-cli westock sector valuation                  # 板块估值
    invest-cli westock screen strategy --list            # 查策略选股的合法取值（英文 slug）
    invest-cli westock screen strategy --type high_dividend --limit 10
    invest-cli westock --help                            # 40+ 子命令的完整命令树

与其它命令的分工：`stock/fund/us/quote` 回答「这只标的多少钱、什么质地」；
本命令回答「市场结构类问题」—— 筹码、资金流、龙虎榜、板块估值、一致预期、
ESG、机构评级、产业链、可转债条款、停复牌。这些 invest-cli 的既有源都没有，
所以它是**扩展能力的唯一出口**，而不是快照链的一员。

代码位置由适配器归一化（`600519` → `sh600519`），中文名也能直接用：
    invest-cli westock chip 贵州茅台

两处口径以**实测**为准（这两条都踩过）：取值一律走旗标 `--type`（位置参数会被
拒），而中文取值不是合法取值域（服务端要英文 slug，如 high_dividend / cn_gdp）。
"""
from __future__ import annotations

import json
import sys

from sources import westock


def run(args: list[str], as_json: bool = False) -> int:
    res = westock.call(args)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif res.get("ok"):
        # 透传原始输出：CLI 出的是人读的 markdown 表格，重新排版只会引入新的失真
        print(res["data"]["output"])
        if res["data"].get("argv_normalized"):
            # 归一化动作要留痕：让用户知道我们改过参数，而不是以为它原本就长这样
            print(f"\n  （已归一化代码：{' '.join(args)} → {' '.join(res['data']['command'].split()[1:])}）")
    else:
        print(f"错误: {res.get('error')}", file=sys.stderr)
    return 0 if res.get("ok") else 1
