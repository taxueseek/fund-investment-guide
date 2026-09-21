#!/usr/bin/env python3
"""
A股/港股分析 - 快照走 route.fetch（同花顺主路，失败整单回退东财）
输出：实时行情 + 估值指标 + 财务数据（对标 invest-stock 三关框架）
"""

import sys
import json
import warnings
from datetime import datetime

# urllib3 2.x 在 LibreSSL 环境下导入时 emit NotOpenSSLWarning，直接写 stderr。
# CLI 的 stderr 是错误通道，不该被库噪音占据（agent 解析错误信息会被带偏）。
# 必须在 import requests **之前**装过滤器，否则告警已在导入期发出。
#
# 注意 category 必须写 Warning 而不是 UserWarning：该告警的继承链是
# NotOpenSSLWarning → SecurityWarning → HTTPWarning → Warning，
# 与 UserWarning 无继承关系，用 UserWarning 或 message 正则都拦不住
# （实测两者均无效，只有按 Warning + module 才生效）。
warnings.filterwarnings("ignore", category=Warning, module=r"urllib3.*")
import requests  # noqa: E402

EASTMONEY_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"


def get_api_key():
    """env 优先，无则读用户级凭据文件（单一实现：sources/eastmoney.load_api_key）。"""
    from sources.eastmoney import load_api_key

    key = load_api_key()
    if not key:
        raise RuntimeError("未设置 EASTMONEY_APIKEY（可写入 ~/.config/invest-cli/eastmoney.env）")
    return key


def query_eastmoney(query: str) -> dict:
    """调用东方财富 API，返回原始响应"""
    resp = requests.post(
        EASTMONEY_URL,
        headers={"apikey": get_api_key(), "Content-Type": "application/json"},
        json={"toolQuery": query},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_tables(raw: dict) -> list[dict]:
    """
    解析东财 API 返回的表格数据。

    东财返回结构：
    raw.data.data.searchDataResultDTO.dataTableDTOList[].{
      entityName: "贵州茅台(600519.SH)",
      nameMap: { "326809": "总市值", "328664": "市净率PB", ... },
      table: { "326809": ["1.616万亿", "1.642万亿", ...], ... }
    }

    返回：[{ "entityName": ..., "总市值": "1.616万亿", "市净率PB": "5.964倍", ... }, ...]
    每个 dict 的值为最新（第一个）值。
    """
    try:
        dtos = raw["data"]["data"]["searchDataResultDTO"]["dataTableDTOList"]
    except (KeyError, TypeError):
        return []

    results = []
    for item in dtos:
        name_map = item.get("nameMap", {})
        table = item.get("table", {})
        row = {"entityName": item.get("entityName", "")}
        for col_id, col_name in name_map.items():
            if col_id in table:
                vals = table[col_id]
                if isinstance(vals, list) and len(vals) > 0:
                    row[col_name] = vals[0]  # 最新值
        if len(row) > 1:  # 至少有 entityName + 一个数据列
            results.append(row)
    return results


def resolve_code(keyword: str) -> str:
    """名称 → 代码映射"""
    known = {
        "茅台": "600519", "贵州茅台": "600519",
        "五粮液": "000858", "宁德时代": "300750",
        "中国平安": "601318", "招商银行": "600036",
        "腾讯": "00700", "阿里巴巴": "09988",
        "美团": "03690", "京东": "09618",
        "比亚迪": "002594", "工商银行": "601398",
    }
    if keyword.isdigit() and len(keyword) in (5, 6):
        return keyword
    return known.get(keyword, keyword)


def _looks_like_hk(keyword: str) -> bool:
    """与 cmd_intent/hithink 共用同一 HK 判定（单一实现）。"""
    from sources.hithink import looks_like_hk

    t = (keyword or "").strip()
    # 6 位纯数字必属 A 股/基金体系，先短路，避免 resolve_code 前缀误判
    if t.isdigit() and len(t) == 6:
        return False
    if looks_like_hk(t):
        return True
    code = resolve_code(t)
    return code.isdigit() and len(code) == 5


def fetch_stock_with_fallback(keyword: str) -> dict:
    """A 股/港股快照：由 route.pick 按 yaml×真方法×可用性选源，整单回退。"""
    from sources.route import fetch, unwrap_snapshot

    market = "hk" if _looks_like_hk(keyword) else "a"
    return unwrap_snapshot(fetch("stock", keyword, market=market))


def _name_matches_code(entity_name: str, code: str) -> bool:
    """东财 entityName（如「贵州茅台(600519.SH)」）是否与查询代码确有对应。

    这是「行情缺失但财务可用」情形的最后一道闸门：只有在实体名里能找到
    用户查询的代码才算匹配到同一标的，避免把模糊匹配到的别家公司放行。

    比较时归一化：查询侧去掉非字母数字（港股/美股可能带点号），
    实体侧同样归一化后做子串判断；代码长度 < 2 时一律不放行（过于宽松）。
    """
    import re as _re

    norm_code = _re.sub(r"[^0-9A-Za-z]", "", (code or "")).upper()
    if len(norm_code) < 2:
        return False
    norm_name = _re.sub(r"[^0-9A-Za-z]", "", (entity_name or "")).upper()
    return norm_code in norm_name


def fetch_stock_data(code: str) -> dict:
    """获取股票完整数据（东财）。

    三组查询（行情/财务/年报）相互独立，串行会让三段 RTT 相加。
    并发取数不改变任何字段口径，只是不再叠加等待时间。
    单个查询失败时该组记为空表，与串行版本的降级行为完全一致。
    """
    from concurrent.futures import ThreadPoolExecutor

    queries = [
        f"{code}股票最新行情 市盈率PE 市净率PB 总市值 收盘价 开盘价",
        f"{code}股票财务指标 净资产收益率ROE 销售毛利率 销售净利率 资产负债率 每股收益EPS",
        f"{code}股票年报 营业收入 净利润 营收增速 净利润增速 经营活动产生的现金流量净额",
    ]

    # 用哨兵区分「取数失败」与「取数成功但没有数据」——两者绝不能混为一谈：
    #   · 成功但空  → 说明东财没匹配到这个标的（可据此判未找到）；
    #   · 请求失败  → 是传输层问题，与标的是否存在无关，不能据此下任何结论。
    # 旧实现把两者都记成 []，会导致「行情那一组恰好失败」时把一只正常股票
    # 误报为「未找到」，甚至编出「模糊匹配到别家」的错误说明。
    _FAILED = object()

    def _one(q: str):
        """单个查询：成功返回行列表（可能为空），失败返回 _FAILED。"""
        try:
            return parse_tables(query_eastmoney(q))
        except RuntimeError as e:
            if "EASTMONEY_APIKEY" in str(e):
                raise  # 配置缺失：必须让调用方看见真实原因
            return _FAILED
        except Exception:
            return _FAILED

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        r1, r2, r3 = pool.map(_one, queries)

    # 三组全失败 → 是取数问题，如实上报，不要伪装成「标的不存在」
    if r1 is _FAILED and r2 is _FAILED and r3 is _FAILED:
        raise RuntimeError(f"东财取数失败（{code}）：三组查询均未成功，请稍后重试")

    t1 = [] if r1 is _FAILED else r1
    t2 = [] if r2 is _FAILED else r2
    t3 = [] if r3 is _FAILED else r3
    # 语义修正：只有行情组（r1）的失败才影响「能否确认标的」；
    # r2/r3 是财务/年报组的传输失败，与实体一致性判断无关（旧写法会在
    # 财务组偶发失败时把可放行的停牌场景误拦）。与 cmd_fund 的 _basic_failed 对齐。
    _quote_failed = r1 is _FAILED

    # 合并：取每个结果的第一行（最新数据）
    quote = t1[0] if t1 else {}
    financial = t2[0] if t2 else {}
    annual = t3[0] if t3 else {}

    # 一致性校验：东财对未知标的会**模糊匹配到另一家公司**并正常返回数据。
    # 实测：查「不存在的公司XYZ」→ 返回 Block Inc-A(XYZ.N) 的 ROE/毛利率，
    # 且 quote 表为空、financial 表非空，旧实现把它的财务挂到用户输入的
    # name 下并以 exit=0 输出——用户会以为拿到了自己查的那家公司。
    #
    # 判据必须同时满足三条才放行「行情缺失但有财务」的情形，缺一不可：
    #   ① 行情那一组请求**成功**（失败是传输问题，不能据此下任何结论）；
    #   ② 至少**两张**非行情表给出 entityName，且彼此一致；
    #   ③ 该 entityName 与用户查询的代码/名称**确有对应关系**。
    # 单张表有值不足以放行——「不存在的公司XYZ」正是只有 financial 一张表
    # 有值（实测），只数一张表就会把 Block Inc-A 的数据当成用户要的标的。
    if not quote:
        if _quote_failed:
            raise RuntimeError(
                f"东财取数失败（{code}）：行情查询未成功，无法确认标的，请稍后重试"
            )
        others = [d for d in (financial, annual) if d]
        names = [d.get("entityName", "") for d in others if d.get("entityName")]
        distinct = set(names)
        # 需要 ≥2 张表且名称一致，且该名称与查询代码确有关联，才认为匹配到同一标的
        if len(names) >= 2 and len(distinct) == 1 and _name_matches_code(distinct.pop(), code):
            snapshot_name = names[0]
            merged = {}
            for d in others:
                for k, v in d.items():
                    if k != "entityName" and v:
                        merged[k] = v
            return {
                "code": code,
                "name": snapshot_name,
                "timestamp": datetime.now().isoformat(),
                "data": merged,
                "raw_tables": {"quote": t1, "financial": t2, "annual": t3},
                "note": "行情缺失（可能停牌/无成交），以下为财务口径数据",
            }
        if others:
            got = others[0].get("entityName", "")
            raise ValueError(
                f"未找到标的「{code}」的行情数据"
                + (f"（东财模糊匹配到 {got}，已丢弃以免误导）" if got else "")
            )
        raise ValueError(f"未找到标的「{code}」的数据，请确认代码或名称")

    # 合并所有字段到一个 flat dict
    merged = {}
    for d in [quote, financial, annual]:
        for k, v in d.items():
            if k != "entityName" and v:
                merged[k] = v

    return {
        "code": code,
        "name": quote.get("entityName", code),
        "timestamp": datetime.now().isoformat(),
        "data": merged,
        "raw_tables": {"quote": t1, "financial": t2, "annual": t3},
    }


def format_terminal(data: dict) -> str:
    lines = []
    d = data.get("data", {})
    name = data.get("name") or data.get("code") or "未知标的"

    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {name} — 行情快照")
    lines.append(f"{'=' * 60}")

    # 行情
    quote = data.get("quote") or {}
    valuation = data.get("valuation") or {}
    quote_keys = [
        ("收盘价", "收盘价", quote.get("last")), ("开盘价", "开盘价", quote.get("open")),
        ("昨收", "昨收", quote.get("prev") or d.get("昨收")),
        ("市盈率PE(TTM)", "PE(TTM)", valuation.get("pe_ttm")), ("市净率PB", "PB", valuation.get("pb_mrq")),
        ("总市值", "总市值", None),
    ]
    lines.append(f"\n  {'指标':<14} {'数值':>16}")
    lines.append(f"  {'-' * 32}")
    for api_key, label, structured in quote_keys:
        val = d.get(api_key)
        if val in (None, "", "-"):
            val = structured
        lines.append(f"  {label:<14} {str(val if val is not None else '-'):>16}")

    # 财务
    fin_keys = [
        ("净资产收益率ROE", "ROE"), ("销售毛利率", "毛利率"),
        ("销售净利率", "净利率"), ("资产负债率", "负债率"),
        ("每股收益EPS", "EPS"),
    ]
    has_fin = any(d.get(k) for k, _ in fin_keys)
    if has_fin:
        lines.append(f"\n  {'财务指标':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in fin_keys:
            val = d.get(api_key, "-")
            lines.append(f"  {label:<14} {str(val):>16}")

    # 年报
    ann_keys = [
        ("营业收入", "营业收入"), ("净利润", "净利润"),
        ("经营活动产生的现金流量净额", "经营现金流"),
    ]
    has_ann = any(d.get(k) for k, _ in ann_keys)
    if has_ann:
        lines.append(f"\n  {'年报数据':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in ann_keys:
            val = d.get(api_key, "-")
            lines.append(f"  {label:<14} {str(val):>16}")

    hist = data.get("financials_history") or []
    if hist:
        lines.append(f"\n  {'年度':<8}{'营收':>14}{'净利润':>14}{'毛利率':>10}{'ROE':>10}")
        lines.append(f"  {'-' * 56}")
        for row in hist:
            year = row.get("fiscal_year", "-")
            rev = row.get("revenue")
            np_ = row.get("net_profit")
            gm = row.get("gross_margin")
            roe = row.get("roe_ending")
            fin = data.get("financials") or {}
            if fin.get("fiscal_year") == year and fin.get("roe") is not None:
                roe = fin.get("roe")
            rev_s = f"{rev / 1e8:.2f}亿" if isinstance(rev, (int, float)) else "-"
            np_s = f"{np_ / 1e8:.2f}亿" if isinstance(np_, (int, float)) else "-"
            gm_s = f"{gm:.1f}%" if isinstance(gm, (int, float)) else "-"
            roe_s = f"{roe:.1f}%" if isinstance(roe, (int, float)) else "-"
            lines.append(f"  {str(year):<8}{rev_s:>14}{np_s:>14}{gm_s:>10}{roe_s:>10}")

    src = data.get("source_label") or data.get("source") or "东方财富"
    lines.append(f"\n  数据时间: {data.get('timestamp', '-')}")
    lines.append(f"  数据来源: {src}")
    warns = data.get("warnings") or []
    if warns:
        lines.append(f"  警告: {'; '.join(warns)}")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="A股/港股分析")
    parser.add_argument("keyword", help="股票代码或名称，如 600519 或 茅台")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    try:
        data = fetch_stock_with_fallback(args.keyword)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
