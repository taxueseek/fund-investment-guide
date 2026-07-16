"""Shared utilities for invest-cli (and investment-agent consumers).

Design goals:
- No hardcoded personal machine paths (env + sibling + common skills roots)
- Stable JSON contract: every subcommand exposes a flat ``data`` dict
- Scripts runnable from any cwd
- This module is data-adapter glue only; analysis frameworks live in invest-* skills
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def ensure_script_dir_on_path() -> Path:
    """Make sibling modules importable regardless of process cwd."""
    script_dir = Path(__file__).resolve().parent
    s = str(script_dir)
    if s not in sys.path:
        sys.path.insert(0, s)
    return script_dir


def skill_root() -> Path:
    """invest-cli skill root: .../invest-cli (parent of scripts/)."""
    return Path(__file__).resolve().parent.parent


def find_invest_cli() -> Path:
    """Locate invest_cli.py without hardcoding a home path.

    Priority:
      1. INVEST_CLI / INVEST_CLI_ROOT env
      2. Sibling install: investment-agent/../invest-cli/scripts/...
      3. Common skill install roots under $HOME
    """
    env_file = os.environ.get("INVEST_CLI")
    if env_file:
        p = Path(env_file).expanduser()
        if p.is_file():
            return p

    env_root = os.environ.get("INVEST_CLI_ROOT")
    if env_root:
        p = Path(env_root).expanduser() / "scripts" / "invest_cli.py"
        if p.is_file():
            return p

    # Sibling layout: <skills>/investment-agent → <skills>/invest-cli
    here = Path(__file__).resolve()
    # If called from invest-cli/scripts/_common.py
    candidate = skill_root() / "scripts" / "invest_cli.py"
    if candidate.is_file():
        return candidate

    # If imported after path injection from investment-agent, walk up
    for parent in here.parents:
        c = parent / "invest-cli" / "scripts" / "invest_cli.py"
        if c.is_file():
            return c

    home = Path.home()
    for base in (
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".grok" / "skills",
        home / ".codex" / "skills",
    ):
        c = base / "invest-cli" / "scripts" / "invest_cli.py"
        if c.is_file():
            return c

    raise FileNotFoundError(
        "invest_cli.py not found. Set INVEST_CLI or INVEST_CLI_ROOT, "
        "or install invest-cli under a standard skills directory."
    )


def json_out(data: Any, *, indent: bool = True) -> str:
    opts: dict[str, Any] = {"ensure_ascii": False}
    if indent:
        opts["indent"] = 2
    return json.dumps(data, **opts)


def eastmoney_ensure_ok(raw: dict, *, context: str = "") -> None:
    """Raise a clear error when Eastmoney returns business failure.

    One-line class fix: never treat rate-limit / dormant account as empty tables.
    """
    if not isinstance(raw, dict):
        raise RuntimeError(f"东财 API 返回非 JSON 对象{context}")
    if raw.get("success") is False or raw.get("data") is None:
        msg = raw.get("message") or raw.get("msg") or str(raw.get("code", "unknown"))
        raise RuntimeError(f"东财 API 失败{context}: {msg}")


def parse_eastmoney_tables(raw: dict) -> list[dict]:
    """Parse Eastmoney claw API table payload → list of flat row dicts."""
    eastmoney_ensure_ok(raw)
    try:
        dtos = raw["data"]["data"]["searchDataResultDTO"]["dataTableDTOList"]
    except (KeyError, TypeError):
        return []

    results: list[dict] = []
    for item in dtos:
        name_map = item.get("nameMap", {})
        table = item.get("table", {})
        row: dict[str, Any] = {"entityName": item.get("entityName", "")}
        for col_id, col_name in name_map.items():
            if col_id in table:
                vals = table[col_id]
                if isinstance(vals, list) and len(vals) > 0:
                    row[col_name] = vals[0]
        if len(row) > 1:
            results.append(row)
    return results


def strip_paren_suffix(name: str) -> str:
    """Strip trailing date/unit parentheses: '最新价(元)(2026.05.22)' → '最新价'."""
    import re

    return re.sub(r"\(.*?\)", "", name).strip()


def pick_screen_columns(all_keys: list[str], limit: int = 6) -> list[str]:
    """Pick display columns without hardcoding dated header strings."""
    priority_stems = ("代码", "名称", "最新价", "涨跌幅", "市盈率", "市净率", "总市值")
    picked: list[str] = []
    for stem in priority_stems:
        for k in all_keys:
            if k in picked:
                continue
            if stem in k or strip_paren_suffix(k).startswith(stem):
                picked.append(k)
                break
        if len(picked) >= limit:
            return picked[:limit]
    if not picked:
        return all_keys[:limit]
    return picked[:limit]
