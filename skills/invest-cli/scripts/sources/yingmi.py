"""盈米且慢（yingmi-skill-cli）数据源适配器。

封装 `yingmi-skill-cli mcp call <toolName> --input '<json>'`。
- 成功信封：stdout 为 {"success": true, "data": {...}}
- 数组直返：批量/列表类工具（GetPopularFund、Batch*、Search*）stdout 直接是 [{...}]
- 业务对象直返：部分工具（如 GetFundDiagnosis）直接返回业务 dict，无 success 字段
- 失败/无结果：stdout 或 stderr 为人类可读文本（部分业务失败返回明确文本）
- 只还原 yingmi 返回值与错误，不做业务判断。
"""
from __future__ import annotations

import json
import subprocess
from typing import Any, Optional

CLI = "yingmi-skill-cli"
CALL_TIMEOUT = 60


def detect() -> tuple[bool, str]:
    from .registry import _probe_command

    return _probe_command([CLI, "init", "status"], '"hasApiKey": true')


def call(tool_name: str, params: Optional[dict] = None, params_json: Optional[str] = None) -> dict:
    pj = params_json
    if pj is None:
        pj = json.dumps(params or {}, ensure_ascii=False)
    cmd = [CLI, "mcp", "call", tool_name]
    if pj:
        cmd += ["--input", pj]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"source": "yingmi", "ok": False, "data": None, "error": f"盈米调用超时（> {CALL_TIMEOUT}s）"}
    except OSError as e:
        return {"source": "yingmi", "ok": False, "data": None, "error": f"盈米执行失败: {e}"}

    raw = (proc.stdout or "").strip()
    err_txt = (proc.stderr or "").strip()

    # 优先尝试解析 stdout 为 JSON（信封对象 / 业务对象 / 数组直返）
    if raw.startswith(("{", "[")):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            # 批量/列表类工具（GetPopularFund、Batch*、Search*）直接返回数组
            return {"source": "yingmi", "ok": True, "data": parsed, "error": None}
        if isinstance(parsed, dict):
            if parsed.get("success") is True:
                return {"source": "yingmi", "ok": True, "data": parsed.get("data"), "error": None}
            if parsed.get("success") is False:
                msg = parsed.get("message") or parsed.get("error") or raw
                return {"source": "yingmi", "ok": False, "data": None, "error": f"盈米调用失败: {msg}"}
            # 无 success 字段：盈米部分工具直接返回业务对象（如 GetFundDiagnosis）
            return {"source": "yingmi", "ok": True, "data": parsed, "error": None}

    # 非 JSON：取退出码与文本作为错误
    detail = raw or err_txt
    if proc.returncode != 0:
        return {"source": "yingmi", "ok": False, "data": None,
                "error": f"盈米退出码 {proc.returncode}: {detail}"}
    # 退出码 0 但无有效数据：视为失败并说明
    return {"source": "yingmi", "ok": False, "data": None, "error": f"盈米未返回结构化数据: {detail[:200]}"}
