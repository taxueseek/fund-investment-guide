#!/usr/bin/env python3
"""Runtime router tests — no live network. Locks MECE pick rules."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources.route import fetch, pick  # noqa: E402


def test_stock_a_excludes_wind_and_orders() -> None:
    ids = pick("stock", market="a")
    assert "wind" not in ids, "Wind 只有 call()，不能进快照链"
    assert "yingmi" not in ids
    assert "bitget" not in ids
    if "hithink" in ids and "eastmoney" in ids:
        assert ids.index("hithink") < ids.index("eastmoney")


def test_stock_hk_excludes_hithink() -> None:
    ids = pick("stock", market="hk")
    assert "hithink" not in ids


def test_fund_snapshot_skips_yingmi_ttfund() -> None:
    ids = pick("fund")
    assert "yingmi" not in ids, "盈米无 fund() 快照，诊断走 intent 另一条问题"
    assert "ttfund" not in ids
    assert "wind" not in ids
    if "hithink" in ids and "eastmoney" in ids:
        assert ids.index("hithink") < ids.index("eastmoney")


def test_us_skips_uninstalled_yfinance() -> None:
    ids = pick("us")
    assert "hithink" not in ids
    assert "eastmoney" not in ids
    assert "bitget" in ids
    if "yfinance" in ids:
        assert ids.index("yfinance") < ids.index("bitget")


def test_screen_is_eastmoney_only() -> None:
    ids = pick("screen")
    assert "hithink" not in ids
    assert "wind" not in ids
    if ids:
        assert ids == ["eastmoney"]


def test_fetch_first_ok_stops() -> None:
    calls: list[str] = []

    def fake(sid, kind, arg):
        calls.append(sid)
        if sid == "hithink":
            return {"source": sid, "kind": kind, "ok": False, "data": None, "error": "miss"}
        return {"source": sid, "kind": kind, "ok": True, "data": {"code": arg}, "error": None}

    res = fetch("stock", "600519", order=["hithink", "eastmoney"], invoke=fake)
    assert res["ok"] is True
    assert res["source"] == "eastmoney"
    assert res["fallback_from"] == "hithink"
    assert calls == ["hithink", "eastmoney"]


def test_fetch_all_fail_returns_tried_envelope() -> None:
    """整链失败必须返回带 tried 的信封，不得抛异常（回退语义锁定，不依赖本机环境）。"""

    def fake(sid, kind, arg):
        return {"source": sid, "kind": kind, "ok": False, "data": None, "error": "down"}

    res = fetch("stock", "600519", order=["hithink", "eastmoney"], invoke=fake)
    assert res["ok"] is False
    assert res["tried"] == ["hithink", "eastmoney"]
    assert "hithink" in res["error"] and "eastmoney" in res["error"]


def test_fetch_exception_continues_to_next() -> None:
    """单源抛异常按失败计，整单继续回退。"""
    calls: list[str] = []

    def fake(sid, kind, arg):
        calls.append(sid)
        if sid == "hithink":
            raise RuntimeError("boom")
        return {"source": sid, "kind": kind, "ok": True, "data": {"code": arg}, "error": None}

    res = fetch("stock", "600519", order=["hithink", "eastmoney"], invoke=fake)
    assert res["ok"] is True
    assert res["source"] == "eastmoney"
    assert "hithink" in res["fallback_error"]
    assert calls == ["hithink", "eastmoney"]


def test_eastmoney_missing_key_is_envelope_not_exit() -> None:
    import os

    os.environ.pop("EASTMONEY_APIKEY", None)
    from cmd_stock import get_api_key
    from sources.eastmoney import stock as em_stock

    try:
        get_api_key()
        raise AssertionError("missing key must raise")
    except RuntimeError as e:
        assert "EASTMONEY_APIKEY" in str(e)
    except SystemExit as e:
        raise AssertionError(f"sys.exit 会绕过 route 回退: {e}") from e

    res = em_stock("600519")
    assert res["ok"] is False
    assert res["source"] == "eastmoney"
    assert "EASTMONEY" in (res.get("error") or "").upper() or "未设置" in (res.get("error") or "")


def test_fetch_does_not_mix_payloads() -> None:
    def fake(sid, kind, arg):
        return {
            "source": sid,
            "kind": kind,
            "ok": True,
            "data": {"pe": 1 if sid == "hithink" else 99},
            "error": None,
        }

    res = fetch("stock", "600519", market="a", invoke=fake)
    assert res["data"]["pe"] == 1
    assert "fallback_from" not in res


if __name__ == "__main__":
    test_stock_a_excludes_wind_and_orders()
    test_stock_hk_excludes_hithink()
    test_fund_snapshot_skips_yingmi_ttfund()
    test_us_skips_uninstalled_yfinance()
    test_screen_is_eastmoney_only()
    test_fetch_first_ok_stops()
    test_fetch_does_not_mix_payloads()
    test_eastmoney_missing_key_is_envelope_not_exit()
    print("test_route: OK")
