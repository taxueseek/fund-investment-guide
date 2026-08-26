"""datasources 子命令：列出并探测所有已登记数据源的可用性。

用法:
    invest-cli datasources            # 表格输出
    invest-cli datasources --json     # 结构化 JSON（供 skill 层路由）
"""
from __future__ import annotations

import json
import sys

from sources import registry


def _fmt_available(v: bool) -> str:
    return "可用" if v else "不可用"


def run(detect_only: bool = False, as_json: bool = False) -> int:
    states = registry.detect_all()
    if not states:
        print("未加载到任何数据源配置（缺 data-sources.yaml）", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(states, ensure_ascii=False, indent=2))
        return 0

    # 可读表格
    print("\n  invest-cli 数据源状态")
    print("  " + "-" * 62)
    print(f"  {'数据源':<12}{'可用':<8}{'优先级':<8}{'覆盖场景'}")
    print("  " + "-" * 62)
    ranked = sorted(states.items(), key=lambda kv: kv[1].get("priority", 0), reverse=True)
    for sid, st in ranked:
        cov = ",".join(st.get("coverage", []))[:20]
        print(f"  {sid:<12}{_fmt_available(st.get('available', False)):<8}"
              f"{st.get('priority', 0):<8}{cov}")
        print(f"    └ {st.get('detail', '')}")
    print("  " + "-" * 62)
    avail = registry.available_ids()
    print(f"\n  当前可用数据源（按优先级）: {', '.join(avail) if avail else '无'}")
    return 0
