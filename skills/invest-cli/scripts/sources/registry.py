"""数据源注册表：加载配置真源 + 可用性探测（门闩）。

CLI 与分析 skill 只通过本模块判断某数据源是否可用，不自行猜测。
"""
from __future__ import annotations

import os
import sys
import shutil
import importlib.util
import subprocess
from pathlib import Path
from typing import Any, Optional

from . import load_registry

# 可配置的数据源探测超时（防止探测某个 CLI 时卡死）
DETECT_TIMEOUT = 10


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
    val = os.environ.get(var)
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


def detect(conf: dict[str, Any]) -> tuple[bool, str]:
    """按 conf['detect'] 探测单个数据源，返回 (available, detail)。"""
    dt = (conf.get("detect") or {}).get("type")
    if dt == "env":
        return _probe_env(conf.get("env_var", ""))
    if dt == "python":
        return _probe_python((conf.get("detect") or {}).get("module", ""))
    if dt == "command":
        d = conf.get("detect") or {}
        return _probe_command(d.get("cmd", []), d.get("check", ""))
    if dt == "dir":
        d = conf.get("detect") or {}
        env_dir = os.environ.get(d.get("env_dir", ""))
        if env_dir and Path(env_dir).expanduser().is_dir():
            return True, f"{d.get('env_dir')} 已指向 skill 目录"
        return _probe_dir(d.get("skill", ""), d.get("key_hint", []))
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
