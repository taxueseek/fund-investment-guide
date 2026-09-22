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


def test_eastmoney_missing_key_is_envelope_not_exit(monkeypatch, tmp_path) -> None:
    """缺 key 时必须返回信封（而非 sys.exit），否则 route 的回退链会被绕过。

    隔离要求：真实机器上 ~/.config/invest-cli/eastmoney.env 往往存在，
    只 pop 环境变量是不够的——load_api_key 会读到凭据文件而「假装有 key」，
    于是本用例在**已配置的机器上必挂、在未配置的机器上才过**（环境耦合）。
    这里同时屏蔽环境变量与凭据文件，让「缺 key」这一前提真正成立。
    """
    from cmd_stock import get_api_key
    from sources import eastmoney as em

    monkeypatch.delenv("EASTMONEY_APIKEY", raising=False)
    monkeypatch.setattr(em, "credential_files", lambda: [])
    monkeypatch.setattr(em, "load_api_key", lambda: "")
    # read_env 会回落到 launchctl / shell rc，同样要屏蔽
    monkeypatch.setattr("sources.env.read_env", lambda name: "")

    try:
        get_api_key()
        raise AssertionError("missing key must raise")
    except RuntimeError as e:
        assert "EASTMONEY_APIKEY" in str(e)
    except SystemExit as e:
        raise AssertionError(f"sys.exit 会绕过 route 回退: {e}") from e

    res = em.stock("600519")
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


def test_fetch_empty_arg_is_rejected_before_any_probe() -> None:
    """空标的必须在取数之前拦下：旧行为是打满整条链再拼三句错误。"""
    res = fetch("stock", "   ")
    assert res["ok"] is False
    assert "空标的" in res["error"]
    assert "tried" not in res  # 没有尝试过任何源


def test_fetch_probes_sources_lazily(monkeypatch) -> None:
    """主源命中时，后面的兜底源不得被探测。

    A 股链里 yfinance 只是末位兜底，但它的探测是真实 HTTPS（实测 0.5s）。
    旧实现 pick() 一次性探测全链，于是每次查 A 股都白付一次 Yahoo 往返。
    """
    import sources.route as route

    probed: list[str] = []

    def fake_detect(conf):
        probed.append(str(conf.get("name", "?")))
        return True, "ok"

    monkeypatch.setattr(route, "detect", fake_detect)
    monkeypatch.setattr(
        route,
        "_invoke",
        lambda sid, kind, arg: {"source": sid, "kind": kind, "ok": True,
                                "data": {"sid": sid}, "error": None},
    )
    res = route.fetch("stock", "600519", market="a")
    assert res["ok"] is True
    assert res["source"] == "hithink"
    assert len(probed) == 1, f"主源已命中却探测了 {probed}"


def test_fetch_detects_next_source_when_first_unavailable(monkeypatch) -> None:
    """反向对照：主源不可用时必须继续探测下一个，不能修成一律不探测。"""
    import sources.route as route

    calls = {"n": 0}

    def fake_detect(conf):
        calls["n"] += 1
        return calls["n"] > 1, "第一个不可用" if calls["n"] == 1 else "ok"

    monkeypatch.setattr(route, "detect", fake_detect)
    monkeypatch.setattr(
        route,
        "_invoke",
        lambda sid, kind, arg: {"source": sid, "kind": kind, "ok": True,
                                "data": {"sid": sid}, "error": None},
    )
    res = route.fetch("stock", "600519", market="a")
    assert res["ok"] is True
    assert res["source"] == "eastmoney"
    assert calls["n"] == 2, "第一个源不可用时未探测第二个"


def test_fetch_all_unavailable_keeps_original_message(monkeypatch) -> None:
    """整链都不通过探测时，结论与**前缀措辞**必须与旧 pick() 一致。

    本轮追加（场景实测发现）：只报 `kind=fund market=-` 是内部术语，用户看不出
    缺哪个 key——同一条链上的 stock 会把逐源原因列全。现在把探测失败原因接在
    原措辞之后，前缀不变，附加原因可省（`errors` 为空时保持原样）。
    """
    import sources.route as route

    monkeypatch.setattr(route, "detect", lambda conf: (False, "缺 key"))
    res = route.fetch("fund", "110011")
    assert res["ok"] is False
    assert res["error"].startswith("无可用数据源: kind=fund market=-")
    assert "缺 key" in res["error"], "报错没带逐源原因，用户不知道缺什么"
    assert res["tried"], "应给出试过哪些源"




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
