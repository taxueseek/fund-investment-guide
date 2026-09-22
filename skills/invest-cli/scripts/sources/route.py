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
import re
from typing import Any, Callable, Optional

from . import load_registry
from .registry import detect

KIND_FNS = ("stock", "fund", "us", "screen")
# 市场对默认快照链的排除（能力边界，不是优先级）
MARKET_EXCLUDE = {
    ("stock", "hk"): frozenset({"hithink"}),
}

# 代码域守卫：纯数字代码落在**确定段**却与所问的 kind 不符时，直接拒绝。
#
# 为什么放在 route 层而不是各 cmd_* 里：`stock` 有两条入口（`cmd_stock.
# fetch_stock_with_fallback` 与 `cmd_intent` 的 `deep stock`），分别加守卫必然
# 漏一条——实测 `invest-cli stock 110011` 已被拒，而
# `invest-cli intent deep stock 110011` 仍拿到那张冒牌基金快照且 rc=0。
# 这里与上面的「空标的」检查同层，都是「这个问题本身不成立」。
#
# 只拦**确定段**（`_common.kind_from_code` 的唯一真源）：`000858` 这类与基金
# 号段重叠的返回 None，仍然放行交给下游解析，避免误杀正常查询。
_DOMAIN_NAME = {"fund": "基金代码", "bond": "可转债代码", "stock": "股票代码"}
_DOMAIN_HINT = {
    "fund": "invest-cli fund {v}",
    "bond": "invest-cli intent deep bond {v}",
    "stock": "invest-cli stock {v}",
}


# 带市场前缀/后缀的写法 → **裸代码**。
#
# 为什么要收敛到裸代码：链上各源的入参口径不同 —— 同花顺/东财/ttskill/盈米要裸代码，
# 腾讯/westock 要 `sh600519`，yfinance 要 `600519.SS`。过去没人管这件事，于是同一个
# 标的换个写法就走另一条路：实测
#   stock sh600519   → 同花顺「未找到匹配标的」→ 东财同 → 一路落到腾讯，只给 29 项**纯行情**（无基本面）
#   stock hk00700    → 落到腾讯 25 项（东财的港股快照本有 21 项含年报数据）
#   fund  sh510300   → 整条链失败（同花顺、ttskill 都认不出）
#   us    usAAPL     → yfinance 认不出 → 落到腾讯
# 在 route（唯一的取数入口）把写法归一成裸代码，各适配器再各自加自己需要的前缀 ——
# 一处改动覆盖四个命令，而不是让每个源各自做一遍容错。
_PREFIXED = re.compile(r"^(sh|sz|bj|hk|us)(?=[0-9A-Za-z])", re.I)
# 只认**交易所后缀**，不动美股 ticker 里的点（BRK.B 的 .B 不是交易所代码）
_SUFFIXED = re.compile(r"\.(SH|SZ|BJ|HK|US)$", re.I)


def canonical_arg(arg: str) -> str:
    """`sh600519` / `600519.SH` / `hk00700` / `usAAPL` → `600519` / `00700` / `AAPL`。"""
    t = str(arg or "").strip()
    if not t:
        return t
    m = _SUFFIXED.search(t)
    if m:
        return t[: -len(m.group(0))]
    return _PREFIXED.sub("", t)


def code_domain_error(kind: str, arg: str) -> str:
    """kind 与**确定段**代码的类型不符时返回错误文案，否则返回空串。"""
    if kind not in ("stock", "fund"):
        return ""
    try:
        from _common import kind_from_code
    except Exception:
        return ""
    code_kind = kind_from_code(arg)
    if code_kind is None or code_kind == kind:
        return ""
    asked = _DOMAIN_NAME[kind]
    return (
        f"「{arg}」是{_DOMAIN_NAME.get(code_kind, code_kind)}，不是{asked.replace('代码', '')}。"
        f"请改用：{_DOMAIN_HINT.get(code_kind, '').format(v=arg)}"
    )

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
    arg = canonical_arg(arg) if kind in KIND_FNS else arg
    domain_err = code_domain_error(kind, arg)
    if domain_err:
        return {"source": kind, "kind": kind, "ok": False, "data": None, "error": domain_err}
    caller = invoke or _invoke
    errors: list[str] = []
    last: dict[str, Any] | None = None
    default_path = invoke is None and order is None
    # ① 快照命中必须在**路由之前**判定。
    #
    # candidates() 看着便宜（只做能力判定、不探测），实际要读配置真源
    # （yaml.safe_load，实测 2.7ms/次）并 import 链上每个适配器模块——而
    # sources.bitget 一旦被 import 就带进 urllib.request → http.client → ssl，
    # 实测整条热路径的 import 自耗时约 50ms，其中约 20-25ms 出自这条链。
    # 缓存命中时这些全是白做的：一次 hit 重新解析配置、重新 import 一遍适配器，
    # 只为返回一个磁盘上已经躺着的 JSON。
    #
    # 为什么提前判定不改变命中语义：缓存键只由 kind/market/arg 决定，与候选链
    # 无关；ttl 只在默认路径（未注入 order/invoke）上非空，注入路径仍然直通。
    # 唯一的行为差异是「候选链为空 + 缓存新鲜」这组：旧代码先报「无可用数据源」，
    # 新代码先返回缓存。候选链为空意味着某个适配器连模块都 import 不进来，
    # 那时给一份新鲜快照显然比报「无源」更符合调用方意图。
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
        if isinstance(res, dict) and res.get("input_error"):
            # 输入层失败（如「多个候选无法唯一消歧」）：换源解决不了，只会让下游源去猜。
            # 实测 `fund -1` 曾因此返回一只任选的基金且 rc=0、同一输入不同时刻结果不同。
            errors.append(f"{sid}: {res.get('error')}")
            break
        errors.append(f"{sid}: {(res or {}).get('error') if isinstance(res, dict) else '非信封'}")
    if default_path and not detected:
        # 整条链没有一个源通过探测：结论与前缀措辞与旧 pick() 一致，但把
        # **逐源原因**接在后面——`无可用数据源: kind=fund market=-` 是内部术语，
        # 用户看不出缺哪个 key（同一条链上的 stock 会把原因列全，实测对比过）。
        # 走到这里时每个候选都因不可用而进了 errors，故不必处理空 errors 分支。
        return {
            "source": kind,
            "kind": kind,
            "ok": False,
            "data": None,
            "error": f"无可用数据源: kind={kind} market={market or '-'}；{'; '.join(errors)}",
            "tried": order,
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
