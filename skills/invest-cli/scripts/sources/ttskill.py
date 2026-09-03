#!/usr/bin/env python3
"""天天基金官方 ttskill 适配器（invest-cli 数据源）。

能力：公募基金结构化快照（默认深取层，对应 invest-fund/references/data-pipeline.md）：
  - 名称/代码解析（TTFUND_SEARCH）
  - 详情+业绩+风险族（夏普/波动/回撤+成立来）+费率梯度+业绩基准（TTFUND_BASE_INFOS）
  - 十大重仓/行业/资产配置 + 报告期（TTFUND_HOLDING_INFO）

约定（与 data-pipeline.md 互为镜像，改映射必须两边同步）：
  - 返回信封对齐 route.fetch：{source, kind, ok, data, error}
  - 快照 schema 对齐 cmd_fund.format_terminal（data 用中文键；holdings 用 stock_name/hold_ratio）
  - 全部走 ttskill CLI，不手拼 token/cookie；cli_login_required → 抛错让 route 落到 hithink/eastmoney

口径（110011 实测 2026-09-03，勿按旧文档改）：
  - BASE：body.expansion.comprehensive_info.fund_profile_overview.{FTYPE,SHORTNAME,FULLNAME,ENDNAV(元),ESTABDATE,JJGS,JJJL,BENCH}
  - 风险在 unique_info[0]（数组首元素，不是对象）；卡玛无直出 = 近1年收益 ÷ |近1年最大回撤|
  - 阶段涨幅 period_increase[]：title∈{Y=近1月,3Y=近3月,6Y=近6月,1N=近1年,2N,3N,5N,JN=今年来,LN=成立来}，Z=近1周不展示
  - 费率 purchase/redeem/service 在 body.expansion.trade_info.fee_rates；管理费/托管费接口不返回
  - HOLDING 有 body.data 包装；QDII 等顶层 top_holdings.stocks 可能为空 → 从 data.periods[-1] 取
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from typing import Any

SOURCE_LABEL = "天天基金 ttskill"
CLI = "ttskill"
INVOKE_TIMEOUT = 45

# period_increase.title → 展示标签（110011 实测值反推；Z=近1周不进快照）
PERIOD_LABELS = {
    "Y": "近1月回报", "3Y": "近3月回报", "6Y": "近6月回报",
    "1N": "近1年回报", "2N": "近2年回报", "3N": "近3年回报",
    "5N": "近5年回报", "JN": "今年来回报", "LN": "成立来回报",
}
RISK_DISPLAY = {  # unique_info[0] 键 → cmd_fund 展示键
    "STDDEV1": "波动率", "SHARP1": "夏普比率", "MAXRETRA1": "最大回撤",
}


def detect() -> tuple[bool, str]:
    """登录态探测：token 存在且未过期才算可用（过期时 status 文本仍显示
    'auth token: present'，仅按文本匹配会误判可用 → 必须看 is_expired）。"""
    exe = shutil.which(CLI)
    if not exe:
        return False, f"{CLI} 不在 PATH"
    try:
        proc = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"{CLI} status 失败: {e}"
    try:
        st = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, f"{CLI} status 非 JSON: {(proc.stdout or '')[:120]}"
    auth = st.get("auth") or {}
    if not auth.get("has_token"):
        return False, "ttskill 未登录，执行 ttskill login"
    cu = (auth.get("current_user") or {})
    if cu.get("is_expired") is True:
        return False, f"ttskill token 已过期（{cu.get('expires_at', '?')}），执行 ttskill login --env prod --force"
    skills = st.get("skills") or []
    if not skills:
        return False, "ttskill 已登录但无业务包，先 ttskill install"
    return True, f"ttskill 已登录 用户:{cu.get('customer_no_masked', '?')}"


def _invoke(skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """ttskill invoke → body 信封。失败抛 RuntimeError。"""
    exe = shutil.which(CLI)
    if not exe:
        raise RuntimeError(f"{CLI} 不在 PATH")
    proc = subprocess.run(
        [exe, "invoke", skill_id, "--action", "query", "--body", json.dumps(body, ensure_ascii=False)],
        capture_output=True, text=True, timeout=INVOKE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{CLI} invoke {skill_id} 退出码 {proc.returncode}: {(proc.stderr or '').strip()[:200]}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"{CLI} invoke {skill_id} 非 JSON 输出: {proc.stdout[:200]}")
    if not payload.get("code") == 0:
        raise RuntimeError(f"{CLI} invoke {skill_id} 失败: {str(payload.get('message'))[:200]}")
    raw = ((payload.get("data") or {}).get("raw_result") or {}).get("body") or {}
    ec = raw.get("errorCode")
    # 成功码各包不一：BASE/HOLDING 用 0，GOLD 等用 200；以 success=false 或 code∉{0,200} 判失败
    if raw.get("success") is False or (ec is not None and ec not in (0, 200)):
        raise RuntimeError(f"{skill_id} 业务失败: {(raw.get('message') or raw.get('firstError') or ec or '')[:200]}")
    return raw


def _num(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _common_run(a: str, b: str) -> int:
    """最长公共连续子串长度（防模糊解析 fail-open：垃圾名会被服务端配到无关基金）。"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def resolve_fcode(keyword: str) -> tuple[str, str]:
    """名称/代码 → (fcode, name)。6 位代码直通；名称 SEARCH 结果必须与查询相关。"""
    kw = (keyword or "").strip()
    if kw.isdigit() and len(kw) == 6:
        return kw, kw
    raw = _invoke("TTFUND_SEARCH", {"query": kw, "search_type": "fund", "page_index": 1, "page_size": 5})
    cands = (((raw.get("data") or {}).get("candidates")) or [])
    threshold = max(2, min(3, sum(1 for ch in kw if "\u4e00" <= ch <= "\u9fff")))
    for c in cands:
        name = c.get("name") or ""
        if (c.get("display_code") or "").isdigit() and _common_run(kw, name) >= threshold:
            return c["display_code"], name or kw
    raise RuntimeError(f"基金搜索无相关候选: {kw}")


def _base_snapshot(code: str) -> dict[str, Any]:
    raw = _invoke("TTFUND_BASE_INFOS", {"fcode": code, "nav_range": "n"})
    ci = (raw.get("expansion") or {}).get("comprehensive_info") or {}
    fpo = ci.get("fund_profile_overview") or {}
    ui = (ci.get("unique_info") or [{}])[0] if isinstance(ci.get("unique_info"), list) else (ci.get("unique_info") or {})
    fees = ((raw.get("expansion") or {}).get("trade_info") or {}).get("fee_rates") or {}

    d: dict[str, Any] = {}
    for k, label in [("FTYPE", "基金类型"), ("ESTABDATE", "成立日期"), ("JJGS", "基金管理人")]:
        if fpo.get(k):
            d[label] = fpo[k]
    if fpo.get("SHORTNAME"):
        d["基金名称"] = fpo["SHORTNAME"]
    if fpo.get("ENDNAV") is not None:  # 元 → 保留数值，展示层 ≥1e8 自动换亿
        d["基金规模"] = _num(fpo["ENDNAV"])
    for t, label in PERIOD_LABELS.items():
        for row in ci.get("period_increase") or []:
            if str(row.get("title")) == t and row.get("syl") is not None:
                d[label] = _num(row["syl"])
                break
    for key, label in RISK_DISPLAY.items():
        if ui.get(key) is not None:
            d[label] = _num(ui[key])
    y1 = d.get("近1年回报")
    mdd = d.get("最大回撤")
    if y1 is not None and mdd is not None and mdd:
        # 卡玛 = 近1年收益 ÷ |最大回撤幅度|：带符号（亏损期应为负），不能用 abs 抹掉
        d["卡玛比率"] = round(y1 / abs(mdd), 2)
    mgr = (fpo.get("JJJL") or "").split(",")[0].strip()
    if mgr:
        d["经理姓名"] = mgr
    if fees.get("purchase"):
        rates = [r for r in fees["purchase"] if isinstance(r, dict)]
        if rates:
            rate = rates[0].get("rate")
            src = rates[0].get("source")
            d["申购费率"] = rate if rate is not None else src
    return d


def _holding_list(code: str) -> tuple[list[dict[str, Any]], str, str]:
    raw = _invoke("TTFUND_HOLDING_INFO", {"fund_id": code, "holding_type": "stock", "period_mode": "latest"})
    data = raw.get("data") or {}
    ho = data.get("holding_overview") or {}
    report_date = ho.get("report_date") or ""
    periods = data.get("periods") or []
    top = data.get("top_holdings") or {}
    stocks = top.get("stocks") or []
    industry = data.get("industry_allocation") or []
    if not stocks and periods:
        latest = periods[-1]
        stocks = ((latest.get("top_holdings") or {}).get("stocks")) or []
        industry = latest.get("industry_allocation") or industry
        report_date = latest.get("report_date") or report_date
    industry_ratio = ""
    if industry:
        top_ind = max(industry, key=lambda r: _num(r.get("ZJZBL")) or 0)
        industry_ratio = f"{top_ind.get('HYMC', '')} {top_ind.get('ZJZBL', '')}%"
    rows = []
    for s in stocks[:10]:
        rows.append({
            "entityName": s.get("GPJC", ""),
            "stock_name": s.get("GPJC", ""),
            "hold_ratio": _num(s.get("JZBL")),
            "change": s.get("PCTNVCHGTYPE", ""),
        })
    return rows, report_date, industry_ratio


def invoke_scene(skill_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """通用场景透传（intent 等上层用）：调官方业务包并原样返回 body。"""
    try:
        raw = _invoke(skill_id, body)
        return {"source": "ttskill", "kind": skill_id, "ok": True, "data": raw, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"source": "ttskill", "kind": skill_id, "ok": False, "data": None, "error": str(e)}


def fund(keyword: str) -> dict[str, Any]:
    """fund 数据源入口：route.fetch 整单调用，失败抛异常由 route 回退。"""
    try:
        code, name = resolve_fcode(keyword)
        d = _base_snapshot(code)
        holdings, report_date, industry = _holding_list(code)
        if not d.get("基金类型"):
            d["基金类型"] = "未知（ttskill 未返回类型）"
        data = {
            "code": code,
            "name": name if not name.isdigit() else d.get("基金名称") or name,
            "timestamp": datetime.now().isoformat(),
            "source_label": SOURCE_LABEL,
            "warnings": [
                "管理费/托管费 ttskill 不返回，需 f10 档案页补查",
                f"持仓报告期 {report_date or '未知'}（滞后一季属正常）",
            ] if report_date else ["报告期未返回"],
            "data": d,
            "holdings": holdings,
        }
        if report_date:
            data["report_date"] = report_date
        if industry:
            data["top_industry"] = industry
        return {"source": "ttskill", "kind": "fund", "ok": True, "data": data, "error": None}
    except Exception as e:  # noqa: BLE001 —— 路由层需要字符串化错误以回退
        return {"source": "ttskill", "kind": "fund", "ok": False, "data": None, "error": str(e)}


if __name__ == "__main__":  # 快速自检：python3 sources/ttskill.py 110011
    code = sys.argv[1] if len(sys.argv) > 1 else "110011"
    print(json.dumps(fund(code), ensure_ascii=False, indent=2, default=str)[:1500])
