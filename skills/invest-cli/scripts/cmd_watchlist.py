"""watchlist 子命令：本地自选股（自含，不依赖东财账户）。

存储：~/.cache/invest-cli/watchlist.json（本地，无版权问题）
行情预览：走东财已授权接口（EASTMONEY_APIKEY），不用腾讯非公开接口。

用法:
    invest-cli watchlist add <code> [--name N] [--type fund|stock]
    invest-cli watchlist remove <code>
    invest-cli watchlist list [--with-quote] [--json]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WATCH_FILE = Path.home() / ".cache" / "invest-cli" / "watchlist.json"


def _load() -> list[dict]:
    if not WATCH_FILE.is_file():
        return []
    try:
        with open(WATCH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(items: list[dict]) -> None:
    WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(WATCH_FILE, "w", encoding="utf-8") as f:
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


def _quote(code: str) -> str:
    try:
        from sources import eastmoney
        r = eastmoney.stock(code)
        if r.get("ok"):
            d = r.get("data") or {}
            return f"{d.get('name', code)} {d.get('data', {}).get('最新价', '')}"
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
                row["quote"] = _quote(it.get("code", ""))
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
