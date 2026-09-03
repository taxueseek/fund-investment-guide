"""argo 数据源适配器：财经检索 / 资讯 / 舆情（低成本、广覆盖）。

定位：argo 是「检索资讯」类源，非「结构化数值」源。用于：
- 财经资讯 / 舆情 / 市场情绪 / 政策行业背景（替代盈米资讯类工具，省配额）
- 结构化源配额不足/失败时的兜底（结果需核验，标注非权威）

调用 argo CLI：python3 scripts/search.py "<query>" --engine <engine> --json
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

from . import registry

ARGO_ROOT = "argo"
CALL_TIMEOUT = 45

# 财经/宏观垂直引擎池（argo 已声明；需 key 的仅标注、不作为默认）
FIN_ENGINES = ("eastmoney", "zhihu", "cninfo", "cn_ai_news", "jin10",
               "cls_telegraph", "em_flow", "em_global_news", "em_miaoxiang",
               "finviz", "fx_rate", "gdelt", "coingecko", "cn-web-search")
MACRO_ENGINES = ("nbs_stats", "eurostat", "eu_opendata", "fred", "worldbank",
                 "gov_policy", "fr_opendata")
# 需 API key 才能取数的引擎（提示用，不作为默认）
REQUIRES_KEY = ("fred", "eurostat", "eu_opendata", "worldbank", "fr_opendata")


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


def search(query: str, engine: str = "eastmoney", limit: int = 5) -> dict:
    p = locate()
    if p is None:
        return {"source": "argo", "ok": False, "data": None,
                "error": "未找到 argo（用 INVEST_SKILL_ROOTS 指定）"}
    if engine not in (FIN_ENGINES + MACRO_ENGINES):
        engine = "eastmoney"
    needs_key = engine in REQUIRES_KEY
    cmd = ["python3", str(p), query, "--engine", engine, "--json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"source": "argo", "ok": False, "data": None, "error": f"argo 检索失败: {e}"}
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        return {"source": "argo", "ok": False, "data": None,
                "error": f"argo 退出码 {proc.returncode}: {(proc.stderr or '')[:160]}"}
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        return {"source": "argo", "ok": True, "data": raw, "error": None}
    results = env.get("results", [])
    note = "argo 检索结果需核验（非权威结构化数据）"
    if needs_key and not results:
        note = f"{engine} 需配置对应 API key 才能取数（本机未配置）"
    elif not results:
        note = f"{engine} 无结果（尝试换 engine 或改检索词）"
    return {
        "source": "argo",
        "ok": True,
        "data": {"query": query, "engine": engine,
                 "results": [{"title": r.get("title"), "url": r.get("url"), "snippet": r.get("snippet")}
                             for r in results[:limit]],
                 "note": note},
        "error": None,
    }
