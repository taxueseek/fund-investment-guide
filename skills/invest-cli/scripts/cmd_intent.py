"""intent 意图层：把 69 个盈米工具 + Wind 7 类收敛为 6 个语义入口。

第一性原理：接口面要小（按意图），能力面要全（内部路由到权威源）。
外部只暴露 deep/screen/portfolio/plan/macro/present 六个意图命令，
内部按场景 + 标的类型路由到盈米/Wind/东财/ttfund 的具体工具。

数据源透传（wind/yingmi/ttfund 子命令）保留为高级/调试入口，不是主用法。

使用:
    invest-cli intent deep <type> <标的> [--json]      # type: stock/fund/bond/commodity
    invest-cli intent screen <条件> [--json]
    invest-cli intent portfolio <持仓json> [--json]
    invest-cli intent plan <家庭数据json> [--json]
    invest-cli intent macro [--json]
    invest-cli intent present <html|json> [--json]
"""
from __future__ import annotations

import json
import re
import sys

# 场景 → 权威源调用。内部路由，供意图层复用。
# 每个调用用现有 source 适配器（yingmi.call / wind.call / eastmoney / ttfund）。
ROUTES: dict[str, dict] = {
    "deep": {
        "fund": lambda p: ("yingmi", "GetFundDiagnosis", {"fundCode": p}),
        "stock_a_hk": lambda p: ("eastmoney_stock", p, None),
        "us": lambda p: ("yfinance", p, None),
        "bond": lambda p: ("ttfund", "bond", None),
        "commodity": lambda p: ("ttfund", "gold", None),
    },
    "screen": {
        "fund": lambda p: ("yingmi", "SearchFunds", {"keyword": p}),
        "stock": lambda p: ("eastmoney_screen", p, None),
    },
    "macro": {},
    "portfolio": {"default": ("yingmi", "DiagnoseFundPortfolio", {})},
    "plan": {"default": ("yingmi", "GetAssetAllocationPlan", {})},
    "present": {"default": ("wind", "RenderHtmlToPdf", {})},
}


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


def classify(target: str) -> str:
    """根据代码/名称自动识别标的类型：fund / stock / us / bond / commodity。"""
    t = target.strip()
    # 名称关键词
    if any(k in t for k in ("基金", "混合", "ETF", "联接", "指数增强", "债基", "定开", "LOF", "FOF", "QDII")):
        return "fund"
    if any(k in t for k in ("债券", "国债", "转债", "信用债", "城投")):
        return "bond"
    if any(k in t for k in ("黄金", "白银", "原油", "商品")):
        return "commodity"
    # 纯代码
    if re.fullmatch(r"\d{6}", t):
        return "fund" if _is_fund_by_yingmi(t) else "stock"
    if re.fullmatch(r"\d{5}", t):
        return "stock"
    # 美股字母代码
    if t.isalpha() and 1 <= len(t) <= 5:
        return "us"
    # 名称兜底：用盈米确认是否为基金（多数基金名不含「基金」二字）
    if _is_fund_by_yingmi(t):
        return "fund"
    return "stock"


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
        # 默认按基金筛，指标/关键词在 value 里
        return {"scene": "screen", "route": ROUTES["screen"]["fund"](value)}
    if scene == "portfolio":
        return {"scene": "portfolio", "route": ROUTES["portfolio"]["default"](value)}
    if scene == "plan":
        return {"scene": "plan", "route": ROUTES["plan"]["default"](value)}
    if scene == "present":
        return {"scene": "present", "route": ROUTES["present"]["default"](value)}
    if scene == "macro":
        q = value or "中国 宏观经济 数据 指标"
        return {"scene": "macro", "route": ("argo", "nbs_stats", q)}
    return {"error": f"未知场景 {scene}"}


def run(scene: str, value: str, as_json: bool = False) -> int:
    from sources import wind as wind_src, yingmi as yingmi_src, eastmoney, ttfund, argo as argo_src, yfinance as yfinance_src

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
    elif kind == "eastmoney_stock":
        res = eastmoney.stock(route[1])
    elif kind == "eastmoney_screen":
        res = eastmoney.screen(route[1])
    elif kind == "yfinance":
        res = yfinance_src.us(route[1])
    elif kind == "ttfund":
        res = ttfund.raw_call([route[1]])
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
