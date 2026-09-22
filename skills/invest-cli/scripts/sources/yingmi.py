"""盈米且慢数据源适配器（直连 OpenAPI，不依赖 yingmi-skill-cli）。

取数路径：
  1. 读 apiKey（`~/.yingmi-skill-cli/config.json`，官方 CLI 的凭据位置）；
  2. 取一次 OpenAPI 文档（`GET /api/docs.json`，磁盘缓存 6h）——操作名、方法、
     路径、参数位置全以这份文档为准，不在本地维护第二份清单；
  3. 按 operationId 找到操作，把入参按 path/query/header/body 拆开后直接 HTTP 调用。

认证：`Authorization: Bearer <apiKey>`（官方同一套，不新造）。
旧实现每次调用起一个 node 子进程（`yingmi-skill-cli mcp call`，含 node 冷启动
+ 每次都重新拉 OpenAPI 文档），这里省掉这两段固定开销。

返回值与原实现保持同一契约：{source, ok, data, error}，业务信封/数组/业务对象原样还原。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

CONFIG_FILE = Path.home() / ".yingmi-skill-cli" / "config.json"
STARGATE_BASE = "https://stargate.yingmi.com"
DOCS_TTL = 6 * 3600.0
CALL_TIMEOUT = 30
SOURCE = "yingmi"
_HTTP_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
_HIDDEN = {"getSkillByName"}
_MISSING = object()


def _api_key() -> str:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    key = cfg.get("apiKey")
    return key.strip() if isinstance(key, str) else ""


def detect() -> tuple[bool, str]:
    """可用性 = 有 apiKey（不看 CLI 在不在 PATH）。"""
    if _api_key():
        return True, "已配置 apiKey"
    return False, f"缺少盈米 apiKey（{CONFIG_FILE}）"


def _docs_url() -> str:
    return f"{STARGATE_BASE}/api/docs.json"


def _fetch_doc(api_key: str) -> dict[str, Any]:
    url = _docs_url() + "?" + urllib.parse.urlencode({"apiKey": api_key})
    req = urllib.request.Request(url, headers={"x-request-id": uuid.uuid4().hex})
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def openapi() -> dict[str, Any]:
    """OpenAPI 文档（磁盘缓存 6h）；拿不到时抛 RuntimeError。"""
    key = _api_key()
    if not key:
        raise RuntimeError(f"缺少盈米 apiKey（{CONFIG_FILE}）")
    try:
        from _common import cache_get, cache_set

        hit = cache_get("yingmi", "openapi", DOCS_TTL)
        if isinstance(hit, dict) and hit.get("paths"):
            return hit
    except Exception:
        pass
    try:
        doc = _fetch_doc(key)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise RuntimeError(f"盈米 OpenAPI 文档获取失败: {e}") from e
    try:
        from _common import cache_set

        cache_set("yingmi", "openapi", doc)
    except Exception:
        pass
    return doc


def _operations(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{operationId: {method, path, parameters, has_body}}（path 级参数并入）。"""
    out: dict[str, dict[str, Any]] = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        shared = item.get("parameters") or []
        for method in _HTTP_METHODS:
            op = item.get(method)
            if not isinstance(op, dict) or not op.get("operationId"):
                continue
            name = op["operationId"]
            if name in _HIDDEN:
                continue
            out[name] = {
                "method": method.upper(),
                "path": path,
                "parameters": [*shared, *(op.get("parameters") or [])],
                "has_body": bool(op.get("requestBody")),
            }
    return out


def list_tools() -> list[dict[str, str]]:
    """给 capabilities 用：全部操作名 + 摘要（来自 OpenAPI，不留本地副本）。"""
    doc = openapi()
    rows: list[dict[str, str]] = []
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method in _HTTP_METHODS:
            op = item.get(method)
            if isinstance(op, dict) and op.get("operationId") and op["operationId"] not in _HIDDEN:
                rows.append({
                    "name": op["operationId"],
                    "description": (op.get("summary") or op.get("description") or "").strip(),
                })
    return rows


def _by_location(parameters: list[dict], location: str) -> list[dict]:
    return [p for p in parameters if isinstance(p, dict) and p.get("in") == location]


def _split(operation: dict[str, Any], raw: Any) -> tuple[dict, dict, dict, Any]:
    """把入参拆成 (path, query, header, body)——与官方 CLI 的 splitInput 同规则。"""
    params = operation["parameters"]
    path_p = _by_location(params, "path")
    query_p = _by_location(params, "query")
    header_p = _by_location(params, "header")

    if not isinstance(raw, dict):
        if operation["has_body"] and not params:
            return {}, {}, {}, raw
        raise RuntimeError("调用输入必须是 JSON 对象")

    reserved = {"path", "query", "header", "body"}
    path_v = {p["name"]: raw.get(p["name"]) for p in path_p if p["name"] in raw}
    path_v.update(raw.get("path") if isinstance(raw.get("path"), dict) else {})
    query_v = {p["name"]: raw.get(p["name"]) for p in query_p if p["name"] in raw}
    query_v.update(raw.get("query") if isinstance(raw.get("query"), dict) else {})
    header_v = {p["name"]: raw.get(p["name"]) for p in header_p if p["name"] in raw}
    header_v.update(raw.get("header") if isinstance(raw.get("header"), dict) else {})

    explicit = raw.get("body", _MISSING)
    param_names = {p.get("name") for p in params}
    remaining = {k: v for k, v in raw.items() if k not in reserved and k not in param_names}

    body: Any = None if explicit is _MISSING else explicit
    if explicit is _MISSING and operation["has_body"]:
        if not params:
            body = raw
        elif remaining:
            body = remaining
    return path_v, query_v, header_v, body


def _request(operation: dict[str, Any], base: str, path_v: dict, query_v: dict,
             header_v: dict, body: Any, api_key: str) -> Any:
    path = operation["path"]
    for key, value in path_v.items():
        if value is not None:
            path = path.replace("{" + key + "}", urllib.parse.quote(str(value), safe=""))
    url = base.rstrip("/") + path
    clean_query = {k: v for k, v in query_v.items() if v is not None}
    if clean_query:
        url += "?" + urllib.parse.urlencode(clean_query)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "x-request-id": uuid.uuid4().hex,
        **{k: str(v) for k, v in header_v.items() if v is not None},
    }
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=operation["method"])
    with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text


def _wrap(parsed: Any) -> dict[str, Any]:
    """业务信封/数组/业务对象 → 统一信封（与原 CLI 版本的还原规则一致）。"""
    if isinstance(parsed, list):
        return {"source": SOURCE, "ok": True, "data": parsed, "error": None}
    if isinstance(parsed, dict):
        if parsed.get("success") is True:
            return {"source": SOURCE, "ok": True, "data": parsed.get("data"), "error": None}
        if parsed.get("success") is False:
            msg = parsed.get("message") or parsed.get("error") or parsed
            return {"source": SOURCE, "ok": False, "data": None, "error": f"盈米调用失败: {msg}"}
        return {"source": SOURCE, "ok": True, "data": parsed, "error": None}
    return {"source": SOURCE, "ok": True, "data": parsed, "error": None}


def call(tool_name: str, params: Optional[dict] = None, params_json: Optional[str] = None) -> dict:
    """按 operationId 直接调用盈米 OpenAPI。"""
    api_key = _api_key()
    if not api_key:
        return {"source": SOURCE, "ok": False, "data": None,
                "error": f"缺少盈米 apiKey（{CONFIG_FILE}）"}
    raw = params
    if params_json is not None:
        try:
            raw = json.loads(params_json) if params_json.strip() else {}
        except json.JSONDecodeError as e:
            return {"source": SOURCE, "ok": False, "data": None, "error": f"--input 不是合法 JSON: {e}"}
    try:
        doc = openapi()
        operation = _operations(doc).get(tool_name)
        if operation is None:
            return {"source": SOURCE, "ok": False, "data": None, "error": f"Tool not found: {tool_name}"}
        base = (doc.get("servers") or [{}])[0].get("url") or f"{STARGATE_BASE}/api"
        path_v, query_v, header_v, body = _split(operation, raw or {})
        parsed = _request(operation, base, path_v, query_v, header_v, body, api_key)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return {"source": SOURCE, "ok": False, "data": None,
                "error": f"盈米调用失败 HTTP {e.code}: {body_text[:200]}"}
    except urllib.error.URLError as e:
        return {"source": SOURCE, "ok": False, "data": None, "error": f"盈米网络失败: {e}"}
    except RuntimeError as e:
        return {"source": SOURCE, "ok": False, "data": None, "error": str(e)}
    return _wrap(parsed)
