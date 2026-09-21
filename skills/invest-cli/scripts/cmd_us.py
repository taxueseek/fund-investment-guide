#!/usr/bin/env python3
"""
美股分析 — yfinance 全量快照优先，Bitget rToken 报价兜底。
输出：估值 + 财务 + 评级（yfinance）；或 rToken/USDT 报价（bitget）。

代码规范化：yfinance 也兜底 A股/港股（见 sources/yfinance.py 的 stock()），
6 位 A 股代码 → 600519.SS / 000858.SZ；5 位港股代码 → 0700.HK。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, NamedTuple

# yfinance 用标准 logging（logger 名 "yfinance"，propagate=True、无自带 handler），
# 所以它每遇到一次上游错误就把**原始 HTTP 响应体**经 root 的 lastResort handler
# 打到 stderr。实测未知代码时 stderr 出现整段
# `HTTP Error 404: {"quoteSummary":...}`，与 invest-cli 自己的错误行混在一起，
# 而 stderr 是给人和 agent 读的错误通道——真实原因会被这段噪音淹没。
# 错误本身由下方守卫转成一句可读中文，这里只负责掐掉库的裸输出。
logging.getLogger("yfinance").setLevel(logging.CRITICAL)

_CN_SH = re.compile(r"^60[0135]\d{3}$|^688\d{3}$|^689\d{3}$")
_CN_SZ = re.compile(r"^00[013]\d{3}$|^30[01]\d{3}$")

# yfinance 在库内把每个端点的 timeout 写死成 30s，且不暴露配置入口
# （实测 yfinance 1.2.0 data.py 内 9 处 timeout=30，YfData 无任何 timeout 属性）。
# 结果是「上游不可达」这一最常见故障要付满 30s 才回退。
# 这里给连接阶段设一个有界预算：超时即快速失败，交给 route 回退到 bitget。
# 默认 8s（够真实慢网络往返，又在最坏情况下把 31s 压到 ~8s）；
# 可用 INVEST_CLI_HTTP_TIMEOUT 覆盖，0 或非法值视为不设限。
_DEFAULT_HTTP_TIMEOUT = 8.0


def _http_timeout() -> float:
    raw = os.environ.get("INVEST_CLI_HTTP_TIMEOUT", "").strip()
    if not raw:
        return _DEFAULT_HTTP_TIMEOUT
    try:
        val = float(raw)
    except ValueError:
        return _DEFAULT_HTTP_TIMEOUT
    return val if val > 0 else 0.0


def _bound_yfinance_timeouts() -> None:
    """把 yfinance 写死的 30s 端点超时收到有界预算。

    **为什么必须在 curl_cffi 的 CURLOPT 层拦**（此前的实现是无效的，教训记录）：
    yfinance 1.2.0 里 `from curl_cffi import requests` 并构造
    `curl_cffi.requests.Session(impersonate=...)`。而
    `issubclass(curl_cffi.requests.Session, requests.Session)` 是 **False**——
    给 `requests.Session.request` 打补丁对 yfinance 毫无作用（实测确认）。
    同时 yfinance 传的是**显式** timeout 字面量，所以「注入默认值」也不会生效。

    正确做法是拦 libcurl 的 setopt。且必须用 **_MS 变体**：curl_cffi 走的是
    `CurlOpt.TIMEOUT_MS`(155) / `CONNECTTIMEOUT_MS`(156)，单位毫秒；
    而 `TIMEOUT`(13) / `CONNECTTIMEOUT`(78) 是秒，curl_cffi 并不设置它们。
    只拦 13/78 等于没拦（实测：请求 30s 超时照旧 30s 才返回）。
    两个变体都拦、各自按单位取小，才真正生效（实测 30s → 3.00s）。

    全程**尽力而为**：任何一步失败都静默跳过，绝不因此让取数失败。
    """
    budget = _http_timeout()
    if budget <= 0:
        return

    try:
        from curl_cffi import Curl  # type: ignore
        from curl_cffi.const import CurlOpt  # type: ignore

        if getattr(Curl, "_invest_cli_bounded", False):
            return

        # 毫秒档与秒档分开，避免单位混用（混用会直接抛 TypeError 或被当成巨大值）
        _ms_opts = (int(CurlOpt.TIMEOUT_MS), int(CurlOpt.CONNECTTIMEOUT_MS))
        _sec_opts = (int(CurlOpt.TIMEOUT), int(CurlOpt.CONNECTTIMEOUT))
        _orig_setopt = Curl.setopt

        def _bounded_setopt(self, option, value):  # type: ignore[no-untyped-def]
            if isinstance(value, (int, float)) and value > 0:
                if option in _ms_opts:
                    value = min(int(value), int(budget * 1000))
                elif option in _sec_opts:
                    value = min(value, budget)
            return _orig_setopt(self, option, value)

        Curl.setopt = _bounded_setopt  # type: ignore[assignment]
        Curl._invest_cli_bounded = True  # type: ignore[attr-defined]
    except Exception:
        pass


def normalize_ticker(symbol: str) -> str:
    """yfinance 代码规范化：CN A股/港股代码 → 带后缀 ticker；美股原样。

    刻意**不做**「点号转连字符」这类形状改写：点号在美股语境里既可能是类别股
    （BRK.B → BRK-B），也可能是交易所后缀（VOD.L 伦敦、VOW3.F 法兰克福），
    按字符串形状猜一定会误伤一侧（实测：按「纯字母 + 单字母后缀」改写后，
    `us VOD.L` 从有数据变成报错）。类别股改由**事实**判定，见 `_load_ticker` 的
    空壳回退：点号形式拿不到任何标识字段时才试连字符形式。
    """
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


# yfinance 对不存在的代码不会抛「未找到」，而是走两条歧路（均实测）：
#   - `Ticker.info` 返回**非空但无内容**的 dict（实测 {'trailingPegRatio': None}）；
#   - `Ticker.history` 在库内 _get_ticker_tz 里抛
#     `TypeError: argument of type 'NoneType' is not a container or iterable`。
# 前者会让「查不存在的公司」拿到一张全 None 的快照且 ok=true（静默假成功），
# 后者会把一句 Python 内部报错当成用户可见原因。两种都不该外泄。
#
# 判据用「有没有任何一条能标识标的的字段」——不比对名称（易误判），
# 与 cmd_stock/cmd_fund 的实体守卫同思路：结构自洽才放行。
#
# 刻意**不含 symbol / currency**：这两个是请求侧原样回显的（实测 BRK.B 这种
# 未规范化的写法会得到 `symbol: "BRK.B"` 而其余字段全空）。把它们算作
# 「有数据」等于让守卫形同虚设。
_IDENTITY_FIELDS = (
    "shortName", "longName",
    "currentPrice", "regularMarketPrice", "previousClose", "marketCap",
)


def _identity_present(info: dict[str, Any]) -> bool:
    return any(info.get(k) for k in _IDENTITY_FIELDS)


def _settle(fut: Any) -> tuple[Any, BaseException | None]:
    """取 future 结果，异常不外抛：返回 (值, 异常)。

    两路取数各自独立，一路失败不该让另一路的结果被丢弃——
    丢弃后就无法判断「标的本身不存在」还是「只是这一路传输失败」。
    """
    try:
        return fut.result(), None
    except Exception as e:  # noqa: BLE001 —— 上游库抛什么都要归一
        return None, e


class _Attempt(NamedTuple):
    """一次取数尝试的结果。

    `error` 是「传输/库层失败」，与「拿到了 info 但没有标识字段」（标的不存在）
    是两件事，必须分开传出去才能分开报。用具名元组而不是位置元组：
    调用方要读的是 `attempt.error`，不是「三元组的中间那个」。
    """

    info: Any
    error: BaseException | None
    hist: Any


def _load_ticker(ticker_symbol: str) -> _Attempt:
    """取 info + 近 1 年历史。

    info 与 history 相互独立，串行会让两段网络等待相加；并发后不再叠加。
    异常不外抛：调用方要靠「info 异常」还是「info 空壳」来区分传输失败与标的不存在。
    """
    import yfinance as yf

    ticker = yf.Ticker(ticker_symbol)
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_info = pool.submit(lambda: ticker.info)
        fut_hist = pool.submit(lambda: ticker.history(period="1y"))
        info, info_err = _settle(fut_info)
        hist, hist_err = _settle(fut_hist)
    return _Attempt(info, info_err, None if hist_err is not None else hist)


def _resolve_snapshot(symbol: str) -> _Attempt:
    """取快照；点号形式拿不到标识字段时，按**事实**回退连字符形式（类别股）。

    类别股（BRK.B / BF.B）Yahoo 只认连字符写法，点号形式返回空壳。但不能按
    字符串形状改写：点号也可能是交易所后缀（VOD.L 伦敦、VOW3.F 法兰克福），
    按形状猜必然误伤一侧（实测打断过 `us VOD.L`）。判据只能是「上游给没给数据」。

    首次尝试的错误优先保留：用户问的是他给的那个代码，报错就该报那个。
    """
    primary = normalize_ticker(symbol)
    attempt = _load_ticker(primary)
    if _identity_present(attempt.info or {}) or "." not in primary:
        return attempt
    alt = _load_ticker(primary.replace(".", "-"))
    return alt if _identity_present(alt.info or {}) else attempt


def fetch_us_data(symbol: str) -> dict:
    """使用 yfinance 获取全量快照（美股为主，也兜底 A股/港股。失败抛异常；未安装也抛 ImportError）。"""
    _bound_yfinance_timeouts()

    attempt = _resolve_snapshot(symbol)

    # 「取数失败」与「标的不存在」必须分开报（与 cmd_stock/cmd_fund 同一条纪律）：
    # info 抛异常 = 传输/库层问题，不能据此断言标的不存在；
    # info 正常返回但没有标识字段 = 上游确实没有这个标的。
    if attempt.error is not None:
        raise RuntimeError(
            f"yfinance 取数失败（{symbol}）：{type(attempt.error).__name__}: {attempt.error}"
        )
    info = attempt.info
    hist = attempt.hist
    if not isinstance(info, dict) or not _identity_present(info):
        raise ValueError(f"未找到标的「{symbol}」（Yahoo 无该代码的行情）")

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
