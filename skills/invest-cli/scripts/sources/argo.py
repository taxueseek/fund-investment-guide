"""argo 数据源适配器：财经检索 / 资讯 / 舆情（低成本、广覆盖）。

定位：argo 是「检索资讯」类源，非「结构化数值」源。用于：
- 财经资讯 / 舆情 / 市场情绪 / 政策行业背景（替代盈米资讯类工具，省配额）
- 结构化源配额不足/失败时的兜底（结果需核验，标注非权威）

调用 argo CLI：python3 scripts/search.py "<query>" --engine <engine> --max-results N --json

引擎清单**不在本模块维护**：argo 自带 250+ 引擎且随版本演进，任何本地白名单
都会漂移（实测：白名单里的 `cn-web-search` 早已不存在，用户拿到的是
「0 结果 + ok=true」的静默空答复；同时合法引擎如 anysearch 会被静默替换成
eastmoney）。因此这里只做透传，由 argo 自己裁决：
- 引擎名无效 → argo 在 stderr 打 `未知引擎: <name>`，本模块据此转成 ok=False；
- 引擎缺 key / 熔断 → argo 在信封 errors 里给原因，本模块原样带给调用方。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from . import registry

ARGO_ROOT = "argo"
CALL_TIMEOUT = 45
DEFAULT_ENGINE = "eastmoney"
# argo 的 `未知引擎` 提示固定走 stderr（实测：合法引擎 stderr 为空字节）。
# 但它**只在冷缓存路径**出现：argo 命中自己的缓存后会直接回缓存信封，不再解析引擎
# （实测同一 query 连跑两次，第一次 stderr 112 字节，第二次 0 字节且 cached=true）。
# 因此它只能当补充信号，主判据是向 argo 问一次「合法引擎清单」。
_UNKNOWN_ENGINE_MARK = "未知引擎"
ENGINE_LIST_TTL = 3600.0


def known_engines() -> Optional[set[str]]:
    """向 argo 要一次合法引擎清单（磁盘缓存 1h）。

    为什么需要：引擎名写错时 argo 仍以 exit 0 返回一个**空结果信封**，
    信封里没有任何「引擎不存在」的标记（实测 engine_outcomes 记的是
    `no-results`、errors 为空）。若不主动校验，用户拿到的是
    「0 结果 + ok=true」的静默空答复。

    拿不到清单（argo 不支持该 flag、超时、输出非 JSON）时返回 None，
    调用方**放行**——校验本身出问题绝不该阻断取数。
    """
    p = locate()
    if p is None:
        return None
    try:
        from _common import cache_get

        hit = cache_get("argo", "engines", ENGINE_LIST_TTL)
    except Exception:
        hit = None
    if isinstance(hit, list) and hit:
        return {str(x) for x in hit}
    try:
        proc = subprocess.run(
            ["python3", str(p), "--list-engines", "--json"],
            capture_output=True, text=True, timeout=CALL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    try:
        names = json.loads((proc.stdout or "").strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(names, list) or not names:
        return None
    names = [str(x) for x in names if isinstance(x, (str, int))]
    try:
        from _common import cache_set

        cache_set("argo", "engines", names)
    except Exception:
        pass
    return set(names)


def _unknown_engine_error(engine: str, search_py: Path) -> dict:
    """不认识的引擎：明确报错，并给出可执行的清单命令（不给占位符路径）。"""
    return {"source": "argo", "ok": False, "data": None,
            "error": f"argo 不认识引擎「{engine}」；可用清单：python3 {search_py} --list-engines"
                     f"（常用：eastmoney/zhihu/cninfo/anysearch）"}


def locate() -> Optional[Path]:
    """定位 argo 的 scripts/search.py。"""
    d = registry.find_skill_dir(ARGO_ROOT)
    if d is None:
        return None
    p = d / "scripts" / "search.py"
    return p if p.is_file() else None


def detect() -> tuple[bool, str]:
    p = locate()
    if p is None:
        return False, "未找到 argo（scripts/search.py）"
    return True, f"argo 可用（{p.parent.parent.name}）"


def _note_from_envelope(env: dict, engine: str) -> str:
    """无结果时给出**来自 argo 的**原因，而不是本模块猜的原因。"""
    errs = [str(e) for e in (env.get("errors") or []) if e]
    if errs:
        return f"{engine} 无结果（argo: {'；'.join(errs[:2])}）"
    return f"{engine} 无结果（尝试换 engine 或改检索词）"


def _stderr_summary(stderr: str) -> str:
    """非零退出时给一句可用原因：取 stderr 最后一行非空内容。

    argo 崩在 Python 异常时 stderr 是一整段 traceback，旧写法取前 160 字符，
    用户看到的「原因」是「Traceback (most recent call last):」——
    真正的原因在最后一行（如 ModuleNotFoundError）。
    """
    lines = [ln.strip() for ln in (stderr or "").splitlines() if ln.strip()]
    return lines[-1][:200] if lines else ""


def search(query: str, engine: str = DEFAULT_ENGINE, limit: int = 5) -> dict:
    p = locate()
    if p is None:
        return {"source": "argo", "ok": False, "data": None,
                "error": "未找到 argo（用 INVEST_SKILL_ROOTS 指定）"}
    engine = (engine or "").strip() or DEFAULT_ENGINE
    # 主判据：先问 argo 认不认这个引擎。stderr 的 `未知引擎` 只在冷缓存路径出现
    # （见文件头注释），单独依赖它会时灵时不灵；清单拿不到时放行（fail-open）。
    known = known_engines()
    if known is not None and engine not in known:
        return _unknown_engine_error(engine, p)
    # --max-results 必须透传：argo 默认只返回 5 条，不传则 limit>5 被静默截断
    cmd = ["python3", str(p), query, "--engine", engine,
           "--max-results", str(max(1, int(limit))), "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"source": "argo", "ok": False, "data": None, "error": f"argo 检索失败: {e}"}

    stderr = proc.stderr or ""
    if _UNKNOWN_ENGINE_MARK in stderr:
        # 清单探测失败时的兜底信号（冷路径）。不必从 stderr 里解析引擎名：
        # argo 原样回显请求里的名字（实测 stderr 为 `未知引擎: <我们传的值>`），
        # 解析只是把 engine 再读一遍。
        return _unknown_engine_error(engine, p)

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return {"source": "argo", "ok": False, "data": None,
                "error": f"argo 退出码 {proc.returncode}: {_stderr_summary(stderr)}"}
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        return {"source": "argo", "ok": True, "data": raw, "error": None}
    if not isinstance(env, dict):
        # 信封不是对象（历史上出现过 CLI 直返数组的源），原样交给调用方，不当成成功解析
        return {"source": "argo", "ok": True, "data": env, "error": None}
    results = env.get("results", []) or []
    return {
        "source": "argo",
        "ok": True,
        "data": {"query": query, "engine": engine,
                 "results": [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("snippet")}
                             for r in results[:limit]],
                 "note": "argo 检索结果需核验（非权威结构化数据）" if results
                         else _note_from_envelope(env, engine)},
        "error": None,
    }
