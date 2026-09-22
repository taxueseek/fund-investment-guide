#!/usr/bin/env python3
"""
基金分析 - 快照走 route.fetch（同花顺主路，ttskill 深取补充，失败回退东财）
输出：净值 + 业绩 + 持仓 + 经理 + 费率（对标 invest-fund 三关框架）
"""

# 让注解惰性求值：本模块有 `-> dict | None`（PEP 604），在 Python 3.9 上
# 会在**导入期**抛 `TypeError: unsupported operand type(s) for |`。
# 这不是理论问题：wrapper 在 .venv 缺失时回退系统 python3（macOS 自带 3.9.6），
# 实测 `import cmd_fund` 直接失败，`invest-cli fund ...` 整条命令不可用。
from __future__ import annotations

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
#
# 过滤器留在模块层，`import requests` 下沉到 query_eastmoney()：requests 的
# import 自耗时实测约 70ms，而它只服务东财**兜底**这一条路（主路走
# route.fetch：同花顺优先，ttskill 深取补充）。放在模块顶层等于每次
# `invest-cli fund` 都先白付 70ms。先后关系不受影响：模块导入即装过滤器，
# requests 的首次导入发生在第一次真正调用 query_eastmoney 时，始终在后。
warnings.filterwarnings("ignore", category=Warning, module=r"urllib3.*")

EASTMONEY_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/query"


def get_api_key():
    """env 优先，无则读用户级凭据文件（单一实现：sources/eastmoney.load_api_key）。"""
    from sources.eastmoney import load_api_key

    key = load_api_key()
    if not key:
        raise RuntimeError("未设置 EASTMONEY_APIKEY（可写入 ~/.config/invest-cli/eastmoney.env）")
    return key


def query_eastmoney(query: str) -> dict:
    import requests  # noqa: PLC0415 —— 见文件头「下沉 import」说明

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
    返回：[{ "entityName": ..., "列名": "最新值", ... }, ...]
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
                    row[col_name] = vals[0]
        if len(row) > 1:
            results.append(row)
    return results


def resolve_fund_code(keyword: str) -> str:
    # ⚠ 易方达蓝筹(精选) = 005827；110011 现为「易方达优质精选(QDII)」。
    # 旧映射把蓝筹指到 110011，在东财兜底路径会返回错误标的（仅 ttsskill/hithink 全挂时触发）。
    known = {
        "易方达蓝筹": "005827", "易方达蓝筹精选": "005827",
        "中欧医疗": "003096", "中欧医疗健康": "003096",
        "招商中证白酒": "161725",
        "富国天惠": "161005",
        "兴全趋势": "163402",
        "诺安成长": "320007",
    }
    if keyword.isdigit() and len(keyword) == 6:
        return keyword
    return known.get(keyword, keyword)


def _ttskill_deep(keyword: str) -> dict | None:
    """ttskill 深取字段（含可用性门槛与落盘缓存）；任何不满足都返回 None。

    深取是两次 ttskill 子进程调用（CLI 冷启动 + BASE_INFOS + HOLDING_INFO），
    实测 ~1.0-1.3s，而它提供的字段（同类分位/机构占比/经理在管）变动远慢于行情。
    不缓存时，即使主快照命中磁盘缓存，每次 `fund <code>` 仍要重付这一秒。
    只缓存成功结果：失败若也缓存，一次网络抖动会被放大成持续缺字段。
    """
    from _common import CACHE_TTL_FUNDAMENTAL, cache_get, cache_set

    # 先读深取缓存，**再**判可用性——顺序是这条路径上的性能关键点。
    #
    # 可用性判断要 load_registry() → `import yaml` + 解析配置（约 10-13ms）。
    # 而深取缓存里的字段（同类分位/机构占比/经理在管）本来就是「变动远慢于行情」
    # 那一批，命中时与 ttskill 此刻是否就绪无关。旧顺序把配置读取放在缓存之前，
    # 于是 `fund` 的**热路径**（快照已命中磁盘缓存）每次仍要付一遍 yaml：
    # 实测热跑 yaml 导入事件 19 次，而同结构的 `stock`/`us` 热跑是 0 次。
    # 独立审查据此指出「重库下沉对 fund 一分没省」，就是这一处顺序导致的。
    ckey = f"ttskill|{keyword}"
    hit = cache_get("deep", ckey, CACHE_TTL_FUNDAMENTAL)
    if isinstance(hit, dict) and hit:
        return hit

    from sources import load_registry
    from sources.registry import detect as detect_conf

    conf = load_registry().get("ttskill")
    if not conf or not detect_conf(conf)[0]:
        return None
    try:
        from sources import ttskill as tts_src

        res = tts_src.fund(keyword)
    except Exception:
        return None
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        return None
    deep = (res["data"] or {}).get("data") or {}
    if deep:
        cache_set("deep", ckey, deep)
    return deep or None


def fetch_fund_with_fallback(keyword: str) -> dict:
    """公募基金快照：route.pick 选源，整单回退。ttskill 就绪时深取补充。

    深取是独立子问题（同类分位/机构占比/波动/夏普等 hithink 不提供的字段），
    只并入主源缺失的键，不覆盖、不跨源拼接同一字段。深取失败静默跳过。

    主快照与深取是两条互不依赖的网络段，串行等于把两段等待相加
    （实测快照 ~1.2s + 深取 ~1.3s）；并发提交后总耗时收敛到两者最大值。
    """
    from concurrent.futures import ThreadPoolExecutor

    from sources.route import fetch, unwrap_snapshot

    # 代码域守卫（反向）在 route.fetch 里，与 `stock` 共用同一份判据——
    # 这里不再各写一遍：`stock` 有两条入口，分别加守卫实测漏掉了 `intent deep stock`。
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_snap = pool.submit(lambda: unwrap_snapshot(fetch("fund", keyword)))
        f_deep = pool.submit(_ttskill_deep, keyword)
        snap = f_snap.result()
        try:
            deep = f_deep.result()
        except Exception:
            deep = None
    if not deep or snap.get("source") == "ttskill":
        # 快照本身来自 ttskill 时，深取与它同源同字段，无需再并一次
        return snap
    existing = snap.get("data") or {}
    added = [k for k, v in deep.items() if k not in existing and v not in (None, "")]
    if not added:
        return snap
    snap["data"] = {**existing, **{k: deep[k] for k in added}}
    snap["deep_source"] = "ttskill"
    snap["warnings"] = list(snap.get("warnings") or []) + [
        f"深取字段（{'、'.join(added)}）来自 ttskill"
    ]
    return snap


def fetch_fund_data(code: str) -> dict:
    """基金完整数据（东财）。

    六组查询相互独立，串行会让六段 RTT 相加（实测最坏 6× 单次耗时）。
    并发取数不改变任何字段口径，只是不再叠加等待；
    单个查询失败时该组记为空表，与串行版本的降级行为完全一致。
    """
    from concurrent.futures import ThreadPoolExecutor

    queries = [
        f"{code}基金基本信息 基金名称 基金类型 成立日期 基金规模 基金管理人",
        f"{code}基金最新净值 近1月回报 近3月回报 近6月回报 近1年回报 近3年回报 今年来回报",
        f"{code}基金风险指标 最大回撤 波动率 夏普比率 卡玛比率",
        f"{code}基金费率 管理费率 托管费率 申购费率",
        f"{code}基金经理 经理姓名 管理年限 管理基金数量 总管理规模",
        f"{code}基金最新十大重仓股 重仓股名称 占净值比例",
    ]

    # 哨兵区分「取数失败」与「成功但无数据」：前者是传输问题，不能据此
    # 判定标的是否存在（否则某组恰好失败就会把正常基金误报为「未找到」）。
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
        r1, r2, r3, r4, r5, r6 = pool.map(_one, queries)

    if all(r is _FAILED for r in (r1, r2, r3, r4, r5, r6)):
        raise RuntimeError(f"东财取数失败（{code}）：六组查询均未成功，请稍后重试")

    t1 = [] if r1 is _FAILED else r1
    t2 = [] if r2 is _FAILED else r2
    t3 = [] if r3 is _FAILED else r3
    t4 = [] if r4 is _FAILED else r4
    t5 = [] if r5 is _FAILED else r5
    t6 = [] if r6 is _FAILED else r6
    _basic_failed = r1 is _FAILED

    basic = t1[0] if t1 else {}
    perf = t2[0] if t2 else {}
    risk = t3[0] if t3 else {}
    fees = t4[0] if t4 else {}
    manager = t5[0] if t5 else {}

    # 一致性校验：与 cmd_stock 同源问题——东财对未知代码会模糊匹配到别的
    # 基金并正常返回。但只有「基础信息查询**成功且为空**」才能判未找到；
    # 若该查询本身失败，那是传输问题，不能冒充「基金不存在」。
    if not basic:
        if _basic_failed:
            raise RuntimeError(
                f"东财取数失败（{code}）：基础信息查询未成功，无法确认标的，请稍后重试"
            )
        others = [t for t in (perf, risk, fees, manager, t6) if t]
        if others:
            got = others[0].get("entityName", "")
            raise ValueError(
                f"未找到基金「{code}」的基础信息"
                + (f"（东财模糊匹配到 {got}，已丢弃以免误导）" if got else "")
            )
        raise ValueError(f"未找到基金「{code}」的数据，请确认代码或名称")

    merged = {}
    for d in [basic, perf, risk, fees, manager]:
        for k, v in d.items():
            if k != "entityName" and v:
                merged[k] = v

    return {
        "code": code,
        "name": basic.get("基金名称", basic.get("entityName", code)),
        "timestamp": datetime.now().isoformat(),
        "data": merged,
        "holdings": t6,
        "raw_tables": {"basic": t1, "performance": t2, "risk": t3, "fees": t4, "manager": t5, "holdings": t6},
    }


def format_terminal(data: dict) -> str:
    lines = []
    d = data.get("data", {})
    h = data.get("holdings", [])
    name = data.get("name") or data.get("code") or "未知基金"

    lines.append(f"\n{'=' * 60}")
    lines.append(f"  {name}（{data.get('code', '-')}）— 基金快照")
    lines.append(f"{'=' * 60}")

    # adapter 已经算出的告警必须在终端出现（与 cmd_stock 同一条纪律：
    # payload 里写了原因，终端层丢掉，用户就只能看到一张空表）。
    note = data.get("note")
    if note:
        lines.append(f"\n  提示: {note}")

    # 基础
    lines.append(f"\n  {'基础信息':<14} {'数值':>16}")
    lines.append(f"  {'-' * 32}")
    for api_key, label in [("基金类型", "类型"), ("成立日期", "成立日期"), ("基金规模", "规模"), ("基金管理人", "管理人"), ("机构占比", "机构占比")]:
        val = d.get(api_key)
        if val is None or val == "":
            val = "-"
        elif label == "规模" and isinstance(val, (int, float)) and val >= 1e8:
            val = f"{val / 1e8:.2f}亿"
        lines.append(f"  {label:<14} {str(val):>16}")

    # 业绩
    perf_keys = [
        ("单位净值", "最新净值"), ("近1月回报", "近1月"), ("近3月回报", "近3月"),
        ("近6月回报", "近6月"), ("近1年回报", "近1年"), ("近3年回报", "近3年"), ("今年来回报", "今年来"),
        ("近1年同类分位", "近1年同类分位"), ("近3年同类分位", "近3年同类分位"),
    ]
    has_perf = any(d.get(k) for k, _ in perf_keys)
    if has_perf:
        lines.append(f"\n  {'业绩表现':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in perf_keys:
            val = d.get(api_key)
            if val is not None and val != "":
                lines.append(f"  {label:<14} {str(val):>16}")

    # 风险
    risk_keys = [("最大回撤", "最大回撤"), ("波动率", "波动率"), ("夏普比率", "夏普比率"), ("卡玛比率", "卡玛比率")]
    has_risk = any(d.get(k) for k, _ in risk_keys)
    if has_risk:
        lines.append(f"\n  {'风险指标':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in risk_keys:
            val = d.get(api_key)
            if val is not None and val != "":
                lines.append(f"  {label:<14} {str(val):>16}")

    # 费率
    fee_keys = [("管理费率", "管理费"), ("托管费率", "托管费"), ("申购费率", "申购费")]
    has_fees = any(d.get(k) for k, _ in fee_keys)
    if has_fees:
        lines.append(f"\n  {'费率结构':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in fee_keys:
            val = d.get(api_key)
            if val:
                lines.append(f"  {label:<14} {str(val):>16}")

    # 经理
    mgr_keys = [("经理姓名", "经理"), ("管理年限", "管理年限"), ("总管理规模", "管理规模")]
    has_mgr = any(d.get(k) for k, _ in mgr_keys)
    if has_mgr:
        lines.append(f"\n  {'基金经理':<14} {'数值':>16}")
        lines.append(f"  {'-' * 32}")
        for api_key, label in mgr_keys:
            val = d.get(api_key)
            if val:
                lines.append(f"  {label:<14} {str(val):>16}")

    # 重仓
    if h:
        lines.append(f"\n  十大重仓股:")
        lines.append(f"  {'-' * 40}")
        for stock in h[:10]:
            sname = stock.get("stock_name") or stock.get("entityName") or ""
            ratio = stock.get("hold_ratio")
            if ratio is None:
                ratio = stock.get("占净值比例", "")
                if not ratio:
                    for k, v in stock.items():
                        if k not in ("entityName", "stock_name", "ticker", "thscode", "investment_rank") and v not in (None, ""):
                            ratio = v
                            break
            lines.append(f"  {sname:<20} {str(ratio):>10}")

    src = data.get("source_label") or data.get("source") or "东方财富"
    lines.append(f"\n  数据时间: {data.get('timestamp', '-')}")
    lines.append(f"  数据来源: {src}")
    warns = data.get("warnings") or []
    if warns:
        lines.append(f"  警告: {'; '.join(warns)}")
    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="基金分析")
    parser.add_argument("keyword", help="基金代码或名称")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    try:
        data = fetch_fund_with_fallback(args.keyword)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_terminal(data))


if __name__ == "__main__":
    main()
