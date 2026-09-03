"""数据源注册表：加载配置真源 + 可用性探测（门闩）。

CLI 与分析 skill 只通过本模块判断某数据源是否可用，不自行猜测。
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from . import load_registry

# 可配置的数据源探测超时（防止探测某个 CLI 时卡死）
DETECT_TIMEOUT = 10
ENV_KEY_FALLBACK = "HITHINK_FINANCE_API_KEY"
# command/dir 探测贵（子进程），同进程 30s 内复用；env/python 本身很便宜不缓存。
_PROBE_TTL = 30.0
_PROBE_CACHE: dict[tuple[Any, ...], tuple[float, bool, str]] = {}


def skill_roots() -> list[Path]:
    """候选 skill 根目录列表（可用 INVEST_SKILL_ROOTS 覆盖扩展，os.pathsep 分隔）。"""
    roots: list[Path] = []
    env_roots = os.environ.get("INVEST_SKILL_ROOTS", "")
    if env_roots:
        for p in env_roots.split(os.pathsep):
            if p.strip():
                roots.append(Path(p.strip()).expanduser())
    home = Path.home()
    for base in (
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        home / ".grok" / "skills",
        home / ".codex" / "skills",
    ):
        roots.append(base)
    cwd = Path.cwd()
    for base in (cwd / ".agents" / "skills", cwd / ".claude" / "skills"):
        roots.append(base)
    # 自动发现常见项目根下的数据源 skill（如 Wind 装在项目内），无需手工配环境变量
    for parent in (home / "Documents",):
        if parent.is_dir():
            for proj in parent.glob("*"):
                for base in (proj / ".agents" / "skills", proj / ".claude" / "skills"):
                    if base.is_dir() and base not in roots:
                        roots.append(base)
    return roots


def find_skill_dir(skill_name: str) -> Optional[Path]:
    """在常见 skill 根目录定位某个 skill 目录，找不到返回 None。"""
    for root in skill_roots():
        cand = root / skill_name
        if cand.is_dir():
            return cand
    return None


def _probe_env(var: str) -> tuple[bool, str]:
    from .env import read_env

    val = read_env(var)
    if val:
        return True, f"{var} 已配置"
    return False, f"缺少环境变量 {var}"


def _probe_python(module: str) -> tuple[bool, str]:
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        return True, f"模块 {module} 可用"
    return False, f"未安装 python 模块 {module}"


def _probe_command(cmd: list[str], check: str) -> tuple[bool, str]:
    if not cmd:
        return False, "空探测命令"
    exe = shutil.which(cmd[0])
    if not exe:
        return False, f"命令 {cmd[0]} 不在 PATH"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=DETECT_TIMEOUT
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"命令 {cmd[0]} 探测失败: {e}"
    out = (proc.stdout or "") + (proc.stderr or "")
    if not check:
        return proc.returncode == 0, f"{cmd[0]} 返回码 {proc.returncode}"
    if check in out:
        return True, f"{cmd[0]} 通过，命中 {check!r}"
    return False, f"{cmd[0]} 未命中 {check!r}"


def _probe_dir(skill: str, key_hint: list[str]) -> tuple[bool, str]:
    skill_dir = find_skill_dir(skill)
    if skill_dir is None:
        return False, f"未找到 skill 目录 {skill}（可用 INVEST_SKILL_ROOTS 指定）"
    # key_hint 任一存在即视为已配置 key
    for pattern in key_hint or []:
        p = Path(pattern).expanduser()
        if p.is_file():
            return True, f"读到 {skill} skill 目录 + key 文件"
    return False, f"找到 {skill} 目录，但未找到 key 文件（{key_hint}）"


def _cached(key: tuple[Any, ...], fn) -> tuple[bool, str]:
    now = time.monotonic()
    hit = _PROBE_CACHE.get(key)
    if hit and now - hit[0] < _PROBE_TTL:
        return hit[1], hit[2]
    ok, detail = fn()
    _PROBE_CACHE[key] = (now, ok, detail)
    return ok, detail


def detect(conf: dict[str, Any]) -> tuple[bool, str]:
    """按 conf['detect'] 探测单个数据源，返回 (available, detail)。"""
    dt = (conf.get("detect") or {}).get("type")
    if dt == "env":
        return _probe_env(conf.get("env_var", ""))
    if dt == "env_or_file":
        names = conf.get("adapters") or []
        if names:
            try:
                mod = importlib.import_module(f"sources.{names[0]}")
                fn = getattr(mod, "detect", None)
                if callable(fn):
                    # 适配器级探测多为子进程（ttskill status 等），与 command/dir 同享 TTL 缓存
                    return _cached(("adapter", names[0]), fn)
            except Exception:
                pass
        ok, detail = _probe_env(conf.get("env_var", ""))
        if ok:
            return ok, detail
        files = (conf.get("detect") or {}).get("files") or []
        var = conf.get("env_var") or ENV_KEY_FALLBACK
        for raw in files:
            if Path(raw).expanduser().is_file():
                return True, "读到 credentials.env"
        return False, f"缺少环境变量 {var} 且无凭据文件"
    if dt == "python":
        return _probe_python((conf.get("detect") or {}).get("module", ""))
    if dt == "command":
        d = conf.get("detect") or {}
        cmd = d.get("cmd", [])
        check = d.get("check", "")
        return _cached(("command", tuple(cmd), check), lambda: _probe_command(cmd, check))
    if dt == "dir":
        d = conf.get("detect") or {}
        from .env import read_env

        env_dir = read_env(d.get("env_dir", ""))
        if env_dir and Path(env_dir).expanduser().is_dir():
            return True, f"{d.get('env_dir')} 已指向 skill 目录"
        skill = d.get("skill", "")
        hints = tuple(d.get("key_hint") or [])
        return _cached(("dir", skill, hints), lambda: _probe_dir(skill, list(hints)))
    if dt == "always":
        return True, "始终可用（免费无 key）"
    return False, f"未知探测方式 {dt!r}"


def detect_all() -> dict[str, dict[str, Any]]:
    """返回 {source_id: {…conf, available, detail}}。"""
    registry = load_registry()
    out: dict[str, dict[str, Any]] = {}
    for sid, conf in registry.items():
        available, detail = detect(conf)
        out[sid] = {**conf, "available": available, "detail": detail}
    return out


def available_ids() -> list[str]:
    """仅返回探测可用的数据源 id，按 priority 降序。"""
    states = detect_all()
    ranked = sorted(
        states.items(), key=lambda kv: kv[1].get("priority", 0), reverse=True
    )
    return [sid for sid, st in ranked if st.get("available")]
