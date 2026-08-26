"""万得 Wind 数据源适配器。

封装 wind-mcp-skill 的 CLI（node scripts/cli.mjs call ...）。
- 调用前用 registry 统一探测（目录 + key 文件），这里 call() 只负责定位并执行。
- 返回结构保持 invest-cli 风格：dict，含 source / ok / data / error。
- 只报告 Wind 返回值与必要限制，不补常识、不补点评。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import registry

CALL_TIMEOUT = 60


def detect() -> tuple[bool, str]:
    import os

    env_dir = os.environ.get("WIND_SKILL_DIR")
    if env_dir and Path(env_dir).expanduser().is_dir():
        return True, "WIND_SKILL_DIR 已指向 wind-mcp-skill"
    from .registry import _probe_dir

    return _probe_dir("wind-mcp-skill", ["~/.wind-aifinmarket/config"])


def locate_skill_dir() -> Optional[Path]:
    env_dir = __import__("os").environ.get("WIND_SKILL_DIR")
    if env_dir:
        p = Path(env_dir).expanduser()
        if p.is_dir():
            return p
    return registry.find_skill_dir("wind-mcp-skill")


def parse_wind_receipt(stdout: str) -> tuple[bool, Any, str]:
    """解析 wind-mcp-skill CLI stdout，返回 (ok, data, error)。"""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        return False, None, f"Wind 回执非 JSON: {e}"
    if isinstance(envelope, dict) and envelope.get("isError"):
        return False, None, str(envelope.get("cli_meta", envelope))
    # 优先解析 content[0].text（多为 JSON 字符串）
    text = ""
    content = envelope.get("content") if isinstance(envelope, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text", "")
    if not text and isinstance(envelope, dict):
        text = envelope.get("message", "")
        if not text:
            text = json.dumps(envelope, ensure_ascii=False)
    # text 是 JSON 字符串则解析；否则保留原文
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("error"):
                return False, None, f"Wind 返回错误: {parsed['error']}"
            return True, parsed, ""
        except (json.JSONDecodeError, TypeError):
            return True, text, ""
    return False, None, "Wind 回执缺少内容"


def call(
    server_type: str,
    tool_name: str,
    params: Optional[dict] = None,
    params_json: Optional[str] = None,
) -> dict:
    """调用 Wind 指定契约工具。

    参数以 wind-mcp-skill 领域契约为准；这里只负责透传，不改字段名。
    """
    skill_dir = locate_skill_dir()
    if skill_dir is None:
        return {
            "source": "wind",
            "ok": False,
            "data": None,
            "error": "未找到 wind-mcp-skill 目录（用 INVEST_SKILL_ROOTS 或 WIND_SKILL_DIR 指定）",
        }
    pj = params_json
    if pj is None:
        pj = json.dumps(params or {}, ensure_ascii=False)
    cmd = ["node", "scripts/cli.mjs", "call", server_type, tool_name, pj]
    try:
        proc = subprocess.run(
            cmd, cwd=str(skill_dir), capture_output=True, text=True, timeout=CALL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return {
            "source": "wind",
            "ok": False,
            "data": None,
            "error": f"Wind 调用超时（> {CALL_TIMEOUT}s）",
        }
    except OSError as e:
        return {"source": "wind", "ok": False, "data": None, "error": f"Wind 执行失败: {e}"}
    if proc.returncode != 0:
        return {
            "source": "wind",
            "ok": False,
            "data": None,
            "error": f"Wind CLI 退出码 {proc.returncode}: {proc.stderr.strip()}",
        }
    ok, data, err = parse_wind_receipt(proc.stdout)
    return {"source": "wind", "ok": ok, "data": data, "error": err or None}
