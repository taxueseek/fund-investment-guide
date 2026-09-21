"""watchlist 子命令：本地自选股（自含，不依赖东财账户）。

存储：<state_root>/watchlist.json（本地，无版权问题）。
    state_root() 由 _common 统一决定（可用 INVEST_CLI_STATE_DIR 覆盖）——
    这是**用户数据**而非缓存，不能落在会被系统清理的 ~/Library/Caches 下，
    也不该让本模块自己再记一份路径规则。
    旧位置 ~/.cache/invest-cli/watchlist.json 仍会被读一次并自动迁移。
行情预览：走 route.fetch（A 股/基金快照链），按 --type 选 stock 或 fund。

用法:
    invest-cli watchlist add <code> [--name N] [--type fund|stock]
    invest-cli watchlist remove <code>
    invest-cli watchlist list [--with-quote] [--json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _common import state_root

# 2026-09 前的落点（缓存目录下），仅用于一次性迁移
_LEGACY_FILE = Path.home() / ".cache" / "invest-cli" / "watchlist.json"


def watch_file() -> Path:
    return state_root() / "watchlist.json"


def _migrate_legacy() -> None:
    """把 2026-09 前落在缓存目录下的自选股搬到 state_root（旧文件保留不删）。"""
    if watch_file().is_file() or not _LEGACY_FILE.is_file():
        return
    try:
        data = json.loads(_LEGACY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if isinstance(data, list) and data:
        _save(data)


def _load() -> list[dict]:
    _migrate_legacy()
    path = watch_file()
    if not path.is_file():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(items: list[dict]) -> None:
    path = watch_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add(code: str, name: str = "", typ: str = "") -> dict:
    items = _load()
    code = code.strip()
    if any(i.get("code") == code for i in items):
        return {"source": "watchlist", "ok": False, "data": None, "error": f"{code} 已在自选" }
    items.append({"code": code, "name": name, "type": typ})
    _save(items)
    return {"source": "watchlist", "ok": True, "data": {"code": code, "added": True}, "error": None}


def remove(code: str) -> dict:
    items = _load()
    new = [i for i in items if i.get("code") != code.strip()]
    if len(new) == len(items):
        return {"source": "watchlist", "ok": False, "data": None, "error": f"{code} 不在自选" }
    _save(new)
    return {"source": "watchlist", "ok": True, "data": {"code": code, "removed": True}, "error": None}


def _quote(code: str, typ: str = "") -> str:
    try:
        from sources.route import fetch

        kind = "fund" if (typ or "").lower() == "fund" else "stock"
        market = None
        if kind == "stock":
            market = "hk" if len((code or "").strip()) == 5 else "a"
        r = fetch(kind, code, market=market)
        if r.get("ok"):
            d = r.get("data") or {}
            inner = d.get("data") if isinstance(d.get("data"), dict) else {}
            last = (
                (d.get("quote") or {}).get("last")
                or inner.get("单位净值")
                or inner.get("最新价")
                or inner.get("收盘价")
                or ""
            )
            return f"{d.get('name', code)} {last}".strip()
    except Exception:
        pass
    return code


def run(action: str, code: str = "", name: str = "", typ: str = "",
        with_quote: bool = False, as_json: bool = False) -> int:
    if action == "add":
        out = add(code, name, typ)
    elif action == "remove":
        out = remove(code)
    elif action == "list":
        items = _load()
        rows = []
        for it in items:
            row = {"code": it.get("code"), "name": it.get("name", ""), "type": it.get("type", "")}
            if with_quote:
                row["quote"] = _quote(it.get("code", ""), it.get("type", ""))
            rows.append(row)
        out = {"source": "watchlist", "ok": True, "data": {"items": rows}, "error": None}
    else:
        print("用法: invest-cli watchlist <add|remove|list> ...", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if not out.get("ok"):
            print(f"watchlist: {out.get('error')}", file=sys.stderr)
            return 1
        if action == "list":
            items = out["data"].get("items", [])
            if not items:
                print("自选列表为空")
            else:
                print("自选股:")
                for it in items:
                    print(f"  {it.get('code')}  {it.get('name', '')}  {it.get('type','')}  {it.get('quote','')}")
        else:
            print(out["data"])
    return 0
