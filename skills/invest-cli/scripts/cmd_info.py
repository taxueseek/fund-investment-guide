"""info 子命令：财经检索 / 资讯 / 舆情（走 argo，低成本、非配额替代）。

用法:
    invest-cli info <查询词> [--engine eastmoney|zhihu|cninfo] [--json]

用途：
- invest 的资讯 / 舆情 / 宏观背景取数（替代盈米资讯类工具，节省配额）
- 结构化源配额不足时的财经信息兜底（结果需核验）
"""
from __future__ import annotations

import json
import sys

from sources import argo as argo_src


def run(query: str, engine: str = "eastmoney", as_json: bool = False) -> int:
    if not query.strip():
        print("用法: invest-cli info <查询词> [--engine ...]", file=sys.stderr)
        return 1
    ok, detail = argo_src.detect()
    if not ok:
        print(f"argo 不可用: {detail}", file=sys.stderr)
        return 1
    res = argo_src.search(query, engine=engine)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res.get("ok"):
            d = res.get("data") or {}
            print(json.dumps(d, ensure_ascii=False, indent=2))
        else:
            print(f"info 失败: {res.get('error')}", file=sys.stderr)
    return 0 if res.get("ok") else 1
