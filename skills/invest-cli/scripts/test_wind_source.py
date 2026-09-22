#!/usr/bin/env python3
"""Wind 适配器直连 MCP 的离线契约测试 — 不联网。

2026-09-21 起改为**直连 Wind MCP**（不再起 wind-mcp-skill 的 node 子进程）。
守护：认证读同一套 Key 顺序、未知 server_type/缺 Key 给明确错误、
SSE 与纯 JSON 两种响应都能解析、工具调用结果还原规则不变。
"""
from __future__ import annotations

import json
from pathlib import Path

from sources import wind


def test_adapter_does_not_shell_out() -> None:
    """直连改造的守护：适配器不得再起 node 子进程。"""
    text = Path(wind.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in text, "Wind 适配器又引入了子进程依赖"
    assert "scripts/cli.mjs" not in text, "Wind 适配器又回去调 node CLI 了"


def test_endpoints_cover_official_registry() -> None:
    """7 个 server_type 与官方 registry 一致（少了会静默不可达）。"""
    assert set(wind._ENDPOINTS) == {
        "stock_data", "fund_data", "index_data", "bond_data",
        "financial_docs", "economic_data", "analytics_data",
    }
    assert all(u.startswith("https://mcp.wind.com.cn/vserver_") for u in wind._ENDPOINTS.values())


def test_unknown_server_type_is_clear_error() -> None:
    res = wind.call("no_such_server", "whatever")
    assert res["ok"] is False
    assert "未知 server_type" in res["error"]


def test_missing_key_is_config_error(monkeypatch) -> None:
    monkeypatch.setattr(wind, "_api_key", lambda: "")
    monkeypatch.delenv("WIND_API_KEY", raising=False)
    res = wind.call("stock_data", "get_stock_price_indicators")
    assert res["ok"] is False and "WIND_API_KEY" in res["error"]


def test_parse_sse_handles_plain_json_and_sse() -> None:
    assert wind._parse_sse('{"result": {"ok": 1}}') == {"result": {"ok": 1}}
    sse = 'event: message\ndata: {"result": {"ok": 2}}\n\n'
    assert wind._parse_sse(sse) == {"result": {"ok": 2}}


def test_call_returns_parsed_content(monkeypatch) -> None:
    """MCP result 的 content[0].text 是业务 JSON → data 为该 JSON。"""
    monkeypatch.setattr(wind, "_api_key", lambda: "k")
    payload = {"data": {"columns": [{"name": "最新成交价"}], "rows": [["1297.4"]]}}

    def _fake_rpc(endpoint, api_key, method, params):
        if method == "initialize":
            return {"protocolVersion": "2025-03-26"}
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}

    monkeypatch.setattr(wind, "_rpc", _fake_rpc)
    res = wind.call("stock_data", "get_stock_price_indicators", params={"windcode": "600519.SH"})
    assert res["ok"] is True
    assert res["data"]["data"]["rows"] == [["1297.4"]]


def test_call_falls_back_to_initialize(monkeypatch) -> None:
    """上游若要求先握手：tools/call 失败后补一次 initialize 再重试（不丢能力）。"""
    monkeypatch.setattr(wind, "_api_key", lambda: "k")
    seen: list[str] = []

    def _rpc(endpoint, api_key, method, params):
        seen.append(method)
        if seen == ["tools/call"]:
            raise RuntimeError("Wind 接口错误: session not initialized")
        if method == "initialize":
            return {"protocolVersion": "2025-03-26"}
        return {"content": [{"type": "text", "text": "{\"data\": {\"ok\": true}}"}]}

    monkeypatch.setattr(wind, "_rpc", _rpc)
    res = wind.call("stock_data", "x")
    assert res["ok"] is True and res["data"]["data"]["ok"] is True
    assert seen == ["tools/call", "initialize", "tools/call"]


def test_call_reports_rpc_error(monkeypatch) -> None:
    monkeypatch.setattr(wind, "_api_key", lambda: "k")

    def _boom(endpoint, api_key, method, params):
        raise RuntimeError("Wind 接口错误: 无权限")

    monkeypatch.setattr(wind, "_rpc", _boom)
    res = wind.call("stock_data", "x")
    assert res["ok"] is False and "无权限" in res["error"]
