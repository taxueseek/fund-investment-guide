"""运行时路由：同一问题选一个源，不同问题才组合。

第一性原理
- 用户要的不是「把所有 API 挂上」，而是「这个问题该问谁」。
- yaml 的 coverage / priority 是声明；适配器是否暴露 stock/fund/us/screen 才是能力。
- Wind 声明覆盖 stock，但只有 call() 透传 → 不能进默认快照链。
- 同一字段禁止跨源拼接（东财 PE + 同花顺 ROE 口径不同）。
- 组合的合法形式：行情走 A、选股走 B、资讯走 C、基金诊断走 D。

探测顺序：coverage 含 kind → hasattr(adapter, kind) → detect(conf)。
先 hasattr 再 detect，避免为没有 fund() 的源（yingmi/bitget 等）付 CLI 探测成本。
"""
from __future__ import annotations

import importlib
from typing import Any, Callable, Optional

from . import load_registry
from .registry import detect

KIND_FNS = ("stock", "fund", "us", "screen")
# 市场对默认快照链的排除（能力边界，不是优先级）
MARKET_EXCLUDE = {
    ("stock", "hk"): frozenset({"hithink"}),
}


def _adapter_module(sid: str, conf: dict[str, Any]):
    names = conf.get("adapters") or [sid]
    name = names[0]
    return importlib.import_module(f"sources.{name}")


def pick(kind: str, market: Optional[str] = None) -> list[str]:
    """返回该问题当前可用、且真有方法的数据源 id，priority 降序。"""
    if kind not in KIND_FNS:
        return []
    registry = load_registry()
    ranked = sorted(
        registry.items(),
        key=lambda kv: kv[1].get("priority", 0),
        reverse=True,
    )
    excluded = MARKET_EXCLUDE.get((kind, market or ""), frozenset())
    out: list[str] = []
    for sid, conf in ranked:
        if kind not in (conf.get("coverage") or []):
            continue
        if sid in excluded:
            continue
        try:
            mod = _adapter_module(sid, conf)
        except Exception:
            continue
        if not callable(getattr(mod, kind, None)):
            continue
        available, _detail = detect(conf)
        if not available:
            continue
        out.append(sid)
    return out


def chains() -> dict[str, list[str]]:
    """给 datasources / 诊断用的默认链（按当前机器可用性）。"""
    return {
        "stock_a": pick("stock", market="a"),
        "stock_hk": pick("stock", market="hk"),
        "fund": pick("fund"),
        "us": pick("us"),
        "screen": pick("screen"),
    }


def _invoke(sid: str, kind: str, arg: str) -> dict[str, Any]:
    registry = load_registry()
    conf = registry.get(sid) or {}
    mod = _adapter_module(sid, conf)
    fn = getattr(mod, kind)
    return fn(arg)


def fetch(
    kind: str,
    arg: str,
    *,
    market: Optional[str] = None,
    order: Optional[list[str]] = None,
    invoke: Optional[Callable[[str, str, str], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """按 pick() 顺序整单取数。第一个 ok 即停，不混字段。

    order 可注入：默认走 pick()（依赖本机可用性）；测试传显式链锁定回退逻辑。
    """
    caller = invoke or _invoke
    errors: list[str] = []
    last: dict[str, Any] | None = None
    if order is None:
        order = pick(kind, market=market)
    if not order:
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"无可用数据源: kind={kind} market={market or '-'}",
        }
    for sid in order:
        try:
            res = caller(sid, kind, arg)
        except Exception as e:
            errors.append(f"{sid}: {e}")
            continue
        last = res if isinstance(res, dict) else None
        if isinstance(res, dict) and res.get("ok"):
            if errors:
                res = {
                    **res,
                    "fallback_from": errors[-1].split(":", 1)[0],
                    "fallback_error": "; ".join(errors),
                }
            return res
        errors.append(f"{sid}: {(res or {}).get('error') if isinstance(res, dict) else '非信封'}")
    return {
        "source": kind,
        "kind": kind,
        "ok": False,
        "data": None,
        "error": "; ".join(errors) if errors else f"{kind} 全部失败",
        "tried": order,
        "last": last,
    }


def unwrap_snapshot(res: dict[str, Any]) -> dict[str, Any]:
    """信封 → CLI 快照。失败抛 RuntimeError。"""
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        raise RuntimeError(res.get("error") or "取数失败")
    snap = dict(res["data"])
    snap.setdefault("source", res.get("source"))
    if res.get("fallback_from"):
        snap["fallback_from"] = res["fallback_from"]
        snap["fallback_error"] = res.get("fallback_error")
    return snap
