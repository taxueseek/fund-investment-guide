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
import hashlib
import time
from pathlib import Path
from typing import Any, Optional, Dict, List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed


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


# ═══ 缓存系统 ═══
_CACHE_DIR = Path.home() / ".cache" / "invest-cli"
_CACHE_TTL = 300  # 5分钟

def _get_cache_key(prefix: str, *args) -> str:
    """生成缓存键"""
    key_str = f"{prefix}:{':'.join(str(a) for a in args)}"
    return hashlib.md5(key_str.encode()).hexdigest()

def get_cached(prefix: str, *args) -> Optional[Dict]:
    """获取缓存数据"""
    cache_key = _get_cache_key(prefix, *args)
    cache_file = _CACHE_DIR / f"{cache_key}.json"
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        
        # 检查是否过期
        if time.time() - cached.get("timestamp", 0) > _CACHE_TTL:
            return None
        
        return cached.get("data")
    except (json.JSONDecodeError, IOError):
        return None

def set_cached(prefix: str, data: Any, *args) -> None:
    """设置缓存数据"""
    cache_key = _get_cache_key(prefix, *args)
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _CACHE_DIR / f"{cache_key}.json"
    
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": time.time(),
                "data": data,
                "prefix": prefix,
                "args": list(args),
            }, f, ensure_ascii=False)
    except IOError:
        pass  # 缓存写入失败不影响主流程


# ═══ 并行执行 ═══
def parallel_execute(tasks: List[Callable], max_workers: int = 3) -> List[Any]:
    """并行执行多个任务
    
    Args:
        tasks: 任务列表，每个任务是一个无参数的可调用对象
        max_workers: 最大并行数
    
    Returns:
        任务结果列表，顺序与输入一致
    """
    results = [None] * len(tasks)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_index = {executor.submit(task): i for i, task in enumerate(tasks)}
        
        # 收集结果
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                results[index] = e
    
    return results


# ═══ 东财 API 增强 ═══
def query_eastmoney_parallel(queries: List[str], api_key: str = None) -> List[Dict]:
    """并行查询东财 API
    
    Args:
        queries: 查询字符串列表
        api_key: API 密钥（如果为 None，从环境变量获取）
    
    Returns:
        查询结果列表
    """
    import requests
    
    if api_key is None:
        api_key = os.getenv("EASTMONEY_APIKEY")
        if not api_key:
            raise RuntimeError("未设置 EASTMONEY_APIKEY 环境变量")
    
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    
    def single_query(query: str) -> Dict:
        resp = requests.post(
            url,
            headers={"apikey": api_key, "Content-Type": "application/json"},
            json={"toolQuery": query},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        eastmoney_ensure_ok(raw, context=f" ({query[:20]}...)")
        return raw
    
    # 并行执行查询
    tasks = [lambda q=q: single_query(q) for q in queries]
    return parallel_execute(tasks)


def eastmoney_query_with_cache(query: str, cache_prefix: str = "em", api_key: str = None) -> Dict:
    """带缓存的东财 API 查询
    
    Args:
        query: 查询字符串
        cache_prefix: 缓存前缀
        api_key: API 密钥
    
    Returns:
        查询结果
    """
    # 尝试从缓存获取
    cached = get_cached(cache_prefix, query)
    if cached is not None:
        return cached
    
    # 执行查询
    import requests
    
    if api_key is None:
        api_key = os.getenv("EASTMONEY_APIKEY")
        if not api_key:
            raise RuntimeError("未设置 EASTMONEY_APIKEY 环境变量")
    
    url = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"
    resp = requests.post(
        url,
        headers={"apikey": api_key, "Content-Type": "application/json"},
        json={"toolQuery": query},
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()
    eastmoney_ensure_ok(raw, context=f" ({query[:20]}...)")
    
    # 缓存结果
    set_cached(cache_prefix, raw, query)
    
    return raw
