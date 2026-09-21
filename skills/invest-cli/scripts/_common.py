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
from typing import Any, Optional


def secret_from_file(name: str) -> str:
    """环境变量缺失时的回退：从 ~/.env.secrets 读

    为什么需要这个回退：密钥不再全局 export 到进程环境——AI agent 会把 env
    快照写进会话日志，实测密钥因此扩散到 120 处（.pi 会话日志 65、shell 快照 38…）。
    改成「工具自己需要时才读文件」，扩散面就结构性消失了。

    与 ~/.agents/skills/zhihu-archive/scripts/cli.py 的 _load_env_from_shell
    是同一约定，不另立格式。只读不回显。
    """
    env_val = os.environ.get(name, "").strip()
    if env_val:
        return env_val
    for p in (Path.home() / ".env.secrets", Path.home() / ".zsh_secrets"):
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.replace("export", "").strip() == name:
                    v = v.strip().strip('"').strip("'")
                    if v:
                        return v
        except OSError:
            pass
    return ""


def eastmoney_api_key(explicit: Optional[str] = None) -> str:
    """东财 API key：显式参数 > 环境变量 > ~/.env.secrets"""
    key = explicit or secret_from_file("EASTMONEY_APIKEY")
    if not key:
        raise RuntimeError(
            "缺少 EASTMONEY_APIKEY（应放在 ~/.env.secrets，或经环境变量传入）")
    return key


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


# ═══ 磁盘缓存（单真源） ═══
#
# 历史教训：本模块曾有一整套 _CACHE_DIR/_CACHE_TTL/_get_cache_key/get_cached/
# set_cached/parallel_execute/query_eastmoney_parallel/eastmoney_query_with_cache，
# 但**全仓零调用者**——宣称有缓存，实际每次全量重取；~/.cache/invest-cli 下
# 十几个 json 是早已过期的残留，从未被读写。同一时间 sources/sec_edgar.py 里
# 另有一份**真正在用**的 _cached_json（TTL + 原子替换 + 写失败不阻断）。
# 两份实现同一件事、只有一份生效，是典型的重复实体。
#
# 现按奥卡姆剃刀收敛为一份：下面这组函数是唯一实现，sec_edgar 也复用它。
# 设计要点（全部来自 sec_edgar 已验证的实践）：
#   - TTL 以秒计，过期即重新取数；
#   - **原子替换**（写 .tmp 再 replace），避免半截文件被后续进程读到；
#   - 缓存任何一步失败都**不阻断主流程**，只是下次还要重取。

CACHE_TTL_QUOTE = 60.0        # 行情快照：1 分钟（同一轮分析内复用足够）
CACHE_TTL_FUNDAMENTAL = 3600.0  # 财务/基本面：1 小时（变动远慢于行情）
CACHE_TTL_MACRO = 1800.0      # 宏观时序：30 分钟（FRED 序列为周度/日度，远慢于此）
# 缓存文件的最长保留时间：TTL 只决定「读时是否算命中」，不负责删文件。
# 没有这一步，`sec`（单公司 companyfacts 约 3.7MB）会按查询过的公司数无界增长。
CACHE_MAX_AGE = 7 * 24 * 3600.0  # 7 天
# 进程内每个命名空间只清理一次：CLI 每进程只跑一条命令，避免重复 listdir。
_CACHE_PRUNED: set[str] = set()


def cache_root() -> Path:
    """invest-cli 缓存根目录（尊重 XDG/平台惯例，不硬编码个人路径）。"""
    env = os.environ.get("INVEST_CLI_CACHE_DIR", "").strip()
    if env:
        base = Path(env).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches" / "invest-cli"
    else:
        base = Path.home() / ".cache" / "invest-cli"
    base.mkdir(parents=True, exist_ok=True)
    return base


def state_root() -> Path:
    """用户态**数据**根目录（自选股等本地状态，与缓存严格分开）。

    为什么不放 cache_root()：缓存是「删了会自动重建」的东西，系统清理
    （macOS 会清 ~/Library/Caches）或用户手删都不该丢用户数据。自选股是
    用户资产，必须落在数据目录。
    """
    env = os.environ.get("INVEST_CLI_STATE_DIR", "").strip()
    base = Path(env).expanduser() if env else Path.home() / ".config" / "invest-cli"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_path(namespace: str, key: str) -> Path:
    """按命名空间 + 键定位缓存文件（键做散列，避免非法文件名字符）。"""
    digest = hashlib.sha256(str(key).encode("utf-8")).hexdigest()[:32]
    ns_dir = cache_root() / namespace
    ns_dir.mkdir(parents=True, exist_ok=True)
    return ns_dir / f"{digest}.json"


def cache_get(namespace: str, key: str, ttl: float) -> Optional[Any]:
    """读缓存；未命中/过期/损坏一律返回 None（调用方按未命中处理）。"""
    path = cache_path(namespace, key)
    try:
        if not path.is_file():
            return None
        if (time.time() - path.stat().st_mtime) >= ttl:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _prune_namespace(ns_dir: Path) -> None:
    """删掉过期缓存与残留 .tmp，把磁盘占用收敛到「最近用过的键」。

    TTL 只在读的时候生效（过期按未命中处理），文件本身不会消失；
    调用方换一个键、或某公司只查过一次，旧文件就永久留在磁盘上。
    `sec` 的 companyfacts 单文件约 3.7MB，无界增长只是时间问题。

    进程内每命名空间只做一次（CLI 每进程一条命令），best-effort 不阻断主流程。
    """
    marker = str(ns_dir)
    if marker in _CACHE_PRUNED:
        return
    _CACHE_PRUNED.add(marker)
    now = time.time()
    try:
        for p in ns_dir.iterdir():
            try:
                age = now - p.stat().st_mtime
                if p.name.endswith(".tmp"):
                    if age > 3600:  # 崩溃残留的临时文件，1 小时后清
                        p.unlink()
                elif age > CACHE_MAX_AGE:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def cache_set(namespace: str, key: str, value: Any) -> None:
    """写缓存：原子替换；任何失败都静默跳过，绝不影响主流程。

    临时文件名带 pid：CLI 每次调用都是独立进程，两个进程写同一个键时
    若共用同一个 .tmp，后写者会把先写者的临时文件截断，先写者的 replace
    则把「半截文件」搬到正式位置（或后写者 replace 时 ENOENT 而丢缓存）。
    按进程分名后，每个写者的替换都是自洽的整文件。
    """
    path = cache_path(namespace, key)
    try:
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except (OSError, TypeError, ValueError):
        return
    _prune_namespace(path.parent)


# 【已删除】parallel_execute / query_eastmoney_parallel / eastmoney_query_with_cache
#
# 这三个函数同样是零调用者的死代码，且与在用实现重复：
#   - parallel_execute 的有界并发，sources/hithink.py 的 _request_many 已实现
#     得更好（支持 http_get 注入以便单测保序、MAX_PARALLEL 封顶、异常不外泄）；
#   - query_eastmoney_parallel / eastmoney_query_with_cache 直连东财 claw 端点，
#     而该端点现有唯一入口是 sources/eastmoney.py + cmd_stock.query_eastmoney，
#     再留一条旁路只会让「东财请求怎么发」出现第二种写法。
# 删除即消灭一类 bug：同一件事的第二份实现，是漂移与误用的源头。
