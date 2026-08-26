"""ttfund 子命令：透传天天基金 ttfund 场景命令。

用法:
    invest-cli ttfund <子命令> [参数...] [--json]

ttfund 是场景化 CLI（bond/gold/macro/diagnose/pick/allocate/research 等），
本命令透传其任意子命令，并在需要取数的场景前校验登录。
"""
from __future__ import annotations

import json
import sys

from sources import ttfund as ttfund_src

# 无需登录即可执行的子命令
NO_AUTH_SCENES = {"login", "logout", "status", "--help", "-h", "plugin", "routes"}


def run(argv: list[str], as_json: bool = False) -> int:
    if "--json" in argv:
        argv = [a for a in argv if a != "--json"]
        as_json = True

    if not argv:
        print("用法: invest-cli ttfund <子命令> [参数...] [--json]", file=sys.stderr)
        return 1

    scene = argv[0]
    if scene not in NO_AUTH_SCENES:
        ok, detail = ttfund_src.login_ok()
        if not ok:
            print(f"ttfund 提示: {detail}（场景取数需登录）", file=sys.stderr)
            return 1

    result = ttfund_src.raw_call(argv)
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 1
    if result.get("ok"):
        data = result.get("data")
        if isinstance(data, str):
            print(data)
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    print(f"ttfund 调用失败: {result.get('error')}", file=sys.stderr)
    return 1
