#!/usr/bin/env python3
"""
美股分析 - yfinance 数据源
输出：估值 + 财务 + 评级（对标 invest-us 四维度框架）
"""

import sys
import json
from datetime import datetime


def fetch_us_data(symbol: str) -> dict:
    """使用 yfinance 获取美股数据"""
    try:
        import yfinance as yf
    except ImportError:
        print("错误: 未安装 yfinance。运行: pip3 install yfinance", file=sys.stderr)
        sys.exit(1)

    ticker = yf.Ticker(symbol.upper())

    # 基础信息
    info = ticker.info

    # 近期价格历史（1年）
    hist = ticker.history(period="1y")

    # 财务数据
    try:
        financials = ticker.financials
        balance = ticker.balance_sheet
        cashflow = ticker.cashflow
    except Exception:
        financials = balance = cashflow = None

    # 计算关键指标
    price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    pe = info.get("trailingPE") or info.get("forwardPE")
    pb = info.get("priceToBook")
    market_cap = info.get("marketCap")
    dividend_yield = info.get("dividendYield")
    beta = info.get("beta")

    # ROE
    roe = info.get("returnOnEquity")

    # 负债率
    debt_to_equity = info.get("debtToEquity")

    # 自由现金流
    fcf = info.get("freeCashflow")

    # 营收 & 净利润（最新年报）
    revenue = info.get("totalRevenue")
    net_income = info.get("netIncomeToCommon")

    # 52周高低
    high_52w = info.get("fiftyTwoWeekHigh")
    low_52w = info.get("fiftyTwoWeekLow")

    # 分析师评级
    recommendation = info.get("recommendationKey")
    target_price = info.get("targetMeanPrice")

    # 从历史数据计算最大回试
    max_drawdown = None
    if hist is not None and not hist.empty:
        prices = hist["Close"].dropna()
        if len(prices) > 0:
            peak = prices.expanding(min_periods=1).max()
            drawdown = (prices - peak) / peak
            max_drawdown = drawdown.min()

    return {
        "symbol": symbol.upper(),
        "name": info.get("shortName") or info.get("longName", ""),
        "currency": info.get("currency", "USD"),
        "timestamp": datetime.now().isoformat(),
        "quote": {
            "price": price,
            "change_pct": None,
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

    # 行情
    lines.append(f"\n  {'指标':<16} {'数值':>16}")
    lines.append(f"  {'-' * 34}")
    for key, label in [
        ("price", "当前价格"), ("pe_trailing", "市盈率(TTM)"),
        ("pe_forward", "市盈率(前瞻)"), ("pb", "市净率"),
        ("dividend_yield", "股息率"), ("beta", "Beta"),
        ("market_cap", "总市值"), ("high_52w", "52周最高"),
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

    # 财务
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

        # 利润率
        for key, label in [
            ("gross_margin", "毛利率"), ("operating_margin", "经营利润率"),
            ("profit_margin", "净利率"),
        ]:
            val = f.get(key)
            if val is not None:
                lines.append(f"  {label:<16} {val * 100:>15.1f}%")

    # 风险
    lines.append(f"\n  {'风险指标':<16} {'数值':>16}")
    lines.append(f"  {'-' * 34}")
    mdd = r.get("max_drawdown_1y")
    if mdd is not None:
        lines.append(f"  {'1年最大回撤':<16} {mdd * 100:>15.1f}%")
    if r.get("beta"):
        lines.append(f"  {'Beta':<16} {r['beta']:>16}")

    # 分析师
    if a.get("recommendation"):
        lines.append(f"\n  分析师评级: {a['recommendation']}")
        if a.get("target_price"):
            lines.append(f"  目标价: ${a['target_price']:.2f}")
        if a.get("analyst_count"):
            lines.append(f"  分析师数量: {a['analyst_count']}")

    # 业务
    if b.get("sector"):
        lines.append(f"\n  行业: {b.get('sector', '')} / {b.get('industry', '')}")
        lines.append(f"  国家: {b.get('country', '')}")

    lines.append(f"\n  数据时间: {data['timestamp']}")
    lines.append(f"  数据来源: Yahoo Finance")
    return "\n".join(lines)


def main():
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
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
