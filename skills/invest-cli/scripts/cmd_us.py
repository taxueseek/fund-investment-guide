#!/usr/bin/env python3
"""
美股分析 — yfinance 全量快照优先，Bitget rToken 报价兜底。
输出：估值 + 财务 + 评级（yfinance）；或 rToken/USDT 报价（bitget）。

代码规范化：yfinance 也兜底 A股/港股（见 sources/yfinance.py 的 stock()），
6 位 A 股代码 → 600519.SS / 000858.SZ；5 位港股代码 → 0700.HK。
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from typing import Any

_CN_SH = re.compile(r"^60[0135]\d{3}$|^688\d{3}$|^689\d{3}$")
_CN_SZ = re.compile(r"^00[013]\d{3}$|^30[01]\d{3}$")


def normalize_ticker(symbol: str) -> str:
    """yfinance 代码规范化：CN A股/港股代码 → 带后缀 ticker；美股原样。"""
    t = (symbol or "").strip().upper()
    if re.fullmatch(r"\d{5}", t):
        return f"{int(t):04d}.HK"  # 00700 → 0700.HK
    if _CN_SH.match(t):
        return f"{t}.SS"
    if _CN_SZ.match(t):
        return f"{t}.SZ"
    return t


def normalize_dividend_yield(info: dict[str, Any], price: float | None) -> float | None:
    """把 yfinance 的股息率统一归一为**小数**（0.0032 表示 0.32%）。

    yfinance 0.2.x 的 `dividendYield` 是小数，1.x 起改为百分数，单位跨版本变过；
    直接用会让展示层重复放大 100 倍（AAPL 曾显示 33.00%，真实约 0.32%）。
    因此优先用「年化股息 ÷ 现价」重算，仅在原始数据缺失时才回退到 dividendYield。
    """
    div_rate = info.get("trailingAnnualDividendRate")
    if div_rate and price:
        return div_rate / price
    raw = info.get("dividendYield")
    if raw is None:
        return None
    # 1.0 边界：1.x 版本的百分数形式最小合法值为 1.00%（=1.0）；
    # 0.2.x 小数为 0.5 时表示 0.5%，但 yfinance 0.2.x 的 dividendYield
    # 实为年股息/价格的小数，>1 不可能（>100% 股息率不存在），故 >=1 安全。
    return raw / 100 if raw >= 1 else raw


def fetch_us_data(symbol: str) -> dict:
    """使用 yfinance 获取全量快照（美股为主，也兜底 A股/港股。失败抛异常；未安装也抛 ImportError）。"""
    import yfinance as yf

    ticker = yf.Ticker(normalize_ticker(symbol))

    info = ticker.info

    hist = ticker.history(period="1y")

    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    change_pct = info.get("regularMarketChangePercent")
    pe = info.get("trailingPE") or info.get("forwardPE")
    pb = info.get("priceToBook")
    market_cap = info.get("marketCap")
    dividend_yield = normalize_dividend_yield(info, price)
    beta = info.get("beta")

    roe = info.get("returnOnEquity")
    debt_to_equity = info.get("debtToEquity")
    fcf = info.get("freeCashflow")
    revenue = info.get("totalRevenue")
    net_income = info.get("netIncomeToCommon")
    high_52w = info.get("fiftyTwoWeekHigh")
    low_52w = info.get("fiftyTwoWeekLow")
    recommendation = info.get("recommendationKey")
    target_price = info.get("targetMeanPrice")

    max_drawdown = None
    if hist is not None and not hist.empty:
        prices = hist["Close"].dropna()
        if len(prices) > 0:
            peak = prices.expanding(min_periods=1).max()
            drawdown = (prices - peak) / peak
            max_drawdown = drawdown.min()

    return {
        "source": "yfinance",
        "symbol": symbol.upper(),
        "name": info.get("shortName") or info.get("longName", ""),
        "currency": info.get("currency", "USD"),
        "timestamp": datetime.now().isoformat(),
        "quote": {
            "price": price,
            "change_pct": change_pct,
            "market_cap": market_cap,
            "pe_trailing": info.get("trailingPE"),
            "pe_forward": info.get("forwardPE"),
            "pb": pb,
            "dividend_yield": dividend_yield,
            "beta": beta,
            "high_52w": high_52w,
            "low_52w": low_52w,
        },
        "financial": {
            "revenue": revenue,
            "net_income": net_income,
            "roe": roe,
            "debt_to_equity": debt_to_equity,
            "free_cash_flow": fcf,
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
        },
        "analyst": {
            "recommendation": recommendation,
            "target_price": target_price,
            "analyst_count": info.get("numberOfAnalystOpinions"),
        },
        "risk": {
            "max_drawdown_1y": max_drawdown,
            "beta": beta,
        },
        "business": {
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "employees": info.get("fullTimeEmployees"),
        },
    }


def bitget_quote_to_snapshot(quote: dict[str, Any]) -> dict[str, Any]:
    """Bitget 报价 payload → CLI 输出用的 quote-centric 快照。"""
    change = quote.get("change_24h")
    return {
        "source": "bitget",
        "symbol": quote.get("symbol", ""),
        "name": quote.get("rtoken") or quote.get("symbol", ""),
        "currency": quote.get("currency", "USDT"),
        "timestamp": quote.get("ts") or datetime.now().isoformat(),
        "quote": {
            "price": quote.get("price"),
            "last": quote.get("last"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "change_pct": change,
            "high_24h": quote.get("high_24h"),
            "low_24h": quote.get("low_24h"),
            "volume_usdt_24h": quote.get("volume_usdt_24h"),
            "price_basis": quote.get("price_basis"),
        },
        "quote_type": quote.get("quote_type", "rtoken"),
        "disclaimer": quote.get("disclaimer", "代币价/USDT/非交易所官方价"),
        "rtoken": quote.get("rtoken"),
        "pair": quote.get("pair"),
    }


def fetch_us_with_fallback(symbol: str) -> dict[str, Any]:
    """美股：route.pick（yfinance → bitget），整单回退，不混字段。"""
    from sources.route import fetch

    res = fetch("us", symbol)
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        raise RuntimeError(res.get("error") or "美股取数失败")
    data = res["data"]
    if res.get("source") == "bitget" or data.get("quote_type") == "rtoken":
        snap = bitget_quote_to_snapshot(data)
        if res.get("fallback_error"):
            snap["fallback_reason"] = res.get("fallback_error")
        return snap
    return data


def format_terminal(data: dict) -> str:
    source = data.get("source", "yfinance")
    if source == "bitget":
        return _format_bitget(data)
    return _format_yfinance(data)


def _format_yfinance(data: dict) -> str:
    lines = []
    q = data.get("quote", {})
    f = data.get("financial", {})
    a = data.get("analyst", {})
    r = data.get("risk", {})
    b = data.get("business", {})

    name = data.get("name", data["symbol"])
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {name}（{data['symbol']}）— 美股快照")
    lines.append(f"  货币: {data.get('currency', 'USD')}")
    lines.append(f"{'=' * 60}")

    lines.append(f"\n  {'指标':<16} {'数值':>16}")
    lines.append(f"  {'-' * 34}")
    for key, label in [
        ("price", "当前价格"), ("change_pct", "涨跌幅"),
        ("pe_trailing", "市盈率(TTM)"),
        ("pe_forward", "市盈率(前瞻)"), ("pb", "市净率"),
        ("dividend_yield", "股息率"), ("beta", "Beta"),
        ("market_cap", "总市值"), ("high_52w", "52周最高"),
        ("low_52w", "52周最低"),
    ]:
        val = q.get(key)
        if val is not None:
            if key == "dividend_yield":
                # yfinance 0.2.x 返回小数（0.0235），1.x 起改为百分数（2.35）。
                # 按量级自适应，避免跨版本重复乘 100（曾导致 AAPL 显示 33.00%）。
                val = f"{val:.2f}%" if val > 1 else f"{val * 100:.2f}%"
            elif key == "change_pct":
                val = f"{val:+.2f}%"
            elif key == "market_cap":
                val = f"{val / 1e8:.0f}亿" if val >= 1e8 else f"{val / 1e6:.0f}M"
            lines.append(f"  {label:<16} {str(val):>16}")
        else:
            lines.append(f"  {label:<16} {'-':>16}")

    if f:
        lines.append(f"\n  {'财务指标':<16} {'数值':>16}")
        lines.append(f"  {'-' * 34}")
        for key, label in [
            ("revenue", "营收"), ("net_income", "净利润"),
            ("roe", "ROE"), ("debt_to_equity", "负债/权益"),
            ("free_cash_flow", "自由现金流"),
        ]:
            val = f.get(key)
            if val is not None:
                if key in ("revenue", "net_income", "free_cash_flow") and abs(val) >= 1e8:
                    val = f"{val / 1e8:.0f}亿"
                elif key == "roe":
                    val = f"{val * 100:.1f}%"
                lines.append(f"  {label:<16} {str(val):>16}")
            else:
                lines.append(f"  {label:<16} {'-':>16}")

        for key, label in [
            ("gross_margin", "毛利率"), ("operating_margin", "经营利润率"),
            ("profit_margin", "净利率"),
        ]:
            val = f.get(key)
            if val is not None:
                lines.append(f"  {label:<16} {val * 100:>15.1f}%")

    lines.append(f"\n  {'风险指标':<16} {'数值':>16}")
    lines.append(f"  {'-' * 34}")
    mdd = r.get("max_drawdown_1y")
    if mdd is not None:
        lines.append(f"  {'1年最大回撤':<16} {mdd * 100:>15.1f}%")
    if r.get("beta"):
        lines.append(f"  {'Beta':<16} {r['beta']:>16}")

    if a.get("recommendation"):
        lines.append(f"\n  分析师评级: {a['recommendation']}")
        if a.get("target_price"):
            lines.append(f"  目标价: ${a['target_price']:.2f}")
        if a.get("analyst_count"):
            lines.append(f"  分析师数量: {a['analyst_count']}")

    if b.get("sector"):
        lines.append(f"\n  行业: {b.get('sector', '')} / {b.get('industry', '')}")
        lines.append(f"  国家: {b.get('country', '')}")

    lines.append(f"\n  数据时间: {data['timestamp']}")
    lines.append(f"  数据来源: {data.get('source', 'yfinance')}")
    return "\n".join(lines)


def _format_bitget(data: dict) -> str:
    lines = []
    q = data.get("quote", {})
    name = data.get("name", data.get("symbol", ""))
    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {name}（{data.get('symbol', '')}）— Bitget rToken 报价")
    lines.append(f"  货币: {data.get('currency', 'USDT')}")
    lines.append(f"{'=' * 60}")
    lines.append(f"\n  ⚠ {data.get('disclaimer', '代币价/USDT/非交易所官方价')}")
    lines.append(f"  交易对: {data.get('pair', '')}")

    lines.append(f"\n  {'指标':<16} {'数值':>16}")
    lines.append(f"  {'-' * 34}")

    def _fmt_pct(v: Any) -> str:
        if v is None:
            return "-"
        return f"{float(v) * 100:.2f}%"

    for label, val in [
        ("参考价", q.get("price")),
        ("最新价", q.get("last")),
        ("买一", q.get("bid")),
        ("卖一", q.get("ask")),
        ("24h涨跌", _fmt_pct(q.get("change_pct")) if q.get("change_pct") is not None else None),
        ("24h最高", q.get("high_24h")),
        ("24h最低", q.get("low_24h")),
        ("24h成交额USDT", q.get("volume_usdt_24h")),
        ("计价依据", q.get("price_basis")),
    ]:
        if val is None:
            lines.append(f"  {label:<16} {'-':>16}")
        else:
            lines.append(f"  {label:<16} {str(val):>16}")

    lines.append(f"\n  数据时间: {data.get('timestamp', '')}")
    lines.append(f"  数据来源: Bitget rToken（非美股交易所官方价）")
    if data.get("fallback_reason"):
        lines.append(f"  回退原因: {data['fallback_reason']}")
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="美股分析")
    parser.add_argument("symbol", help="美股代码，如 AAPL、MSFT、TSLA")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    try:
        data = fetch_us_with_fallback(args.symbol)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
