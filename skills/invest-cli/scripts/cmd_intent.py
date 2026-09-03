"""intent 意图层：把 69 个盈米工具 + Wind 7 类收敛为 6 个语义入口。

第一性原理：接口面要小（按意图），能力面要全（内部路由到权威源）。
外部只暴露 deep/screen/portfolio/plan/macro/present 六个意图命令，
内部按场景 + 标的类型路由到盈米/Wind/同花顺/东财/官方 ttskill 的具体工具。

数据源透传（wind/yingmi 子命令）保留为高级/调试入口，不是主用法。

使用:
    invest-cli intent deep <type> <标的> [--json]      # type: stock/fund/bond/commodity
    invest-cli intent screen <条件> [--json]
    invest-cli intent portfolio <持仓json|自然语言> [--json]
    invest-cli intent plan <家庭数据json|自然语言> [--json]
    invest-cli intent macro [--json]
    invest-cli intent present <html文件路径> [--json]   # HTML → 终端摘要
"""
from __future__ import annotations

import json
import re
import sys

# 场景 → 权威源调用。内部路由，供意图层复用。
# 每个调用用现有 source 适配器（yingmi.call / wind.call / eastmoney / 官方 ttskill）。
ROUTES: dict[str, dict] = {
    "deep": {
        "fund": lambda p: ("fund_deep", p, None),
        "stock_a_hk": lambda p: ("stock_deep", p, None),
        "us": lambda p: ("yfinance", p, None),
        "bond": lambda p: ("wind_bond", p, None),
        "commodity": lambda p: ("ttskill_scene", "TTFUND_GOLD_INFO", {"query_scope": "gold"}),
    },
    "screen": {
        "fund": lambda p: ("yingmi", "SearchFunds", {"keyword": p}),
        "stock": lambda p: ("eastmoney_screen", p, None),
    },
    "macro": {},
    "portfolio": {"default": lambda p: ("yingmi", "DiagnoseFundPortfolio", {"input": p})},
    "plan": {"default": lambda p: ("yingmi", "GetAssetAllocationPlan", {"input": p})},
    "present": {"default": lambda p: ("present_html", p, None)},
}

# 简单场景 → 盈米工具名（value 整体作为用户输入）。
_SCENE_TOOLS: dict[str, str] = {
    "portfolio": "DiagnoseFundPortfolio",
    "plan": "GetAssetAllocationPlan",
}


# 6 位代码里能靠前缀 MECE 切开的部分：不要为茅台去打盈米 CLI。
_SH_A = re.compile(r"^(60[0135]|688|689)\d{3}$")
_CHINEXT = re.compile(r"^30[01]\d{3}$")
_FUND_6 = re.compile(r"^[15]\d{5}$")


def kind_from_code(t: str) -> str | None:
    """纯代码的确定性分类。None = 与基金代码区间重叠，才允许外部消歧。"""
    if re.fullmatch(r"\d{5}", t):
        return "stock"
    if not re.fullmatch(r"\d{6}", t):
        return None
    if _SH_A.match(t) or _CHINEXT.match(t):
        return "stock"
    if _FUND_6.match(t):
        return "fund"
    return None


def _is_fund_by_yingmi(target: str) -> bool:
    """用盈米 GuessFundCode 确认是否基金（自动识别用）。失败默认非基金。"""
    try:
        from sources import yingmi as _ym
        res = _ym.call("GuessFundCode", {"fundNameOrCode": target})
    except Exception:
        return False
    if not res.get("ok"):
        return False
    data = res.get("data") or {}
    # 成功匹配到基金名 → 视为基金
    return bool(data) and (isinstance(data, dict) and bool(data.get("fundName") or data.get("name")))


# 英文类型词精确匹配：避免裸类型词被当成美股代码或拿去问盈米
_EN_TYPE: dict[str, str] = {"bond": "bond", "gold": "commodity", "commodity": "commodity"}


def classify(target: str) -> str:
    """根据代码/名称自动识别标的类型：fund / stock / us / bond / commodity。"""
    t = target.strip()
    en = _EN_TYPE.get(t.lower())
    if en:
        return en
    # 名称关键词
    if any(k in t for k in ("基金", "混合", "ETF", "联接", "指数增强", "债基", "定开", "LOF", "FOF", "QDII")):
        return "fund"
    if any(k in t for k in ("债券", "国债", "转债", "信用债", "城投")):
        return "bond"
    if any(k in t for k in ("黄金", "白银", "原油", "商品")):
        return "commodity"
    coded = kind_from_code(t)
    if coded:
        return coded
    if re.fullmatch(r"\d{6}", t):
        return "fund" if _is_fund_by_yingmi(t) else "stock"
    # 美股字母代码
    if t.isalpha() and 1 <= len(t) <= 5:
        return "us"
    # 名称兜底：用盈米确认是否为基金（多数基金名不含「基金」二字）
    if _is_fund_by_yingmi(t):
        return "fund"
    return "stock"


def _looks_like_fund_screen(value: str) -> bool:
    return any(k in (value or "") for k in ("基金", "ETF", "债基", "LOF", "FOF", "QDII", "基金经理"))


def _resolve_fund_code(target: str) -> str:
    """基金名 → 基金代码（用盈米 GuessFundCode）。已是 6 位代码则原样返回。"""
    t = target.strip()
    if re.fullmatch(r"\d{6}", t):
        return t
    try:
        from sources import yingmi as _ym
        res = _ym.call("GuessFundCode", {"fundNameOrCode": t})
        data = res.get("data") if res.get("ok") else None
        if isinstance(data, dict):
            for k in ("fundCode", "code", "fund_code"):
                if data.get(k):
                    return str(data[k])
    except Exception:
        pass
    return t


def _dispatch(scene: str, value: str) -> dict:
    """按场景 + 标的类型返回 {source:..., call:...}，失败返回 {'error':...}。"""
    if scene == "deep":
        parts = value.split(" ", 1)
        if len(parts) != 2:
            # 无显式类型 → 自动识别
            target = parts[0].strip()
            typ = classify(target)
        else:
            typ, target = parts[0], parts[1].strip()
        key = "stock_a_hk" if typ == "stock" else typ
        if typ == "us":
            key = "us"
        if typ == "fund":
            target = _resolve_fund_code(target)
        route = ROUTES["deep"].get(key) or ROUTES["deep"].get(typ)
        if not route:
            return {"error": f"deep 不支持类型 {typ}"}
        return {"scene": "deep", "type": typ, "route": route(target)}
    if scene == "screen":
        # 默认东财选股（与 invest-cli screen / SKILL 一致）；明确基金语义才走盈米。
        key = "fund" if _looks_like_fund_screen(value) else "stock"
        return {"scene": "screen", "route": ROUTES["screen"][key](value)}
    if scene in ("portfolio", "plan", "present"):
        return {"scene": scene, "route": ROUTES[scene]["default"](value)}
    if scene == "macro":
        q = value or "中国 宏观经济 数据 指标"
        return {"scene": "macro", "route": ("argo", "nbs_stats", q)}
    return {"error": f"未知场景 {scene}"}


def _stock_with_fallback(target: str) -> dict:
    """deep stock：快照链走 route（A 股同花顺→东财，港股东财）。"""
    from cmd_stock import _looks_like_hk
    from sources.route import fetch

    market = "hk" if _looks_like_hk(target) else "a"
    return fetch("stock", target, market=market)


def _fund_with_fallback(target: str) -> dict:
    """deep fund：诊断问盈米（独立问题）；快照问 route（同花顺→东财）。不混字段。"""
    from sources import load_registry
    from sources.registry import detect as detect_conf
    from sources.route import fetch

    conf = load_registry().get("yingmi")
    if conf:
        ok, _ = detect_conf(conf)
        if ok:
            try:
                from sources import yingmi as _ym

                code = _resolve_fund_code(target)
                res = _ym.call("GetFundDiagnosis", {"fundCode": code})
                if res.get("ok"):
                    return res
            except Exception:
                pass
    return fetch("fund", target)


def run(scene: str, value: str, as_json: bool = False) -> int:
    from sources import wind as wind_src, yingmi as yingmi_src, argo as argo_src

    d = _dispatch(scene, value)
    if "error" in d:
        print(f"intent 错误: {d['error']}", file=sys.stderr)
        return 1

    route = d["route"]
    # route 形如 (kind, payload_a, payload_b)；按 kind 分发到 source 适配器
    kind = route[0]
    if kind == "yingmi":
        tool_name = route[1]
        params = route[2] or {}
        # 若 value 是 JSON，尝试解析作为参数覆盖
        if value.strip().startswith("{"):
            try:
                params = json.loads(value)
            except json.JSONDecodeError:
                pass
        res = yingmi_src.call(tool_name, params=params if isinstance(params, dict) else {})
    elif kind == "wind":
        server_type, tool_name, params = (route[1], route[2], route[3] if len(route) > 3 else {})
        res = wind_src.call(server_type, tool_name, params=params)
    elif kind == "stock_deep":
        res = _stock_with_fallback(route[1])
    elif kind == "fund_deep":
        res = _fund_with_fallback(route[1])
    elif kind == "wind_bond":
        # 债券行情/估值走 Wind bond_data（官方 ttskill 债券包暂未收标的级行情）
        res = wind_src.call("bond_data", "get_bond_market_data", params={"question": route[1]})
    elif kind == "present_html":
        # 本地渲染 HTML → 终端摘要；外发 PDF 交给用户，不依赖不存在的 Wind 渲染工具
        from cmd_present import render_html_summary

        res = render_html_summary(route[1])
    elif kind == "eastmoney_screen":
        from sources.route import fetch as route_fetch

        res = route_fetch("screen", route[1])
    elif kind == "yfinance":
        from sources.route import fetch as route_fetch

        res = route_fetch("us", route[1])
    elif kind == "ttskill_scene":
        # 官方天天业务包场景（如 TTFUND_GOLD_INFO）；ttfund 老 CLI 已退役
        from sources.ttskill import invoke_scene as tts_scene

        res = tts_scene(route[1], route[2] or {})
    elif kind == "argo":
        res = argo_src.search(route[2], engine=route[1])
    else:
        res = {"source": "unknown", "ok": False, "data": None, "error": f"未知路由 {kind}"}

    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res.get("ok"):
            print(json.dumps(res.get("data"), ensure_ascii=False, indent=2))
        else:
            print(f"intent 失败: {res.get('error')}", file=sys.stderr)
    return 0 if res.get("ok") else 1
