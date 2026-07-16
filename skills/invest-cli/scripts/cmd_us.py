#!/usr/bin/env python3
"""
美股分析 - yfinance 数据源
输出：估值 + 财务 + 评级（对标 invest-stock 四维框架）

JSON 契约：与 stock/fund 一致，始终提供扁平 ``data``，
同时保留 quote/financial 分区，方便终端展示与 agent 消费。
"""
from __future__ import annotations

import sys
from datetime import datetime

from _common import ensure_script_dir_on_path, json_out

ensure_script_dir_on_path()


def fetch_us_data(symbol: str) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        print(
            "错误: 未安装 yfinance。运行: python3 -m pip install yfinance",
            file=sys.stderr,
        )
        sys.exit(1)

    ticker = yf.Ticker(symbol.upper())
    info = ticker.info or {}
    hist = ticker.history(period="1y")

    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    pe_trailing = info.get("trailingPE")
    pe_forward = info.get("forwardPE")
    pb = info.get("priceToBook")
    market_cap = info.get("marketCap")
    dividend_yield = info.get("dividendYield")
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
            max_drawdown = float(drawdown.min())

    quote = {
        "price": price,
        "change_pct": None,
        "market_cap": market_cap,
        "pe_trailing": pe_trailing,
        "pe_forward": pe_forward,
        "pb": pb,
        "dividend_yield": dividend_yield,
        "beta": beta,
        "high_52w": high_52w,
        "low_52w": low_52w,
    }
    financial = {
        "revenue": revenue,
        "net_income": net_income,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "free_cash_flow": fcf,
        "gross_margin": info.get("grossMargins"),
        "operating_margin": info.get("operatingMargins"),
        "profit_margin": info.get("profitMargins"),
    }
    analyst = {
        "recommendation": recommendation,
        "target_price": target_price,
        "analyst_count": info.get("numberOfAnalystOpinions"),
    }
    risk = {"max_drawdown_1y": max_drawdown, "beta": beta}
    business = {
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "country": info.get("country"),
        "employees": info.get("fullTimeEmployees"),
    }

    # Flat data for investment-agent / shared consumers (contract with stock/fund)
    flat = {
        **quote,
        **financial,
        "recommendation": recommendation,
        "target_price": target_price,
        "max_drawdown_1y": max_drawdown,
        "sector": business.get("sector"),
        "industry": business.get("industry"),
    }
    # Chinese aliases used by monitor thresholds when scanning US via shared gates
    if pe_trailing is not None:
        flat["市盈率PE(TTM)"] = pe_trailing
    if pb is not None:
        flat["市净率PB"] = pb
    if roe is not None:
        # yfinance ROE is typically a ratio (0.15); expose percent for CN consumers
        flat["净资产收益率ROE"] = roe * 100 if abs(roe) <= 2 else roe
    if price is not None:
        flat["最新价"] = price
        flat["收盘价"] = price

    return {
        "symbol": symbol.upper(),
        "code": symbol.upper(),
        "name": info.get("shortName") or info.get("longName") or symbol.upper(),
        "currency": info.get("currency", "USD"),
        "timestamp": datetime.now().isoformat(),
        "quote": quote,
        "financial": financial,
        "analyst": analyst,
        "risk": risk,
        "business": business,
        "data": flat,
    }


def format_terminal(data: dict) -> str:
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
        ("price", "当前价格"),
        ("pe_trailing", "市盈率(TTM)"),
        ("pe_forward", "市盈率(前瞻)"),
        ("pb", "市净率"),
        ("dividend_yield", "股息率"),
        ("beta", "Beta"),
        ("market_cap", "总市值"),
        ("high_52w", "52周最高"),
        ("low_52w", "52周最低"),
    ]:
        val = q.get(key)
        if val is not None:
            if key == "dividend_yield":
                val = f"{val * 100:.2f}%"
            elif key == "market_cap":
                val = f"{val / 1e8:.0f}亿" if val >= 1e8 else f"{val / 1e6:.0f}M"
            lines.append(f"  {label:<16} {str(val):>16}")
        else:
            lines.append(f"  {label:<16} {'-':>16}")

    if f:
        lines.append(f"\n  {'财务指标':<16} {'数值':>16}")
        lines.append(f"  {'-' * 34}")
        for key, label in [
            ("revenue", "营收"),
            ("net_income", "净利润"),
            ("roe", "ROE"),
            ("debt_to_equity", "负债/权益"),
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
            ("gross_margin", "毛利率"),
            ("operating_margin", "经营利润率"),
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
    lines.append("  数据来源: Yahoo Finance")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="美股分析")
    parser.add_argument("symbol", help="美股代码，如 AAPL、MSFT、TSLA")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    try:
        data = fetch_us_data(args.symbol)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json_out(data))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
