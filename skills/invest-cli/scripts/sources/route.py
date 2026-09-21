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

# 快照缓存 TTL：与 _common 的口径常量对齐；screen 是条件查询，不缓存。
_SNAPSHOT_TTL_KINDS = {"stock": "quote", "us": "quote", "fund": "fundamental"}


def _snapshot_ttl(kind: str) -> Optional[float]:
    """该 kind 的快照缓存 TTL（秒）；不缓存的返回 None。"""
    slot = _SNAPSHOT_TTL_KINDS.get(kind)
    if slot is None:
        return None
    try:
        from _common import CACHE_TTL_FUNDAMENTAL, CACHE_TTL_QUOTE
    except Exception:
        return None
    return CACHE_TTL_QUOTE if slot == "quote" else CACHE_TTL_FUNDAMENTAL


def _adapter_module(sid: str, conf: dict[str, Any]):
    names = conf.get("adapters") or [sid]
    name = names[0]
    return importlib.import_module(f"sources.{name}")


def candidates(kind: str, market: Optional[str] = None) -> list[str]:
    """按 priority 降序返回「有能力回答该问题」的源，**不做可用性探测**。

    与 pick() 的分工：探测是贵的（yfinance 要真实 HTTPS），而它大多数时候
    用不上——A 股链里 yfinance 只是末位兜底，却会在每个冷探测窗口被探一次。
    这里只做便宜的能力判定（coverage 含 kind + 适配器真有该方法），
    可用性交给 fetch() 在**即将调用某个源之前**逐个判定。
    """
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
        out.append(sid)
    return out


def pick(kind: str, market: Optional[str] = None) -> list[str]:
    """返回该问题当前可用、且真有方法的数据源 id，priority 降序。

    供 `datasources` / `chains()` 这类需要「一次看清全链可用性」的场景；
    取数主路径请用 fetch()，它在调用前才逐个探测（见 candidates 注释）。
    """
    registry = load_registry()
    out: list[str] = []
    for sid in candidates(kind, market=market):
        available, _detail = detect(registry.get(sid) or {})
        if available:
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
    """按候选顺序整单取数。第一个 ok 即停，不混字段。

    order 可注入：默认走 candidates()（能力判定，不探测）；测试传显式链锁定回退逻辑。
    默认路径上每个源在**即将被调用前**才探测可用性：主源命中时，
    后面的兜底源（如 A 股链里的 yfinance）根本不会被探测，省掉一次无关的网络往返。
    成功信封走跨进程磁盘缓存（CLI 每进程都新起，进程内缓存无效）；
    仅生产默认路径（未注入 invoke/order）启用，测试注入路径保持直通语义。
    """
    if not str(arg or "").strip():
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"空标的：{kind} 需要代码或名称",
        }
    caller = invoke or _invoke
    errors: list[str] = []
    last: dict[str, Any] | None = None
    default_path = invoke is None and order is None
    if order is None:
        order = candidates(kind, market=market)
    if not order:
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"无可用数据源: kind={kind} market={market or '-'}",
        }
    ttl = _snapshot_ttl(kind) if default_path else None
    cache_key = f"{kind}|{market or '-'}|{arg}"
    if ttl:
        try:
            from _common import cache_get

            hit = cache_get("snapshot", cache_key, ttl)
        except Exception:
            hit = None
        if isinstance(hit, dict) and hit.get("ok"):
            return {**hit, "cached": True}
    registry = load_registry() if default_path else {}
    detected = 0
    for sid in order:
        if default_path:
            available, detail = detect(registry.get(sid) or {})
            if not available:
                errors.append(f"{sid}: {detail}")
                continue
            detected += 1
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
            if ttl:
                try:
                    from _common import cache_set

                    cache_set("snapshot", cache_key, res)
                except Exception:
                    pass
            return res
        errors.append(f"{sid}: {(res or {}).get('error') if isinstance(res, dict) else '非信封'}")
    if default_path and not detected:
        # 整条链没有一个源通过探测：保持与旧 pick() 一致的结论与措辞
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"无可用数据源: kind={kind} market={market or '-'}",
        }
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
    if res.get("cached"):
        snap["cached"] = True  # 透传缓存命中标记，CLI 输出可见（接线可验证）
    if res.get("fallback_from"):
        snap["fallback_from"] = res["fallback_from"]
        snap["fallback_error"] = res.get("fallback_error")
    return snap
