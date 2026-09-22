"""kline 子命令：K 线（原生快路径 + CLI 兜底）。

用法:
    invest-cli kline 600519                        # 日线，默认 60 根
    invest-cli kline 600519 --period week --limit 20
    invest-cli kline 600519 --period month --json
    invest-cli kline 600519 --period m5            # 分钟级自动转 westock CLI

为什么单独一条命令（而不是全推给 `westock kline`）
--------------------------------------------------
同一个问题有两条通道，成本差 3.6 倍：原生内核直连腾讯 fqkline 接口（实测 ~130ms），
westock CLI 是 Go 二进制（实测 ~472ms，含进程 fork）。日/周/月/年是绝大多数场景，
原生先答；原生答不了（分钟级、或接口故障）再转 CLI，能力不缩水。

复权口径：原生通道固定**前复权**（qfq），并在返回里显式标注 ——
前复权适合算区间收益，**不等于**当日真实成交价（这是被移植实现的一个真实误用：
它把历史某日的「现价」当成真实成交价，而那是前复权价）。要看真实历史价请用
`invest-cli westock kline <代码> --fq bfq`。
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from sources import tencent, westock
from sources.tencent import _PERIOD_ALIAS

# westock CLI 的分钟周期（原生命中内核不支持，必须转 CLI；且 CLI 要求 --start/--end）
_MINUTE = {"m1", "m5", "m15", "m30", "m60", "m120"}
# 各分钟周期允许的日期跨度上限：**实测得来**（CLI 会直接拒绝超限请求并给出具体天数）：
#   m1  "查询日期跨度不能超过 5 天"
#   m5  "查询日期跨度不能超过 10 天"
#   m15/m30 用 20 天可通过；m60/m120 在密集调用下返回「请求过于频繁」，按 20 天给。
_MINUTE_SPAN = {"m1": 5, "m5": 10}
_PERIOD_CN = {"day": "日", "week": "周", "month": "月", "year": "年"}


def _terminal(data: dict) -> str:
    rows = data.get("rows") or []
    name = data.get("name") or data.get("symbol", "")
    period = _PERIOD_CN.get(str(data.get("period")), data.get("period"))
    lines = ["", "=" * 72,
             f"  {name} — {period}K（{len(rows)} 根，前复权）",
             "=" * 72, "",
             f"  {'日期':<12}{'开':>10}{'高':>10}{'低':>10}{'收':>10}{'量':>14}",
             "  " + "-" * 66]
    for r in rows:
        lines.append(f"  {r['date']:<12}{r['open']:>10}{r['high']:>10}"
                     f"{r['low']:>10}{r['close']:>10}{r['volume']:>14}")
    lines.append("  " + "-" * 66)
    lines.append("  复权口径: 前复权（qfq）—— 适合算区间收益，不等于当日真实成交价")
    return "\n".join(lines)


# 原生内核认识的周期（中英别名都算）：命中走快路径，其余**直接交 CLI**。
# 这样 CLI 自己的取值域说明就是权威（实测它支持 season / m1…m120），
# 不会出现「用我们的模板去解释别人的取值域」这种必然不一致的提示。
_NATIVE = set(_PERIOD_ALIAS) | set(_PERIOD_ALIAS.values())


def run(code: str, period: str = "day", limit: int = 60, as_json: bool = False) -> int:
    want = str(period).lower()
    if want not in _NATIVE:
        # 例如 season / m1…m120 / 拼错的周期：原生内核没有这条通道，
        # 但 CLI 有（或会给出它自己的合法取值清单）—— 交给它，我们不猜。
        return _via_cli(code, want, limit, as_json,
                        note=f"周期 {period!r} 不在原生命中内核的取值域内，已交 westock CLI")
    res = tencent.kline(code, period=want, limit=limit)
    if res.get("ok"):
        if as_json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print(_terminal(res["data"]))
        return 0
    # 原生失败：如实说明原因后再转 CLI（能力不缩水，但用户看得见降级）
    native_err = res.get("error")
    return _via_cli(code, want, limit, as_json, note=f"原生通道不可用（{native_err}），已转 westock CLI")


def _via_cli(code: str, period: str, limit: int, as_json: bool,
             note: str = "") -> int:
    args = ["kline", code, "--period", period, "--limit", str(limit)]
    if period in _MINUTE:
        # CLI 对分钟周期强制要求日期范围（近 1 个月内），默认给最近 20 个自然日
        end = date.today()
        span = _MINUTE_SPAN.get(period, 20)
        args += ["--start", str(end - timedelta(days=span)), "--end", str(end)]
    res = westock.call(args)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    if res.get("ok"):
        if note:
            print(f"  注: {note}\n", file=sys.stderr)
        print(res["data"]["output"])
        return 0
    print(f"错误: {res.get('error')}", file=sys.stderr)
    return 1
