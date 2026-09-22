"""quote 子命令：免鉴权多标的实时行情（一次 HTTP，跨市场）。

用法:
    invest-cli quote 600519
    invest-cli quote 600519,000858,00700,AAPL          # 一次请求全给
    invest-cli quote 贵州茅台 --json                    # 中文名亦可
    invest-cli quote 510300,113050                     # ETF / 可转债

与 stock/fund/us 的分工（这是本命令存在的唯一理由）
--------------------------------------------------
    quote   纯行情：最新价/涨跌/高低/量额/换手/PE/PB/市值/52周。零鉴权，
            一次请求可带任意多个标的（实测 6 标的混合沪/深/港/美/ETF/可转债 132ms）。
    stock   深度快照：带净利润/ROE/EPS/资产负债率等基本面，要问同花顺/东财，
            单标的冷取数 0.5s 起。us 的富源（yfinance）冷取数 4.4s。

所以：**「现在多少钱」用 quote，「这家公司怎么样」用 stock/fund/us**。
把深度快照用在行情问题上，就是为 13 项基本面字段付了 4 倍的网络等待；
反过来把 quote 用在基本面问题上，会拿到一份没有 ROE 的快照还以为数据缺失。

为什么不做成「stock 的一个快模式」：那会让同一条命令的输出形状随行情波动，
调用方无法预期字段集。分离成两条命令，字段集是静态承诺，比参数更快慢可预期得多。
"""
from __future__ import annotations

import json
import sys

from sources import tencent


def _fmt_pct(v) -> str:
    return "-" if v is None else f"{v:+.2f}%"


def _fmt_amount(v) -> str:
    """成交额按量级换单位（元 → 万/亿）。"""
    if v is None:
        return "-"
    if v >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if v >= 1e4:
        return f"{v / 1e4:.0f}万"
    return f"{v:.0f}"


def _terminal(data: dict, source: str) -> str:
    rows = data.get("quotes") or []
    lines = ["", "=" * 78,
             f"  实时行情（{len(rows)} 个标的，一次请求）— 数据来源: {source}",
             "=" * 78, ""]
    head = f"  {'代码':<10}{'名称':<14}{'最新价':>10}{'涨跌':>10}{'涨跌幅':>9}{'成交额':>10}{'换手':>8}"
    lines.append(head)
    lines.append("  " + "-" * 74)
    for q in rows:
        name = str(q.get("name", ""))[:12]
        lines.append(
            f"  {str(q.get('symbol', '')):<10}{name:<14}"
            f"{str(q.get('price', '-')):>10}{str(q.get('change', '-')):>10}"
            f"{_fmt_pct(q.get('change_pct')):>9}{_fmt_amount(q.get('amount')):>10}"
            f"{(str(q.get('turnover_rate')) + '%') if q.get('turnover_rate') is not None else '-':>8}"
        )
    lines.append("  " + "-" * 74)
    # 未命中的标的必须出声：接口对未知代码不报错，只是不回那一行。
    # 不报出来，用户只会看到「少了几个」，无从判断是代码写错还是接口少给。
    if data.get("missing"):
        lines.append(f"\n  未返回（代码可能不存在或写法有误）: {', '.join(data['missing'])}")
    if data.get("unresolved"):
        lines.append(f"  无法解析的名称: {', '.join(data['unresolved'])}")
    # 无成交数据的标的单独说清楚：不把它们混进行情表，也不静默丢掉
    for n in data.get("no_quote") or []:
        lines.append(f"\n  无成交数据: {n['symbol']} {n.get('name') or ''} —— {n['reason']}")
    for warn in data.get("conflicts") or []:
        lines.append(f"\n  注意: {warn}")
    if data.get("cached"):
        lines.append("\n  （10 秒内缓存命中，行情时间见下）")
    times = {str(q.get("time", "")) for q in rows if q.get("time")}
    if len(times) == 1:
        lines.append(f"  行情时间: {times.pop()}")
    return "\n".join(lines)


def run(symbols: str, as_json: bool = False) -> int:
    res = tencent.quote(symbols)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif res.get("ok"):
        print(_terminal(res["data"], res.get("source", "tencent")))
    else:
        print(f"错误: {res.get('error')}", file=sys.stderr)
    return 0 if res.get("ok") else 1
