"""天天基金（ttfund CLI）数据源适配器（场景引擎）。

ttfund 是场景化 CLI（v1.4），覆盖 diagnose/pick/allocate/gold/bond/macro/
research 等场景，是 invest 系列在债券/黄金/宏观/配置等领域的场景引擎。
与东方财富同源但场景更专；本适配器负责探测与透传。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any, Optional

CLI = "ttfund"
CALL_TIMEOUT = 60
DETECT_TIMEOUT = 10


def detect() -> tuple[bool, str]:
    from .registry import _probe_command

    return _probe_command([CLI, "status"], "")


def login_ok() -> tuple[bool, str]:
    """检查 ttfund 是否已登录（场景调用前提）。"""
    if shutil.which(CLI) is None:
        return False, "ttfund 未安装"
    try:
        proc = subprocess.run([CLI, "status"], capture_output=True, text=True, timeout=DETECT_TIMEOUT)
    except Exception as e:
        return False, f"ttfund status 失败: {e}"
    text = (proc.stdout or "") + (proc.stderr or "")
    if "未登录" in text:
        return False, "ttfund 未登录，执行 ttfund login"
    return True, "ttfund 已登录"


def raw_call(args: list[str], *, timeout: int = CALL_TIMEOUT) -> dict:
    """透传 ttfund 子命令。args 为实际参数（不含 CLI 自身）。"""
    if shutil.which(CLI) is None:
        return {"source": "ttfund", "ok": False, "data": None, "error": f"{CLI} 未安装"}
    cmd = [CLI] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"source": "ttfund", "ok": False, "data": None, "error": "ttfund 超时"}
    except OSError as e:
        return {"source": "ttfund", "ok": False, "data": None, "error": f"ttfund 执行失败: {e}"}
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return {"source": "ttfund", "ok": False, "data": None,
                "error": f"ttfund 退出码 {proc.returncode}: {(proc.stderr or '').strip()[:200]}"}
    try:
        return {"source": "ttfund", "ok": True, "data": json.loads(raw), "error": None}
    except json.JSONDecodeError:
        return {"source": "ttfund", "ok": True, "data": raw, "error": None}
