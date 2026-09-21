#!/usr/bin/env python3
"""SEC EDGAR 适配器回归测试 — 默认不联网（fixture 驱动）；末尾一条联网冒烟。

背景：XBRL 标签会漂移（Apple 的 Revenues 标签停在 2018 财年），
且同一标签下混有季度值。抽取逻辑必须：优先新标签、只取年跨度、时点型取 10-K/FY。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sources.sec_edgar as sec  # noqa: E402


def _facts_fixture() -> dict:
    """含标签漂移 + 季度噪音 + 时点/时长混合的最小 companyfacts。"""
    return {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"start": "2017-10-01", "end": "2018-09-29", "val": 265595000000,
                             "fy": 2018, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "units": {
                        "USD": [
                            {"start": "2024-09-29", "end": "2025-09-27", "val": 416161000000,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                            # 季度噪音：同 form/fp 但跨度 90 天，必须被拒
                            {"start": "2025-06-29", "end": "2025-09-27", "val": 102466000000,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"start": "2024-09-29", "end": "2025-09-27", "val": 112010000000,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {"start": "2024-09-29", "end": "2025-09-27", "val": 7.39,
                             "fy": 2025, "fp": "FY", "form": "10-K"},
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {"end": "2025-09-27", "val": 359241000000, "fy": 2025, "fp": "FY", "form": "10-K"},
                            {"end": "2025-06-28", "val": 331495000000, "fy": 2025, "fp": "Q3", "form": "10-Q"},
                        ]
                    }
                },
            }
        }
    }


def test_extract_prefers_new_tag_and_annual_period() -> None:
    m = sec.extract_annual(_facts_fixture())
    assert m["revenue"]["tag"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert m["revenue"]["value"] == 416161000000  # 不是 2018 旧标签，也不是季度值
    assert m["revenue"]["end"] == "2025-09-27"
    assert m["net_income"]["value"] == 112010000000
    assert m["eps_diluted"]["unit"] == "USD/shares"
    assert m["assets"]["value"] == 359241000000  # 时点型取 10-K/FY，不取 10-Q


def test_cik_padding_and_ticker_norm() -> None:
    assert sec._cik10(320193) == "0000320193"
    assert sec._cik10("0000320193") == "0000320193"
    assert sec._norm_ticker("brk.b") == "BRK-B"
    idx = sec._ticker_index(
        {"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"}}
    )
    assert idx["BRK-B"]["cik_str"] == 1067983
    assert idx["BRK.B"]["cik_str"] == 1067983  # 点号写法也命中


def test_quarterly_and_foreign_forms_rejected() -> None:
    rows = sec._annual_rows(
        [{"start": "2025-06-29", "end": "2025-09-27", "val": 1, "form": "10-K", "fp": "FY"}]
    )
    assert rows == []
    rows = sec._annual_rows(
        [{"start": "2024-09-29", "end": "2025-09-27", "val": 1, "form": "20-F", "fp": "FY"}]
    )
    assert rows == []


def test_error_envelope_without_network() -> None:
    def _boom(ticker: str):
        raise RuntimeError("SEC 未收录该 ticker: XXX（仅美股发行人）")

    orig = sec.resolve_cik
    sec.resolve_cik = _boom  # type: ignore[assignment]
    try:
        res = sec.fundamentals("XXX")
        assert res["ok"] is False and res["data"] is None
        assert "未收录" in (res["error"] or "")
        assert res["source"] == "sec_edgar"
    finally:
        sec.resolve_cik = orig  # type: ignore[assignment]


def test_fundamentals_live_smoke() -> None:
    """联网冒烟：网络不可用/被限流时跳过；解析类错误必须暴露。"""
    try:
        res = sec.fundamentals("AAPL")
    except Exception:
        return
    if not res.get("ok"):
        err = (res.get("error") or "").lower()
        if "请求失败" in (res.get("error") or "") or "timeout" in err or "超时" in err:
            return
        raise AssertionError(res.get("error"))
    m = res["data"]["metrics"]
    assert m["revenue"]["value"] > 0
    assert m["assets"]["value"] > 0


if __name__ == "__main__":
    test_extract_prefers_new_tag_and_annual_period()
    test_cik_padding_and_ticker_norm()
    test_quarterly_and_foreign_forms_rejected()
    test_error_envelope_without_network()
    test_fundamentals_live_smoke()
    print("test_sec_edgar: OK")
