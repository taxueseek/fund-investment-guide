"""wind 子命令：透传 Wind 万得数据源。

用法:
    invest-cli wind <server_type> <tool_name> --input '<json>' [--json]

以 wind-mcp-skill 领域契约为准，本命令只负责定位并透传，不改字段名。
"""
from __future__ import annotations

import json
import sys

from sources import wind as wind_src


def run(server_type: str, tool_name: str, params_json: str, as_json: bool = False) -> int:
    ok, detail = wind_src.detect()
    if not ok:
        print(f"Wind 不可用: {detail}", file=sys.stderr)
        print("提示: 安装 wind-mcp-skill 并用 WIND_SKILL_DIR 或 INVEST_SKILL_ROOTS 指向其目录。", file=sys.stderr)
        return 1
    result = wind_src.call(server_type, tool_name, params_json=params_json)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if result.get("ok"):
        print(json.dumps(result.get("data"), ensure_ascii=False, indent=2))
        return 0
    print(f"Wind 调用失败: {result.get('error')}", file=sys.stderr)
    return 1
