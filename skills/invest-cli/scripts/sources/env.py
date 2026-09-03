"""环境变量识别器：跨主流位置统一读取。

背景：同一个变量可能被配在四处，且各处可见性不同——
  1. 进程环境（os.environ）：当前 shell / 宿主应用继承；
  2. macOS launchctl 用户级环境（`launchctl getenv`）：GUI 会话/launchd
     服务里 `launchctl setenv` 设置，普通自动化子进程不继承；
  3. shell rc 文件（~/.zshenv ~/.zprofile ~/.zshrc ~/.bash_profile
     ~/.bashrc ~/.profile）：仅登录/交互 shell 加载；
  4. 用户级凭据文件（各适配器 credential_files，见 data-sources.yaml）。

detect 与适配器若只读 os.environ，就会出现「用户明明配了，detect 却说不
可用」的漂移。本模块按 1→2→3 顺序统一读取（凭据文件由适配器负责，职责不同）。

安全约束：
  - 只做文本解析，不执行任何 shell/命令替换（rc 里的 `VAR=$(.../`` 一律跳过）；
  - 不打印变量值，本模块只返回给调用方。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

_RC_FILE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_RC_SHELL_FORM = re.compile(r"\$\(|\`|\$[A-Za-z_{]")


def _strip_comment(line: str) -> str:
    """剥离行尾注释（引号内 # 不剥）。"""
    in_sq = in_dq = False
    for i, ch in enumerate(line):
        if ch == "'" and not in_dq:
            in_sq = not in_sq
        elif ch == '"' and not in_sq:
            in_dq = not in_dq
        elif ch == "#" and not in_sq and not in_dq:
            return line[:i]
    return line


def _unquote(val: str) -> str:
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
        return val[1:-1]
    return val


def default_rc_files() -> list[Path]:
    home = Path.home()
    return [
        home / ".zshenv", home / ".zprofile", home / ".zshrc",
        home / ".bash_profile", home / ".bashrc", home / ".profile",
    ]


def read_rc_var(name: str, rc_files: Optional[list[Path]] = None) -> str:
    """按主流 rc 顺序（后加载覆盖先加载）查找简单赋值。跳过命令替换与追加。"""
    val = ""
    for p in rc_files or default_rc_files():
        if not p.is_file():
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            m = _RC_FILE.match(_strip_comment(line.strip()))
            if not m or m.group(1) != name:
                continue
            raw = m.group(2)
            if _RC_SHELL_FORM.search(raw):
                continue  # 含 $(..)/`..`/变量引用：不执行，跳过
            val = _unquote(raw)
    return val


# launchctl 子进程查询较贵，30s 内复用（与 registry._PROBE_TTL 同量级）
_LAUNCHCTL_TTL = 30.0
_LAUNCHCTL_CACHE: dict[str, tuple[float, str]] = {}


def _launchctl_getenv(name: str) -> str:
    now = time.monotonic()
    hit = _LAUNCHCTL_CACHE.get(name)
    if hit and now - hit[0] < _LAUNCHCTL_TTL:
        return hit[1]
    val = ""
    try:
        proc = subprocess.run(
            ["launchctl", "getenv", name],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        val = ""
    _LAUNCHCTL_CACHE[name] = (now, val)
    return val


def read_env(name: str) -> str:
    """按 进程环境 → launchctl(Mac) → shell rc 顺序读取，命中即返。"""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    if os.uname().sysname == "Darwin":
        val = _launchctl_getenv(name)
        if val:
            return val
    return read_rc_var(name)
