"""yingmi 子命令：透传盈米且慢数据源。

用法:
    invest-cli yingmi <tool_name> --input '<json>' [--json]

盈米工具契约以其 schema 为准，本命令只负责透传与还原结果/错误。
"""
from __future__ import annotations

import json
import sys

from sources import yingmi as yingmi_src


def run(tool_name: str, params_json: str, as_json: bool = False) -> int:
    ok, detail = yingmi_src.detect()
    if not ok:
        print(f"盈米不可用: {detail}", file=sys.stderr)
        print("提示: 先执行 yingmi-skill-cli init setup 完成初始化。", file=sys.stderr)
        return 1
    result = yingmi_src.call(tool_name, params_json=params_json)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if result.get("ok"):
        print(json.dumps(result.get("data"), ensure_ascii=False, indent=2))
        return 0
    print(f"盈米调用失败: {result.get('error')}", file=sys.stderr)
    return 1
