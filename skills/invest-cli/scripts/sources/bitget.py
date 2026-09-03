"""Bitget rToken 美股行情适配器（仅报价，无财务）。

公开 API、无需 key，仅依赖 stdlib（urllib + json）。
价格为 USDT 代币价，非美股交易所官方报价。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Optional

API_BASE = "https://api.bitget.com"
TICKER_PATH = "/api/v2/spot/market/tickers"
DEFAULT_TIMEOUT = 10
USER_AGENT = "Mozilla/5.0"
# bid/ask 价差相对 mid 低于该阈值才采用 mid，否则用 lastPr
MAX_SANE_SPREAD = 0.05
DISCLAIMER = "代币价/USDT/非交易所官方价"

# 可注入的 GET，便于单测无网 mock
_HttpGet = Callable[[str], tuple[int, str]]


def normalize_symbol(raw: str) -> tuple[str, str, str]:
    """把用户输入规范为 (ticker, rtoken, pair)。

    接受 AAPL / rAAPL / RAAPLUSDT / $nvda / BRK.B 等。
    仅当显式小写 r 前缀（rAAPL）或 *USDT 交易对时剥掉 r；
    ROKU 等真 ticker 不会被误拆成 OKU。
    类别股去掉点号建 pair：BRK.B → RBRKBUSDT。
    """
    stripped = (raw or "").strip().replace("$", "").replace(" ", "")
    if not stripped:
        raise ValueError("空代码")

    # 显式 rToken 写法：rAAPL / rBRK.B（前缀 r 为小写）
    explicit_rtoken = len(stripped) > 1 and stripped[0] == "r" and stripped[1].isalpha()

    s = stripped.upper()

    if s.endswith("USDT") and len(s) > 4:
        pair = s
        base = s[:-4]  # RAAPL
        if base.startswith("R") and len(base) > 1:
            ticker = base[1:]
            rtoken = "r" + ticker
        else:
            ticker = base
            rtoken = "r" + ticker
            pair = f"R{ticker.replace('.', '')}USDT"
        return ticker, rtoken, pair

    if explicit_rtoken:
        ticker = s[1:]  # AAPL
        pair_base = ticker.replace(".", "")
        return ticker, "r" + ticker, f"R{pair_base}USDT"

    ticker = s
    pair_base = ticker.replace(".", "")
    return ticker, "r" + ticker, f"R{pair_base}USDT"


def _default_http_get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return resp.getcode() or 200, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return int(e.code), body
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ConnectionError(f"Bitget 请求失败: {e}") from e


def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ts_to_iso(ts_ms: Any) -> Optional[str]:
    ms = _to_float(ts_ms)
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def choose_price(
    last: Optional[float],
    bid: Optional[float],
    ask: Optional[float],
    max_spread: float = MAX_SANE_SPREAD,
) -> tuple[Optional[float], str]:
    """价差合理时用 mid，否则用 last。返回 (price, price_basis)。"""
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        if mid > 0:
            spread = (ask - bid) / mid
            if spread < max_spread:
                return mid, "mid"
    if last is not None:
        return last, "last"
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / 2.0, "mid"
    # 无任何可用报价：返回 None + "n/a"，不要把 (None,"last") 当真实行情
    return None, "n/a"


def parse_ticker_row(
    row: dict[str, Any],
    ticker: str,
    rtoken: str,
    pair: str,
) -> dict[str, Any]:
    """把 Bitget ticker 单条记录解析为报价 payload。"""
    last = _to_float(row.get("lastPr"))
    bid = _to_float(row.get("bidPr"))
    ask = _to_float(row.get("askPr"))
    price, basis = choose_price(last, bid, ask)
    change = _to_float(row.get("change24h"))
    return {
        "symbol": ticker,
        "rtoken": rtoken,
        "pair": pair,
        "price": price,
        "price_basis": basis,
        "last": last,
        "bid": bid,
        "ask": ask,
        "change_24h": change,
        "high_24h": _to_float(row.get("high24h")),
        "low_24h": _to_float(row.get("low24h")),
        "volume_usdt_24h": _to_float(row.get("usdtVolume")),
        "ts": _ts_to_iso(row.get("ts")),
        "currency": "USDT",
        "quote_type": "rtoken",
        "disclaimer": DISCLAIMER,
    }


def _envelope(
    ok: bool,
    data: Any = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "source": "bitget",
        "kind": "us",
        "ok": ok,
        "data": data,
        "error": error,
    }


def us(
    symbol: str,
    *,
    http_get: Optional[_HttpGet] = None,
) -> dict[str, Any]:
    """获取美股 rToken 报价信封。http_get 可注入，签名 (url) -> (status, body)。"""
    try:
        ticker, rtoken, pair = normalize_symbol(symbol)
    except ValueError as e:
        return _envelope(False, error=f"无效代码: {e}")

    getter = http_get or _default_http_get
    qs = urllib.parse.urlencode({"symbol": pair})
    url = f"{API_BASE}{TICKER_PATH}?{qs}"

    try:
        status, body = getter(url)
    except ConnectionError as e:
        return _envelope(False, error=str(e))
    except Exception as e:
        return _envelope(False, error=f"Bitget 请求异常: {e}")

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        return _envelope(False, error=f"Bitget 返回非 JSON (HTTP {status})")

    code = str(payload.get("code", ""))
    msg = payload.get("msg") or ""
    data = payload.get("data")

    if status == 400 or code == "40034":
        return _envelope(
            False,
            error=f"Bitget 无此 rToken: {pair}（{ticker}）。{msg}".strip(),
        )
    if status >= 400 or (code and code != "00000"):
        return _envelope(
            False,
            error=f"Bitget 错误 HTTP {status} code={code}: {msg or body[:200]}",
        )
    if not isinstance(data, list) or not data:
        return _envelope(False, error=f"Bitget 无行情数据: {pair}")

    row = data[0]
    if not isinstance(row, dict):
        return _envelope(False, error=f"Bitget 行情格式异常: {pair}")

    quote = parse_ticker_row(row, ticker=ticker, rtoken=rtoken, pair=pair)
    return _envelope(True, data=quote)
