"""sec 子命令：SEC EDGAR 美股财报（免费官方源，无需 key）。

用法:
    invest-cli sec <ticker> [--forms 10-K,10-Q,8-K] [--filings 5] [--json]

数据 = 10-K 年报 XBRL 事实（form=10-K + fp=FY）+ 最近申报清单（带原文链接）。
与 Wind / yfinance 的结构化数字交叉验证时，以本命令为「原文级」依据。
"""
from __future__ import annotations

import json
import sys
import unicodedata

from sources import sec_edgar


def _disp_width(s: str) -> int:
    """终端显示宽度（CJK 双宽），用于对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _disp_width(s))


def _fmt_value(row: dict) -> str:
    value = row.get("value")
    unit = row.get("unit")
    if value is None:
        return "-"
    if unit == "USD/shares":
        return f"{float(value):,.2f} 美元/股"
    if unit == "USD":
        return f"{float(value) / 1e8:,.2f} 亿美元"
    return f"{value} {unit}"


def format_terminal(data: dict) -> str:
    lines: list[str] = []
    ticker = data.get("ticker") or ""
    name = data.get("name") or ticker
    lines.append("=" * 64)
    lines.append(f"  SEC EDGAR · {name}（{ticker}，CIK {data.get('cik')}）")
    lines.append("=" * 64)
    fy = data.get("fiscal_year")
    if fy:
        lines.append(f"  最新年报：FY{fy}（10-K，XBRL 原文口径）")
    lines.append("")
    lines.append(f"  {_pad('指标', 14)}{_pad('数值', 22)}us-gaap 标签")
    lines.append("  " + "-" * 60)
    metrics = data.get("metrics") or {}
    for key, label in sec_edgar.METRIC_LABELS.items():
        row = metrics.get(key)
        if not row:
            continue
        lines.append(f"  {_pad(label, 14)}{_pad(_fmt_value(row), 22)}{row.get('tag')}")
    filings = data.get("filings") or []
    if filings:
        lines.append("")
        lines.append("  最近申报：")
        for f in filings:
            lines.append(f"    {str(f.get('form', '')):<6} {f.get('filing_date', '')}  {f.get('url', '')}")
    if data.get("filings_error"):
        lines.append(f"  （申报清单获取失败：{data['filings_error']}）")
    lines.append("")
    lines.append(f"  来源：{data.get('source_url', '')}")
    return "\n".join(lines)


def run(ticker: str, forms: str = "", limit: int = 5, as_json: bool = False) -> int:
    form_list = [f.strip() for f in (forms or "").split(",") if f.strip()]
    res = sec_edgar.snapshot(ticker, forms=form_list, limit=limit)
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if not res.get("ok"):
        print(f"SEC 取数失败: {res.get('error')}", file=sys.stderr)
        return 1
    print(format_terminal(res["data"]))
    return 0
