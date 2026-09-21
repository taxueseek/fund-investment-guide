"""数据源注册表：加载配置真源 + 可用性探测（门闩）。

CLI 与分析 skill 只通过本模块判断某数据源是否可用，不自行猜测。
"""
from __future__ import annotations

import importlib
import importlib.util
import json
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
# 真实 HTTPS 探测预算：要远小于数据源自身的连接超时，
# 否则「探测」本身就成了新的瓶颈（Yahoo 库内写死 30s）。
HTTP_PROBE_TIMEOUT = 2.0
PROBE_USER_AGENT = "invest-cli/1.0 (reachability probe)"
# **跨进程**缓存：CLI 每次调用都是新进程，进程内 TTL 缓存救不了冷启动。
# 若不落盘，每次 `invest-cli stock ...` 都要重付一次可达性探测
# （实测 yfinance 冷探测 2.02s，占 pick() 全部耗时；热探测 0.0003s）。
#
# 成功与失败的 TTL 刻意不同（**非对称**）：
#   - 成功：缓存久一点（省探测成本，源确实好用）；
#   - 失败：缓存很短，因为**一次网络抖动不该让一个可用源被禁 5 分钟**。
#     负结果缓存过长会把「瞬时不可达」放大成「持续不可用」，
#     这是探测类设计最典型的自伤（假阴性)。
_PROBE_DISK_TTL = 300.0
_PROBE_DISK_TTL_FAIL = 20.0
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
    """python 包型数据源探测：装了 ≠ 可达。

    只做 find_spec 是旧行为，它会伪造可用性：本机 Yahoo 完全不可达时，
    yfinance 仍被判「可用」并排进 us 链首位，于是每次 `us <code>` 先烧满
    yfinance 的 30s 连接超时再回退 bitget（实测 31.3s vs 1.0s）。
    「可用」的判据必须是「这个源现在真能取到数」，而不是「这个包在磁盘上」。

    为什么不是 TCP 探测：本机 TCP connect 到 Yahoo 在 0.01s 内就「成功」
    （被本地 PAC/透明代理应答），而真实 HTTPS 请求 10s 都不返回
    （curl 实测 connect=0.000000s、total=10.06s 后超时）。
    即 TCP 可达性是个假信号，会原样保留这个 bug。因此这里做**真实 HTTPS
    探测**：一次 HEAD/GET，带 2s 预算，判据是拿到 HTTP 状态码。

    结果按 _PROBE_TTL 缓存，故每个进程最多只付一次探测成本。
    探测不可判定（异常/网络栈问题）时**放行**（fail-open），
    绝不因探测本身出错而误杀一个可能好用的数据源。
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return False, f"未安装 python 模块 {module}"

    url = _probe_url_for_module(module)
    if not url:
        return True, f"模块 {module} 可用"
    reachable, detail = _cached(("http", url), lambda: _probe_http(url))
    if not reachable:
        return False, f"模块 {module} 已安装，但端点不可达（{detail}）"
    return True, f"模块 {module} 可用（{detail}）"


# 需要做真实可达性校验的 python 包 → 探针 URL。
# 只登记「装了但可能连不上」的网络型包；纯本地计算包不在此列。
# 探针用**最轻的端点**（chart 接口单标的、不取字段），避免探测本身开销过大。
_PYTHON_ENDPOINTS: dict[str, str] = {
    "yfinance": "https://query1.finance.yahoo.com/v8/finance/chart/AAPL",
}


def _probe_url_for_module(module: str) -> str:
    return _PYTHON_ENDPOINTS.get(module, "")


def _probe_http(url: str, timeout: float = HTTP_PROBE_TIMEOUT) -> tuple[bool, str]:
    """真实 HTTPS 可达性探测：拿到任意 HTTP 状态码即视为可达。

    只读状态码、不解析响应体；任何网络异常都视为不可达。
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": PROBE_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, f"HTTP {resp.getcode()}"
    except urllib.error.HTTPError as e:
        # 有状态码 = 服务在线（401/403/405 都说明端点在应答）
        return True, f"HTTP {e.code}"
    except Exception as e:
        return False, f"{type(e).__name__}"


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


def _probe_cache_key(key: tuple[Any, ...]) -> tuple[Any, ...]:
    """把缓存根目录并入探测键。

    否则进程内缓存会跨缓存目录复用：一个在 dir_A 下探到的结果，会在
    INVEST_CLI_CACHE_DIR 切到 dir_B 后继续命中——测试隔离与运行时切换
    缓存位置都会被这条「串味」的条目绕过（实测可复现）。
    """
    try:
        from _common import cache_root

        return key + (str(cache_root()),)
    except Exception:
        return key


def _probe_cache_path(key: tuple[Any, ...]) -> Optional[Path]:
    """探测结果的落盘位置（全类型跨进程复用）。"""
    try:
        from _common import cache_path

        return cache_path("probe", repr(key))
    except Exception:
        return None


def _cached(key: tuple[Any, ...], fn) -> tuple[bool, str]:
    now = time.monotonic()
    ckey = _probe_cache_key(key)
    hit = _PROBE_CACHE.get(ckey)
    if hit and now - hit[0] < _PROBE_TTL:
        return hit[1], hit[2]

    # 全类型探测一律先看跨进程落盘缓存：CLI 每次都是新进程，进程内缓存无效。
    # 旧条件只落盘 http 型，command/adapter/dir 型每进程重付一次子进程探测
    # （实测 ~0.35s/类）。探测键已并入 cache_root（_probe_cache_key），
    # 落盘对全类型安全，不会跨缓存目录串味。
    disk = _probe_cache_path(ckey)
    if disk is not None:
        try:
            if disk.is_file():
                age = time.time() - disk.stat().st_mtime
                data = json.loads(disk.read_text(encoding="utf-8"))
                was_ok = bool(data.get("ok"))
                # 负结果只缓存很短时间，避免把瞬时抖动放大成持续不可用
                ttl = _PROBE_DISK_TTL if was_ok else _PROBE_DISK_TTL_FAIL
                if age < ttl:
                    ok, detail = was_ok, str(data.get("detail", ""))
                    _PROBE_CACHE[ckey] = (now, ok, detail)
                    return ok, detail
        except (OSError, ValueError):
            pass

    try:
        ok, detail = fn()
    except Exception as e:
        # fail-open 的另一半：探测函数**自身**抛异常时不能外泄。
        # 可用性判据出问题绝不该让整条取数链挂掉——按不可达处理并说明原因。
        ok, detail = False, f"探测异常（{type(e).__name__}）"
    _PROBE_CACHE[ckey] = (now, ok, detail)

    if disk is not None:
        try:
            # 临时名带 pid：CLI 每进程独立，共用同一个 .tmp 会让并发写者互相截断
            tmp = disk.with_name(f"{disk.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"ok": ok, "detail": detail}), encoding="utf-8")
            tmp.replace(disk)
        except OSError:
            pass

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
