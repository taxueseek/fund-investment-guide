#!/usr/bin/env python3
"""hithink adapter tests — default run needs no live network and never prints the Key."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from sources import load_registry  # noqa: E402
from sources.hithink import (  # noqa: E402
    ENV_KEY,
    _request_many,
    build_history,
    fund,
    looks_like_hk,
    parse_indicators,
    pick_ticker,
    stock,
)
from sources.registry import detect  # noqa: E402


def _ok(data):
    return json.dumps({"code": 0, "message": "success", "data": data})


def _item(*rows):
    return {"timestamp": 1, "item": list(rows)}


class Router:
    def __init__(self, routes: dict[str, tuple[int, str]]):
        self.routes = routes
        self.calls: list[str] = []
        self.headers: list[dict] = []

    def __call__(self, url: str, headers=None):
        self.calls.append(url)
        self.headers.append(dict(headers or {}))
        path = urlparse(url).path
        if path not in self.routes:
            raise AssertionError(f"unexpected path {path}")
        return self.routes[path]


def test_request_many_injected_client_is_serial() -> None:
    order: list[str] = []

    def fake(url, headers=None):
        path = urlparse(url).path
        order.append(path)
        return 200, json.dumps({"code": 0, "message": "ok", "data": {"item": []}})

    got = _request_many(
        [
            ("a", "/api/a", {"x": 1}),
            ("b", "/api/b", {"x": 2}),
            ("c", "/api/c", {"x": 3}),
        ],
        api_key="k",
        http_get=fake,
        sleep=lambda _t: None,
    )
    assert list(got) == ["a", "b", "c"]
    assert order == ["/api/a", "/api/b", "/api/c"]


def test_looks_like_hk() -> None:
    assert looks_like_hk("00700") is True
    assert looks_like_hk("09988.HK") is True
    assert looks_like_hk("600519") is False
    assert looks_like_hk("茅台") is False


def test_pick_ticker_exact_and_ambiguous() -> None:
    items = [
        {"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台", "asset_type": "a-share"},
        {"thscode": "600519.SH", "ticker": "600519", "name": "dummy", "asset_type": "a-share-index"},
    ]
    picked, err = pick_ticker(items, "600519", frozenset({"a-share"}))
    assert err == ""
    assert picked["thscode"] == "600519.SH"

    amb = [
        {"thscode": "000001.SZ", "ticker": "000001", "name": "平安银行", "asset_type": "a-share"},
        {"thscode": "600000.SH", "ticker": "600000", "name": "浦发银行", "asset_type": "a-share"},
    ]
    picked, err = pick_ticker(amb, "银行", frozenset({"a-share"}))
    assert picked is None
    assert "无法唯一消歧" in err


def test_parse_indicators_array_not_object() -> None:
    abilities = [
        {
            "ability": "profitability",
            "indicators": [
                {"index_id": "index_weighted_avg_roe", "value": "32.5300"},
                {"index_id": "sale_gross_margin", "value": None},
            ],
        }
    ]
    out = parse_indicators(abilities)
    assert out["roe"] == 32.53
    assert out["gross_margin"] is None  # null 不补零


def test_build_history_null_not_zero() -> None:
    inc = [{"fiscal_year": 2025, "operating_income": 100, "operating_costs": 40, "net_profit": None, "basic_eps": 1}]
    bal = [{"fiscal_year": 2025, "assets_total": 200, "total_debt": 50, "holder_equity_total": 150}]
    cf = [{"fiscal_year": 2025, "act_cash_flow_net": None}]
    hist = build_history(inc, bal, cf)
    assert len(hist) == 1
    row = hist[0]
    assert abs(row["gross_margin"] - 60.0) < 1e-9
    assert row["net_profit"] is None
    assert row["ocf"] is None
    assert row["ocf_to_ni"] is None
    assert abs(row["debt_ratio"] - 25.0) < 1e-9


def test_stock_hk_no_http() -> None:
    def boom(url, headers=None):
        raise AssertionError("港股不得打 A 股接口")

    res = stock("00700", http_get=boom, sleep=lambda _t: None)
    assert res["ok"] is False
    assert res["source"] == "hithink"
    assert "港股" in (res["error"] or "")


def test_stock_ok_mock() -> None:
    os.environ[ENV_KEY] = "test-key-not-real"
    router = Router(
        {
            "/api/meta/tickers/search": (
                200,
                _ok(_item({"thscode": "600519.SH", "ticker": "600519", "name": "贵州茅台", "asset_type": "a-share", "currency": "CNY"})),
            ),
            "/api/a-share/prices/snapshot": (
                200,
                _ok(_item({"thscode": "600519.SH", "ticker": "600519", "last_price": 1297.4, "open_price": 1290, "price_change_ratio_pct": 0.39})),
            ),
            "/api/a-share/valuations/snapshot": (
                200,
                _ok(_item({"thscode": "600519.SH", "pe_ttm": 19.9, "pb_mrq": 6.45, "pe_mrq": 18.2, "ps_ttm": 9.3, "pcf_ttm": 13.6})),
            ),
            "/api/a-share/financials/income-statements": (
                200,
                _ok(_item({"fiscal_year": 2025, "operating_income": 1.6e11, "operating_costs": 1.4e10, "net_profit": 8.5e10, "basic_eps": 65.66, "parent_holder_net_profit": 8.5e10})),
            ),
            "/api/a-share/financials/balance-sheets": (
                200,
                _ok(_item({"fiscal_year": 2025, "assets_total": 3.0e11, "total_debt": 5.0e10, "holder_equity_total": 2.5e11})),
            ),
            "/api/a-share/financials/cash-flow-statements": (
                200,
                _ok(_item({"fiscal_year": 2025, "act_cash_flow_net": 6.3e10})),
            ),
            "/api/a-share/financials/indicators": (
                200,
                _ok(
                    {
                        "thscode": "600519.SH",
                        "report": "2025-4",
                        "abilities": [
                            {"ability": "profitability", "indicators": [
                                {"index_id": "index_weighted_avg_roe", "value": "32.53"},
                                {"index_id": "sale_gross_margin", "value": "91.18"},
                            ]},
                            {"ability": "solvency", "indicators": [
                                {"index_id": "assets_debt_ratio", "value": "16.42"},
                            ]},
                        ],
                    }
                ),
            ),
        }
    )
    res = stock("600519", http_get=router, sleep=lambda _t: None)
    assert res["ok"] is True, res.get("error")
    data = res["data"]
    assert data["thscode"] == "600519.SH"
    assert data["quote"]["last"] == 1297.4
    assert data["valuation"]["pe_ttm"] == 19.9
    assert data["financials"]["roe"] == 32.53
    assert data["financials"]["roe_source"] == "index_weighted_avg_roe"
    assert data["data"]["市盈率PE(TTM)"] == 19.9
    dumped = json.dumps(res, ensure_ascii=False)
    assert "test-key-not-real" not in dumped
    assert all("X-api-key" in h for h in router.headers)
    assert any("indicators" in u and "2025-4" in u for u in router.calls)
    # 不得猜后缀：必须先 search
    assert any("tickers/search" in u for u in router.calls)
    qs = parse_qs(urlparse(router.calls[0]).query)
    assert qs.get("q") == ["600519"]


def test_fund_ok_mock() -> None:
    os.environ[ENV_KEY] = "test-key-not-real"
    router = Router(
        {
            "/api/meta/tickers/search": (
                200,
                _ok(_item({"thscode": "110011.OF", "ticker": "110011", "name": "优质精选", "asset_type": "fund-otc"})),
            ),
            "/api/fund/profile/detail": (
                200,
                _ok(_item({
                    "thscode": "110011.OF",
                    "fund_name": "优质精选",
                    "mgmt_name": "易方达基金管理有限公司",
                    "manager_name": "张坤",
                    "fund_scale": 6777001473.91,
                    "unit_nav": 4.2094,
                    "estab_date": 1262275200000,
                    "rate_info": [
                        {"rate_type": "management", "standard_rate": "1.20%"},
                        {"rate_type": "custody", "standard_rate": "0.20%"},
                        {"rate_type": "purchase", "standard_rate": "1.50%"},
                    ],
                    "manager_info": [
                        {"manager_id": "new", "manager_name": "新人", "tenure_days": 64},
                        {"manager_id": "x", "manager_name": "张坤", "tenure_days": 1815},
                    ],
                })),
            ),
            "/api/fund/performance/returns": (
                200,
                _ok(_item({"return_month": 2.16, "return_year": -22.62, "return_nowyear": -20.71})),
            ),
            "/api/fund/performance/drawdowns": (
                200,
                _ok(_item({"year": -30.1, "tyear": -45.0})),
            ),
            "/api/fund/portfolio/holdings": (
                200,
                _ok(_item({"stock_name": "贵州茅台", "ticker": "600519", "hold_ratio": 9.23, "investment_rank": 2})),
            ),
        }
    )
    res = fund("110011", http_get=router, sleep=lambda _t: None)
    assert res["ok"] is True, res.get("error")
    data = res["data"]
    assert data["thscode"] == "110011.OF"
    assert data["fund_type"] == "otc"
    assert data["fees"]["management"] == "1.20%"
    assert data["profile"]["manager_name"] == "张坤"
    assert data["returns"]["year"] == -22.62
    assert data["holdings"][0]["stock_name"] == "贵州茅台"
    assert data["data"]["近1年回报"] == -22.62
    assert "test-key-not-real" not in json.dumps(res)


def test_fund_subrequest_failure_envelope_false() -> None:
    """业绩/回撤/持仓任一失败 → 整单 ok=False（route 回退），不输出缺块残缺快照。"""
    os.environ[ENV_KEY] = "test-key-not-real"
    router = Router(
        {
            "/api/meta/tickers/search": (
                200,
                _ok(_item({"thscode": "110011.OF", "ticker": "110011", "name": "优质精选", "asset_type": "fund-otc"})),
            ),
            "/api/fund/profile/detail": (
                200,
                _ok(_item({"thscode": "110011.OF", "fund_name": "优质精选", "rate_info": []})),
            ),
            "/api/fund/performance/returns": (429, "rate limited"),
            "/api/fund/performance/drawdowns": (429, "rate limited"),
            "/api/fund/portfolio/holdings": (429, "rate limited"),
        }
    )
    res = fund("110011", http_get=router, sleep=lambda _t: None)
    assert res["ok"] is False, "子请求失败必须整单失败，让 route 回退"
    assert "收益" in (res.get("error") or "") and "429" in (res.get("error") or "")


def test_registry_hithink() -> None:
    reg = load_registry()
    assert "hithink" in reg
    conf = reg["hithink"]
    assert conf.get("priority") == 60
    assert "stock" in conf.get("coverage", [])
    assert "fund" in conf.get("coverage", [])
    assert "screen" not in conf.get("coverage", [])
    assert (conf.get("detect") or {}).get("type") == "env_or_file"
    os.environ[ENV_KEY] = "test-key-not-real"
    available, detail = detect(conf)
    assert available is True
    assert ENV_KEY in detail or "已配置" in detail
    assert "test-key-not-real" not in detail


def test_live_optional() -> None:
    if os.environ.get("INVEST_LIVE") != "1":
        return
    if os.environ.get(ENV_KEY) == "test-key-not-real":
        os.environ.pop(ENV_KEY, None)
    res = stock("600519")
    assert res["ok"] is True, res.get("error")
    data = res["data"]
    assert data["thscode"] == "600519.SH"
    assert data["quote"]["last"] is not None
    assert "pe_ttm" in data["valuation"]
    dumped = json.dumps(res)
    key = os.environ.get(ENV_KEY, "")
    if key:
        assert key not in dumped
    fres = fund("110011")
    assert fres["ok"] is True, fres.get("error")
    assert fres["data"]["thscode"].endswith(".OF") or fres["data"]["thscode"].endswith(".SH")


if __name__ == "__main__":
    test_request_many_injected_client_is_serial()
    test_looks_like_hk()
    test_pick_ticker_exact_and_ambiguous()
    test_parse_indicators_array_not_object()
    test_build_history_null_not_zero()
    test_stock_hk_no_http()
    test_stock_ok_mock()
    test_fund_ok_mock()
    test_fund_subrequest_failure_envelope_false()
    test_registry_hithink()
    test_live_optional()
    print("test_hithink: OK")
