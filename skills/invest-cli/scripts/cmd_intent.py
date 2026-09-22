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
    "portfolio": {"default": lambda p: ("yingmi", "DiagnoseFundPortfolio", _portfolio_params(p))},
    "plan": {"default": lambda p: ("yingmi", "GetAssetAllocationPlan", _plan_params(p))},
    "present": {"default": lambda p: ("present_html", p, None)},
}

# 代码域分类的唯一真源在 _common（cmd_stock / cmd_fund 也用同一判据拦
# 「代码域与子命令不匹配」）。此处只做再导出，避免同一判据出现第二份实现。
from _common import kind_from_code  # noqa: E402


def _is_fund_by_yingmi(target: str) -> bool:
    """用盈米 GuessFundCode 确认是否基金（自动识别用）。失败默认非基金。

    盈米是**子串式模糊匹配**：股票简称会被配到「名字里含这几个字」的无关基金。
    实测：「中国平安」→「华银平安中国主题灵活配置混合」，
    「招商银行」→「银叶投资-招商银行-宁海工业园1号」。
    因此判据不能是「盈米返回了东西」，而必须是「返回的基金名与查询确有对应」：
    查询是基金名前缀（「易方达蓝筹精选」→「易方达蓝筹精选混合」），
    或者查询占了基金名的大部分（短名不要拿去配长名）。
    """
    try:
        from sources import yingmi as _ym
        res = _ym.call("GuessFundCode", {"fundNameOrCode": target})
    except Exception:
        return False
    if not res.get("ok"):
        return False
    data = res.get("data") or {}
    if not isinstance(data, dict):
        return False
    name = str(data.get("fundName") or data.get("name") or "").strip()
    kw = (target or "").strip()
    if not name or not kw:
        return False
    if name.startswith(kw):
        return True
    return kw in name and len(kw) >= 0.6 * len(name)


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
    # 美股字母代码（必须限 ASCII）：Python 里汉字也是 isalpha()，
    # 旧写法会把「茅台」「腾讯」这类中文名判成美股代码，
    # `intent deep 茅台` 于是去 Yahoo 找「茅台」，白付两轮失败网络。
    if t.isascii() and t.isalpha() and 1 <= len(t) <= 5:
        return "us"
    # 名称兜底：用盈米确认是否为基金（多数基金名不含「基金」二字）。
    # 但**短名（≤2 字）不做模糊匹配**：盈米的名称猜测是子串式的，
    # 「腾讯」会命中「银河定投宝腾讯济安指数」而被判成基金，
    # 而 2 字输入里股票/港股简称远多于基金简称（实测误配代价高于收益）。
    if len(t) >= 3 and _is_fund_by_yingmi(t):
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


# 持仓简写：110011:50 / 110011=10000 / 110011:50,005827:50。
# 金额必须带显式分隔符（: ： =）：否则「110011 005827」会被贪心成 code=110011, amount=5827。
_HOLDING_ITEM = re.compile(
    r"([0-9]{6}|[A-Za-z][A-Za-z0-9.]{0,9})(?:\s*[:：=]\s*([0-9]+(?:\.[0-9]+)?))?"
)


def _portfolio_params(value: str) -> dict:
    """自然语言/简写持仓 → DiagnoseFundPortfolio 的 body {fundList:[{fundCode,amount}]}。

    SKILL 文档写明 `intent portfolio <持仓json或自然语言>`，但旧实现把整串当
    `{"input": ...}` 发出去，服务端固定回 400「基金列表不能为空」——文档承诺的
    自然语言路径实际不可用。JSON 输入仍由 run() 原样透传（含 fundList 或基金数组）。
    """
    t = (value or "").strip()
    if t.startswith(("{", "[")):
        return {}  # JSON 由 run() 解析后覆盖
    fund_list = []
    for code, amount in _HOLDING_ITEM.findall(t):
        fund_list.append({"fundCode": code, "amount": float(amount) if amount else 10000.0})
    if not fund_list:
        return {}
    return {"fundList": fund_list}


def _num_before_or_after(text: str, keyword: str) -> float | None:
    """取关键词附近的数字：同时支持「20%回撤」与「回撤 20%」两种语序。"""
    m = re.search(rf"([0-9]+(?:\.[0-9]+)?)\s*%?\s*{keyword}", text) or \
        re.search(rf"{keyword}[^0-9]{{0,6}}([0-9]+(?:\.[0-9]+)?)\s*%?", text)
    return float(m.group(1)) if m else None


def _plan_params(value: str) -> dict:
    """自然语言 → GetAssetAllocationPlan 的三个查询参数（三性至少一项）。

    支持「能承受 20% 回撤 / 5 年 / 预期年化 8%」；百分比换算成小数。
    数字在关键词前或后都能识别（中文里两种语序都常见）。
    """
    t = (value or "").strip()
    if t.startswith(("{", "[")):
        return {}
    params: dict[str, float | str] = {}
    dd = _num_before_or_after(t, "回撤")
    if dd is not None:
        params["expectedDrawdown"] = dd / 100
    ret = _num_before_or_after(t, "年化")
    if ret is not None:
        params["expectedAnnualizedReturnRate"] = ret / 100
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*年", t)
    if m:
        params["expectedInvestTime"] = f"{m.group(1)}y"
    return params


def _dispatch(scene: str, value: str) -> dict:
    """按场景 + 标的类型返回 {source:..., call:...}，失败返回 {'error':...}。"""
    if scene == "deep":
        parts = value.split(" ", 1)
        if len(parts) != 2:
            # 无显式类型 → 自动识别；但「只有类型词没有标的」是缺参数，
            # 不能把它当成标的（旧写法会把 `deep stock` 当成美股代码 STOCK）。
            target = parts[0].strip()
            # commodity/gold 的取数是固定场景（TTFUND_GOLD_INFO），本就不需要标的；
            # 其余类型词没有标的就是缺参数，不能把它当成标的（旧写法会把
            # `deep stock` 当成美股代码 STOCK）。
            if target.lower() in ("stock", "fund", "us", "bond"):
                return {"error": f"deep 缺少标的（用法: intent deep <type> <标的>）"}
            typ = classify(target)
        else:
            typ, target = parts[0], parts[1].strip()
            # 显式类型词归一：gold → commodity（与 classify 的 _EN_TYPE 同源，避免「gold 支持不了」）
            typ = _EN_TYPE.get(typ.lower(), typ)
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
        return {"scene": "macro", "route": ("macro_pipeline", q, None)}
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
    from sources.route import code_domain_error, fetch

    # 代码域守卫：这条路径**先问盈米**（不经 route.fetch），所以 route 那层
    # 的守卫拦不到它。实测 `intent deep fund 600519` 会拿到盈米的
    # `{"ok": true, "message": "未识别到具体基金"}` 并 rc=0。
    # 用同一份判据（route.code_domain_error），不在这里另写一套。
    _err = code_domain_error("fund", target)
    if _err:
        return {"source": "fund", "kind": "fund", "ok": False, "data": None, "error": _err}

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
    elif kind == "macro_pipeline":
        # 宏观流动性：FRED 净流动性结构化通道优先（WALCL/TGA/ON RRP + SOFR），
        # 无 key 或失败时降级为 argo 检索兜底，不阻塞宏观查询。
        from sources import fred as fred_src

        res = fred_src.liquidity()
        if not res.get("ok") or not (res.get("data") or {}).get("net_liquidity"):
            res = argo_src.search(route[1], engine="nbs_stats")
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
