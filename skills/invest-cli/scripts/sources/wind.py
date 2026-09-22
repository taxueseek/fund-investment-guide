"""万得 Wind 数据源适配器（直连 MCP，不依赖 wind-mcp-skill 的 node CLI）。

取数路径：MCP JSON-RPC over HTTP（POST，`initialize` → `tools/call`），
认证用 `Authorization: Bearer <WIND_API_KEY>`（官方同一套，不新造）。
Key 顺序与官方一致：`~/.wind-aifinmarket/config` > skill config.json > 环境变量。

旧实现每次调用起一个 node 子进程（node CLI 冷启动 + 每次重新 initialize），
这里省掉这两段固定开销。

返回值契约不变：{source, ok, data, error}；data 为 MCP 结果解析后的业务 JSON。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

CALL_TIMEOUT = 60
SOURCE = "wind"
SKILL_VERSION = "2.0.4"
GLOBAL_CONFIG = Path.home() / ".wind-aifinmarket" / "config"

# server_type → MCP 端点（与 wind-mcp-skill 的 registry 一致；不读 skill 目录）
_ENDPOINTS = {
    "stock_data": "https://mcp.wind.com.cn/vserver_stock_data/mcp/",
    "fund_data": "https://mcp.wind.com.cn/vserver_fund_data/mcp/",
    "index_data": "https://mcp.wind.com.cn/vserver_index_data/mcp/",
    "bond_data": "https://mcp.wind.com.cn/vserver_bond_data/mcp/",
    "financial_docs": "https://mcp.wind.com.cn/vserver_financial_docs/mcp/",
    "economic_data": "https://mcp.wind.com.cn/vserver_economic_data/mcp/",
    "analytics_data": "https://mcp.wind.com.cn/vserver_analytics_data/mcp/",
}


def _read_key_from_file(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, val = line.split("=", 1)
        if name.strip() == "WIND_API_KEY":
            return val.strip().strip('"').strip("'")
    return ""


def _api_key() -> str:
    """用户全局配置 > skill 本地 config.json > 环境变量（与官方顺序一致）。"""
    key = _read_key_from_file(GLOBAL_CONFIG)
    if key:
        return key
    skill_dir = os.environ.get("WIND_SKILL_DIR", "").strip()
    if skill_dir:
        try:
            cfg = json.loads((Path(skill_dir).expanduser() / "config.json").read_text(encoding="utf-8"))
            if isinstance(cfg, dict) and isinstance(cfg.get("wind_api_key"), str):
                return cfg["wind_api_key"].strip()
        except (OSError, json.JSONDecodeError):
            pass
    # 最后一道回退同样走 read_env（进程环境 → launchctl → shell rc），
    # 只读 os.environ 会重演 hithink.detect 的漂移：用户把 key 配在 rc 文件里，
    # load/可用性两边结论不一致，源被静默丢掉。
    from .env import read_env

    return read_env("WIND_API_KEY")


def detect() -> tuple[bool, str]:
    if _api_key():
        return True, "WIND_API_KEY 已配置"
    return False, f"缺少 WIND_API_KEY（{GLOBAL_CONFIG} 或环境变量）"


def parse_wind_receipt(stdout: str) -> tuple[bool, Any, str]:
    """解析 MCP 回执，返回 (ok, data, error)。保留原契约供调用方复用。"""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        return False, None, f"Wind 回执非 JSON: {e}"
    if isinstance(envelope, dict) and envelope.get("isError"):
        return False, None, str(envelope.get("cli_meta", envelope))
    text = ""
    content = envelope.get("content") if isinstance(envelope, dict) else None
    if isinstance(content, list) and content and isinstance(content[0], dict):
        text = content[0].get("text", "")
    if not text and isinstance(envelope, dict):
        text = envelope.get("message", "") or json.dumps(envelope, ensure_ascii=False)
    if text:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("error"):
                return False, None, f"Wind 返回错误: {parsed['error']}"
            return True, parsed, ""
        except (json.JSONDecodeError, TypeError):
            return True, text, ""
    return False, None, "Wind 回执缺少内容"


def _parse_sse(text: str) -> dict[str, Any]:
    """MCP 响应：后端正常走 SSE，部分错误场景纯 JSON。"""
    trimmed = text.strip()
    if trimmed.startswith("{"):
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError:
            pass
    last = ""
    for line in text.splitlines():
        if line.startswith("data: "):
            last = line[6:]
    if last:
        return json.loads(last)
    raise RuntimeError(f"Wind 响应格式无法识别: {text[:200]}")


def _rpc(endpoint: str, api_key: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
        payload = _parse_sse(resp.read().decode("utf-8", errors="replace"))
    if not isinstance(payload, dict):
        raise RuntimeError("Wind 响应不是 JSON-RPC 对象")
    if payload.get("error"):
        err = payload["error"]
        msg = err if isinstance(err, str) else (err.get("message") or json.dumps(err, ensure_ascii=False))
        raise RuntimeError(f"Wind 接口错误: {msg}")
    return payload.get("result") or {}


def call(
    server_type: str,
    tool_name: str,
    params: Optional[dict] = None,
    params_json: Optional[str] = None,
) -> dict:
    """直连 Wind MCP 调一个契约工具。参数原样透传，不改字段名。"""
    endpoint = _ENDPOINTS.get(server_type)
    if not endpoint:
        return {"source": SOURCE, "ok": False, "data": None,
                "error": f"未知 server_type: {server_type}（可选: {'/'.join(_ENDPOINTS)}）"}
    api_key = _api_key()
    if not api_key:
        return {"source": SOURCE, "ok": False, "data": None, "error": "WIND_API_KEY 未配置"}
    if params_json is not None:
        try:
            params = json.loads(params_json) if params_json.strip() else {}
        except json.JSONDecodeError as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": f"--input 不是合法 JSON: {e}"}
    call_params = {
        "name": tool_name,
        "arguments": params or {},
        "_meta": {"clientVersion": SKILL_VERSION},
    }
    init_params = {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "invest-cli", "version": SKILL_VERSION},
    }
    try:
        # Wind 当前是无状态 MCP，tools/call 直接可用（实测省一次往返）。
        # 若上游以后要求先握手，_rpc 会抛协议/HTTP 错，下面补一次 initialize 重试。
        result = _rpc(endpoint, api_key, "tools/call", call_params)
    except RuntimeError:
        try:
            _rpc(endpoint, api_key, "initialize", init_params)
            result = _rpc(endpoint, api_key, "tools/call", call_params)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
            return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind HTTP {e.code}: {detail}"}
        except (urllib.error.URLError, OSError) as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind 网络失败: {e}"}
        except RuntimeError as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": str(e)}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200] if e.fp else ""
        return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind HTTP {e.code}: {detail}"}
    except (urllib.error.URLError, OSError) as e:
        return {"source": SOURCE, "ok": False, "data": None, "error": f"Wind 网络失败: {e}"}
    ok, data, err = parse_wind_receipt(json.dumps(result, ensure_ascii=False))
    return {"source": SOURCE, "ok": ok, "data": data, "error": err or None}
