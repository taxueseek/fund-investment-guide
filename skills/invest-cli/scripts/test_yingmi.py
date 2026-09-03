#!/usr/bin/env python3
"""盈米且慢适配器的离线契约测试 — 不联网。

守护 2026-09-03 实测发现的 bug：适配器 call() 只认 `{` 开头，
GetPopularFund 等批量/列表工具直返 JSON 数组（[{...}]）被误判
"未返回结构化数据"。本测试模拟官方 CLI 的 5 种 stdout 形态。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from sources import yingmi


class _FakeProc:
    def __init__(self, stdout: str, stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _call_with(stdout: str, monkeypatch, **kw) -> dict:
    monkeypatch.setattr(yingmi.subprocess, "run", lambda *a, **k: _FakeProc(stdout, **kw))
    return yingmi.call("WhateverTool", params={})


def test_array_return_ok(monkeypatch) -> None:
    """数组直返（GetPopularFund 形态）→ ok=True，data 为原数组。"""
    arr = [{"fundCode": "001938", "rank": 1}, {"fundCode": "163406", "rank": 2}]
    res = _call_with(json.dumps(arr, ensure_ascii=False), monkeypatch)
    assert res["ok"] is True
    assert isinstance(res["data"], list) and len(res["data"]) == 2
    assert res["data"][0]["fundCode"] == "001938"


def test_success_envelope(monkeypatch) -> None:
    """标准信封 {"success": true, "data": {...}} → 取 data。"""
    res = _call_with(json.dumps({"success": True, "data": {"name": "中欧时代先锋"}}, ensure_ascii=False), monkeypatch)
    assert res["ok"] is True
    assert res["data"]["name"] == "中欧时代先锋"


def test_success_envelope_with_array_data(monkeypatch) -> None:
    """信封内 data 为数组（部分工具包装批量返回）→ ok。"""
    res = _call_with(json.dumps({"success": True, "data": [{"a": 1}]}, ensure_ascii=False), monkeypatch)
    assert res["ok"] is True
    assert isinstance(res["data"], list)


def test_failure_envelope(monkeypatch) -> None:
    """{"success": false, "message": ...} → ok=False 且带 message。"""
    res = _call_with(json.dumps({"success": False, "message": "基金不存在"}, ensure_ascii=False), monkeypatch)
    assert res["ok"] is False
    assert "基金不存在" in res["error"]


def test_bare_business_object(monkeypatch) -> None:
    """无 success 字段的业务对象（GetFundDiagnosis 形态）→ ok=True 原样返回。"""
    biz = {"fundCode": "001938", "riskScore": 5}
    res = _call_with(json.dumps(biz, ensure_ascii=False), monkeypatch)
    assert res["ok"] is True
    assert res["data"]["riskScore"] == 5


def test_nonzero_exit_text_error(monkeypatch) -> None:
    """退出码非 0 且 stdout/stderr 为文本 → ok=False 带错误文本。"""
    res = _call_with("", monkeypatch, stderr="boom", returncode=1)
    assert res["ok"] is False
    assert "boom" in res["error"]


def test_zero_exit_no_json(monkeypatch) -> None:
    """退出码 0 但无有效 JSON → ok=False 明示未返回结构化数据。"""
    res = _call_with("done, nothing here", monkeypatch)
    assert res["ok"] is False
    assert "未返回结构化数据" in res["error"]
