#!/usr/bin/env python3
"""盈米且慢适配器的离线契约测试 — 不联网。

历史：2026-09-03 实测发现适配器只认 `{` 开头，GetPopularFund 等批量/列表工具
直返 JSON 数组（[{...}]）被误判「未返回结构化数据」。
2026-09-21 起改为**直连盈米 OpenAPI**（不再起 yingmi-skill-cli 子进程），
响应还原规则（信封/数组/业务对象/失败）保持不变，因此这里直接钉 `_wrap`。
"""
from __future__ import annotations

import json
import urllib.error

from sources import yingmi


def test_array_return_ok() -> None:
    """数组直返（GetPopularFund 形态）→ ok=True，data 为原数组。"""
    arr = [{"fundCode": "001938", "rank": 1}, {"fundCode": "163406", "rank": 2}]
    res = yingmi._wrap(arr)
    assert res["ok"] is True
    assert isinstance(res["data"], list) and len(res["data"]) == 2
    assert res["data"][0]["fundCode"] == "001938"


def test_success_envelope() -> None:
    """标准信封 {"success": true, "data": {...}} → 取 data。"""
    res = yingmi._wrap({"success": True, "data": {"name": "中欧时代先锋"}})
    assert res["ok"] is True
    assert res["data"]["name"] == "中欧时代先锋"


def test_success_envelope_with_array_data() -> None:
    """信封内 data 为数组（部分工具包装批量返回）→ ok。"""
    res = yingmi._wrap({"success": True, "data": [{"a": 1}]})
    assert res["ok"] is True
    assert isinstance(res["data"], list)


def test_failure_envelope() -> None:
    """{"success": false, "message": ...} → ok=False 且带 message。"""
    res = yingmi._wrap({"success": False, "message": "基金不存在"})
    assert res["ok"] is False
    assert "基金不存在" in res["error"]


def test_bare_business_object() -> None:
    """无 success 字段的业务对象（GetFundDiagnosis 形态）→ ok=True 原样返回。"""
    res = yingmi._wrap({"fundCode": "001938", "riskScore": 5})
    assert res["ok"] is True
    assert res["data"]["riskScore"] == 5


# ── 直连传输层：入参拆分 / 错误信封 / 不依赖 CLI ──

def _op(method: str, path: str, parameters=None, has_body=False) -> dict:
    return {"method": method, "path": path, "parameters": parameters or [], "has_body": has_body}


def test_split_puts_named_params_in_query_and_path() -> None:
    """GET 的具名参数进 query、路径参数进 path，其余进 body（与官方 splitInput 同规则）。"""
    op = _op("GET", "/bmdj/v1/fund/info/{fundCode}/ai-summary",
             [{"name": "fundCode", "in": "path"}])
    path_v, query_v, header_v, body = yingmi._split(op, {"fundCode": "005827"})
    assert path_v["fundCode"] == "005827"
    assert body is None and query_v == {} and header_v == {}

    op2 = _op("GET", "/fund/guess-code", [{"name": "fundNameOrCode", "in": "query"}])
    _, query_v2, _, body2 = yingmi._split(op2, {"fundNameOrCode": "易方达蓝筹精选"})
    assert query_v2["fundNameOrCode"] == "易方达蓝筹精选"
    assert body2 is None


def test_split_body_for_post_without_params() -> None:
    """POST 且无声明参数时，整个输入就是 body。"""
    _, _, _, body = yingmi._split(_op("POST", "/fund/search", has_body=True), {"keyword": "新能源"})
    assert body == {"keyword": "新能源"}


def test_split_explicit_body_wins() -> None:
    _, _, _, body = yingmi._split(_op("POST", "/x", has_body=True), {"body": {"k": 1}, "extra": 2})
    assert body == {"k": 1}


def test_call_reports_missing_tool(monkeypatch) -> None:
    monkeypatch.setattr(yingmi, "_api_key", lambda: "k")
    monkeypatch.setattr(yingmi, "openapi", lambda: {"paths": {}, "servers": [{"url": "https://x/api"}]})
    res = yingmi.call("NoSuchTool", params={})
    assert res["ok"] is False and "Tool not found" in res["error"]


def test_call_reports_http_error_as_envelope(monkeypatch) -> None:
    monkeypatch.setattr(yingmi, "_api_key", lambda: "k")
    monkeypatch.setattr(yingmi, "openapi", lambda: {
        "paths": {"/fund/guess-code": {"get": {"operationId": "GuessFundCode",
                                               "parameters": [{"name": "fundNameOrCode", "in": "query"}]}}},
        "servers": [{"url": "https://x/api"}]})

    def _boom(*a, **kw):
        raise urllib.error.HTTPError("u", 401, "unauthorized", {}, None)

    monkeypatch.setattr(yingmi, "_request", _boom)
    res = yingmi.call("GuessFundCode", params={"fundNameOrCode": "x"})
    assert res["ok"] is False and "401" in res["error"]


def test_call_without_api_key_is_config_error(monkeypatch) -> None:
    monkeypatch.setattr(yingmi, "_api_key", lambda: "")
    res = yingmi.call("GetCurrentTime", params={})
    assert res["ok"] is False
    assert "apiKey" in res["error"]


def test_adapter_does_not_shell_out() -> None:
    """直连改造的守护：适配器不得再出现 subprocess（外部 CLI 依赖）。"""
    from pathlib import Path

    text = (Path(yingmi.__file__)).read_text(encoding="utf-8")
    assert "subprocess" not in text, "盈米适配器又引入了子进程依赖"
