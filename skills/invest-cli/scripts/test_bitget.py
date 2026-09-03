#!/usr/bin/env python3
"""Bitget rToken adapter tests — default run needs no live network."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources.bitget import (  # noqa: E402
    choose_price,
    normalize_symbol,
    parse_ticker_row,
    us,
)
from sources import load_registry  # noqa: E402
from sources.registry import detect  # noqa: E402


def test_normalize_symbol() -> None:
    assert normalize_symbol("AAPL") == ("AAPL", "rAAPL", "RAAPLUSDT")
    assert normalize_symbol("rAAPL") == ("AAPL", "rAAPL", "RAAPLUSDT")
    assert normalize_symbol("RAAPLUSDT") == ("AAPL", "rAAPL", "RAAPLUSDT")
    assert normalize_symbol("BRK.B") == ("BRK.B", "rBRK.B", "RBRKBUSDT")
    assert normalize_symbol("$nvda") == ("NVDA", "rNVDA", "RNVDAUSDT")
    assert normalize_symbol("  msft ") == ("MSFT", "rMSFT", "RMSFTUSDT")
    # 真 ticker 以 R 开头，不能剥成 OKU
    assert normalize_symbol("ROKU") == ("ROKU", "rROKU", "RROKUUSDT")


def test_choose_price_mid_vs_last() -> None:
    price, basis = choose_price(100.0, 99.5, 100.5)
    assert basis == "mid"
    assert abs(price - 100.0) < 1e-9

    # 宽价差 → last
    price, basis = choose_price(50.0, 1.0, 199999.0)
    assert basis == "last"
    assert price == 50.0

    # 仅 last
    price, basis = choose_price(12.3, None, None)
    assert basis == "last"
    assert price == 12.3


def test_parse_ticker_fixture() -> None:
    row = {
        "open": "323.64",
        "symbol": "RAAPLUSDT",
        "high24h": "323.24",
        "low24h": "322.56",
        "lastPr": "323.1",
        "usdtVolume": "2591.413739",
        "ts": "1788090978709",
        "bidPr": "320.02",
        "askPr": "320.15",
        "change24h": "-0.00167",
    }
    q = parse_ticker_row(row, ticker="AAPL", rtoken="rAAPL", pair="RAAPLUSDT")
    assert q["symbol"] == "AAPL"
    assert q["rtoken"] == "rAAPL"
    assert q["pair"] == "RAAPLUSDT"
    assert q["currency"] == "USDT"
    assert q["quote_type"] == "rtoken"
    assert q["price_basis"] == "mid"
    assert abs(q["price"] - (320.02 + 320.15) / 2) < 1e-9
    assert q["change_24h"] == -0.00167
    assert q["last"] == 323.1
    assert "代币价" in q["disclaimer"]

    wide = dict(row)
    wide["bidPr"] = "1"
    wide["askPr"] = "199999"
    q2 = parse_ticker_row(wide, ticker="AAPL", rtoken="rAAPL", pair="RAAPLUSDT")
    assert q2["price_basis"] == "last"
    assert q2["price"] == 323.1


def test_us_missing_symbol_mock() -> None:
    body = json.dumps(
        {
            "code": "40034",
            "msg": "Parameter RBRKBUSDT does not exist",
            "data": None,
        }
    )

    def fake_get(url: str) -> tuple[int, str]:
        assert "RBRKBUSDT" in url
        return 400, body

    res = us("BRK.B", http_get=fake_get)
    assert res["ok"] is False
    assert res["source"] == "bitget"
    assert res["data"] is None
    assert "RBRKBUSDT" in (res["error"] or "")


def test_us_ok_mock() -> None:
    body = json.dumps(
        {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "lastPr": "100",
                    "bidPr": "99.9",
                    "askPr": "100.1",
                    "change24h": "0.01",
                    "high24h": "101",
                    "low24h": "99",
                    "usdtVolume": "1234.5",
                    "ts": "1700000000000",
                    "symbol": "RAAPLUSDT",
                }
            ],
        }
    )

    def fake_get(url: str) -> tuple[int, str]:
        return 200, body

    res = us("AAPL", http_get=fake_get)
    assert res["ok"] is True
    assert res["data"]["symbol"] == "AAPL"
    assert res["data"]["price_basis"] == "mid"
    assert res["data"]["quote_type"] == "rtoken"


def test_registry_bitget() -> None:
    reg = load_registry()
    assert "bitget" in reg
    conf = reg["bitget"]
    assert conf.get("priority") == 35
    assert conf.get("coverage") == ["us"]
    assert (conf.get("detect") or {}).get("type") == "always"
    available, detail = detect(conf)
    assert available is True
    assert "始终可用" in detail


def test_live_optional() -> None:
    if os.environ.get("INVEST_LIVE") != "1":
        return
    res = us("AAPL")
    assert res["ok"] is True, res.get("error")
    assert res["data"]["pair"] == "RAAPLUSDT"
    assert res["data"]["price"] is not None


if __name__ == "__main__":
    test_normalize_symbol()
    test_choose_price_mid_vs_last()
    test_parse_ticker_fixture()
    test_us_missing_symbol_mock()
    test_us_ok_mock()
    test_registry_bitget()
    test_live_optional()
    print("test_bitget: OK")
