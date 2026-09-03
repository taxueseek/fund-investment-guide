"""东方财富数据源适配器。

复用 scripts/ 下现有 cmd_stock / cmd_fund 的取数实现，保持 JSON 契约一致。
东财=天天（同一家），本适配器只负责东财；天天官方能力走 ttskill 源（sources/ttskill.py）。

key 读取：环境变量 EASTMONEY_APIKEY 或用户级凭据文件（env_or_file，见 data-sources.yaml）。
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from typing import Any

# 让 scripts/ 下的 cmd_* 模块可导入（无论进程 cwd）
_SCRIPTS = str(Path(__file__).resolve().parent.parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

ENV_KEY = "EASTMONEY_APIKEY"


def credential_files() -> list[Path]:
    cands = [
        Path.home() / ".config" / "invest-cli" / "eastmoney.env",
        Path.home() / "Library" / "Application Support" / "invest-cli" / "eastmoney.env",
    ]
    return [p for p in cands if p.is_file()]


def load_api_key() -> str:
    """进程环境/launchctl/shell rc 优先（统一识别器），无则读用户级凭据文件。"""
    from .env import read_env

    val = read_env(ENV_KEY)
    if val:
        return val
    for p in credential_files():
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{ENV_KEY}="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return os.environ.get(ENV_KEY, "")


# 可用性探测统一走 data-sources.yaml（type: env_or_file / EASTMONEY_APIKEY），见 sources/registry.py
# 注意：不再在此维护模块级 detect()——registry 的 env_or_file 探测会调用适配器 detect，
# 但本模块刻意不提供：KEY 文件按 registry 的 files 列表声明，多实现必漂移。


def _wrap(kind: str, snap: Any) -> dict:
    if not isinstance(snap, dict):
        return {"source": "eastmoney", "kind": kind, "ok": False, "data": None,
                "error": "东财返回非对象"}
    payload = snap.get("data")
    if not payload:
        return {"source": "eastmoney", "kind": kind, "ok": False, "data": None,
                "error": f"东财{kind}为空"}
    return {"source": "eastmoney", "kind": kind, "ok": True, "data": snap, "error": None}


def stock(keyword: str) -> dict:
    from cmd_stock import resolve_code, fetch_stock_data

    try:
        snap = fetch_stock_data(resolve_code(keyword))
    except Exception as e:
        return {"source": "eastmoney", "kind": "stock", "ok": False, "data": None, "error": str(e)}
    return _wrap("stock", snap)


def fund(keyword: str) -> dict:
    from cmd_fund import resolve_fund_code, fetch_fund_data

    try:
        snap = fetch_fund_data(resolve_fund_code(keyword))
    except Exception as e:
        return {"source": "eastmoney", "kind": "fund", "ok": False, "data": None, "error": str(e)}
    return _wrap("fund", snap)


def screen(condition: str, page_size: int = 20) -> dict:
    import requests

    api_key = load_api_key()
    if not api_key:
        return {"source": "eastmoney", "kind": "screen", "ok": False, "data": None,
                "error": "未设置 EASTMONEY_APIKEY（env 或 ~/.config/invest-cli/eastmoney.env）"}
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/stock-screen"
    try:
        resp = requests.post(
            url,
            headers={"apikey": api_key, "Content-Type": "application/json"},
            json={"keyword": condition, "pageNo": 1, "pageSize": page_size},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"source": "eastmoney", "kind": "screen", "ok": False, "data": None, "error": f"东财选股失败: {e}"}
    return {"source": "eastmoney", "kind": "screen", "ok": True, "data": resp.json(), "error": None}
