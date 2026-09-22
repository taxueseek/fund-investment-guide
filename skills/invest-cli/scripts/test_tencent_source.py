#!/usr/bin/env python3
"""腾讯行情适配器回归测试 — 全部离线（真实响应样本已落盘在 tencent_samples.json）。

三层断言，缺一不可：

1. **口径表锁定**：`_QT_MAP` 里每个下标都是「用独立源核对过」才登记的。这里把
   核对值写成断言，任何人改动下标都会红。核心是港股换手率那条 —— 它是被移植
   代码里真实存在的错值（原实现单表 [38]，港股恒为 0，真值 0.78%），
   没有这条断言，同一个 bug 会在移植时悄悄回来。
2. **边界语义**：传输故障必须是 `ok=False`，不能降级成空结果（原实现 `_never_raise`
   的做法）。这条用「让 HTTP 抛错」来验，回滚成空结构即失败。
3. **链路位置**：腾讯在 us 链必须在 bitget **之前**、在 yfinance **之后**；
   在 stock 链必须在富源之后。位置错了不会报错，只会让快照悄悄退化成纯行情
   （能力降级）或让兜底位回到代币价源。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sources import route, tencent

_SAMPLES = json.loads((Path(__file__).resolve().parent / "tencent_samples.json")
                      .read_text(encoding="utf-8"))


def _rows(code: str) -> list[dict]:
    """把落盘的真实响应喂给解析器（不联网）。"""
    rows = []
    for line in _SAMPLES[code].splitlines():
        row = tencent._parse_qt_line(line)
        if row:
            rows.append(row)
    return rows


def _row(code: str) -> dict:
    rows = _rows(code)
    assert rows, f"样本 {code} 解析不出任何行"
    return rows[0]


# ── ① 口径表锁定：用**具名独立源**逐字段反查 ────────────────────────────────
#
# 这里不写「我断言 PE 是 19.25」这种只锁数值的句子 —— 那样锁的是**值**，不是**含义**。
# 首版就是这么写的：47/48 被写成 52周高低，而它们其实是涨停/跌停价，测试照样绿。
#
# 现在改成结构性校验：fixture 里同时存了 qt 原始行与 **westock CLI 的具名列**
# （`_cliq_<code>`，同一时刻抓取，48 个列名如 price/pe_ratio/high_52week）。
# 对映射表里每个字段，断言「qt 取出来的值 == CLI 那个具名列的值」——
# 下标写错、含义写错、单位写错，都会直接红。

_QT_MAP_TESTS = {
    "sh600519": ["amount", "turnover_rate", "pe_ttm", "range_pct", "mktcap_circ", "mktcap",
                 "pb", "price_ceiling", "price_floor", "volume_ratio", "avg_price",
                 "pe_fwd", "pe_lyr", "chg_ytd", "chg_5d", "dividend_ttm", "w52_high",
                 "w52_low", "chg_10d", "chg_20d", "chg_60d"],
    "hk00700": ["amount", "range_pct", "mktcap_circ", "mktcap", "dividend_ttm", "w52_high",
                "w52_low", "volume_ratio", "pe_ttm", "pb", "turnover_rate", "chg_ytd",
                "chg_5d", "chg_10d", "chg_20d", "chg_60d", "avg_price"],
    "usAAPL": ["amount", "turnover_rate", "pe_ttm", "range_pct", "mktcap_circ", "mktcap",
               "w52_high", "w52_low", "pb", "dividend_ttm", "chg_ytd", "chg_5d", "chg_10d",
               "chg_20d", "chg_60d", "volume_ratio", "avg_price"],
}
# 字段名 → CLI 具名列（CLI 的列名就是「含义」的定义）
_CLI_COLUMN = {
    "amount": "amount", "turnover_rate": "turnover_rate", "pe_ttm": "pe_ratio",
    "range_pct": "range_pct", "mktcap_circ": "circulating_market_cap",
    "mktcap": "total_market_cap", "pb": "pb_ratio", "price_ceiling": "price_ceiling",
    "price_floor": "price_floor", "volume_ratio": "volume_ratio", "avg_price": "avg_price",
    "pe_fwd": "pe_fwd", "pe_lyr": "pe_lyr", "chg_ytd": "chg_ytd", "chg_5d": "chg_5d",
    "dividend_ttm": "dividend_ratio_ttm", "w52_high": "high_52week", "w52_low": "low_52week",
    "chg_10d": "chg_10d", "chg_20d": "chg_20d", "chg_60d": "chg_60d",
}


def _cli(code: str) -> dict:
    """CLI 的具名列（含义真源）。"""
    return _SAMPLES[f"_cliq_{code}"]


@pytest.mark.parametrize("code", list(_QT_MAP_TESTS))
def test_map_matches_named_cli_columns(code):
    """映射表里每个字段都必须等于 CLI 同名/同义列的取值。

    这条把「口径表正确性」从人工核对变成机器校验：任何下标改动、任何市场的
    位置差异（同一个数在不同市场含义不同）都会在这里暴露。
    """
    row = _row(code)
    cli = _cli(code)
    for field in _QT_MAP_TESTS[code]:
        col = _CLI_COLUMN[field]
        want = cli.get(col)
        assert want not in (None, "", "---"), f"CLI 列 {col} 在样本里没有值"
        got = row.get(field)
        assert got is not None, f"{code}.{field}（CLI 列 {col}）没解析出来"
        if field == "amount" and code == "sh600519":
            # A股接口给「万元」且已取整（308853），×1e4 后与 CLI 的元值
            # 3088526148 差 3852（0.00013%）——这是**源的精度上限**，不是换算错。
            # 故按相对量断言，并在注释里留下这个差值的来源，避免后人误当缺陷。
            assert abs(got - float(want)) / float(want) < 1e-3, f"{code}.amount {got} != {want}"
        else:
            assert abs(float(got) - float(want)) <= max(abs(float(want)) * 1e-4, 1e-6), \
                f"{code}.{field}: qt={got} 与 CLI[{col}]={want} 不一致"


def test_per_market_map_really_differs_per_market():
    """同一个下标在不同市场是**不同的量**；用真实样本证明分表不是多余。

    实测（同一时刻）：
        [47] A股=涨停价 1377.83 / 港股=股息率TTM 1.18
        [38] A股=换手率 0.20 / 港股=0（这一位港股没有值）
        [57] A股=成交额(万元) / 港股=市盈率 15.15 / 美股=ROE 148.75
    """
    a, hk, us = _row("sh600519"), _row("hk00700"), _row("usAAPL")
    assert a["price_ceiling"] == 1377.83 and hk.get("price_ceiling") is None
    assert abs(hk["dividend_ttm"] - 1.18) < 1e-6
    assert a["turnover_rate"] == 0.2 and hk["turnover_rate"] == 0.78 and us["turnover_rate"] == 0.24


def test_unknown_indices_would_break_the_mapping():
    """反证：把某个市场的表换成另一个市场的，断言必须失败。

    这条用来证伪「其实一张表也能用」——如果单表可行，说明上面那组断言没鉴别力。
    """
    src = tencent._QT_MAP["a"]["w52_high"]        # A股 52周高在 67
    assert src == 67, "A股 52周高应为 67（CLI high_52week）"
    assert tencent._QT_MAP["hk"]["w52_high"] == 48, "港股 52周高在 48（同一含义换了下标）"
    assert tencent._QT_MAP["a"]["price_ceiling"] == 47 and "price_ceiling" not in tencent._QT_MAP["hk"]


def test_hk_turnover_rate_is_not_zero():
    """港股换手率回归锁：被移植实现此处恒为 0.0（错值），真值 0.78%。

    港股与A股的换手率**不在同一下标**（A股 [38]、港股 [59]），单表实现必然二选一错。
    """
    r = _row("hk00700")
    assert r["turnover_rate"] == 0.78, r["turnover_rate"]
    assert r["turnover_rate"] != 0.0


def test_hk_amount_is_already_yuan():
    """港/美成交额已是元，**不能**再乘 1e4（否则差 4 个数量级）。"""
    r = _row("hk00700")
    assert 3.2e10 < r["amount"] < 3.3e10, r["amount"]
    assert _row("sh600519")["amount"] < 1e10      # A股原样是万元，差 1e4


def test_us_values_match_yfinance():
    """美股 ROE：CLI 无同名列，证据是与 yfinance 的 roe 值一致（1.4875101 → 148.75%）。"""
    r = _row("usAAPL")
    assert abs(r["roe"] - 1.4875101 * 100) < 0.05


def test_empty_field_is_absent_but_real_zero_is_kept():
    """空 = 字段不出现；0 = 如实落 0。两者不能混为一谈。"""
    def line_with(field38: str, field59: str) -> dict:
        fields = [""] * 70
        fields[1], fields[2], fields[3] = "测试", "600519", "10.0"
        fields[30], fields[33], fields[34] = "20260922150000", "11", "9"
        fields[38], fields[59] = field38, field59
        return tencent._parse_qt_line('v_sh600519="' + "~".join(fields) + '";')

    assert "turnover_rate" not in line_with("", "")          # 接口没给 → 字段缺席
    assert line_with("0", "")["turnover_rate"] == 0.0        # 真实零 → 保留
    assert line_with("0.2", "")["turnover_rate"] == 0.2


def test_every_rendered_key_is_producible():
    """`_STOCK_KEYS` 不能有孤儿键：键名对不上解析结果就是静默丢字段。

    （首版 `amplitude` 在改名为 `range_pct` 后成了孤儿键，振幅字段会静默消失。）
    """
    parseable = set(_row("sh600519")) | set(_row("hk00700")) | set(_row("usAAPL"))
    orphans = [k for k in tencent._STOCK_KEYS if k not in parseable]
    assert not orphans, f"这些键在真实样本里取不到值（多半是改名后没同步）: {orphans}"


def test_kline_reads_prefixed_key(monkeypatch):
    """复权序列挂在 `qfq<period>` 键下，取裸 `<period>` 会**恒返回空**。"""
    payload = json.loads(_SAMPLES["_kline_sh600519_qfq_day_5"])
    node = payload["data"]["sh600519"]
    assert "day" not in node, "样本前提变了：接口开始给裸键，需重新确认取键优先级"
    assert len(node["qfqday"]) == 6

    monkeypatch.setattr(tencent, "_http_get",
                        lambda *a, **k: _SAMPLES["_kline_sh600519_qfq_day_5"])
    res = tencent.kline("600519", "day", 5)
    assert res["ok"] is True
    assert len(res["data"]["rows"]) == 5, "超过 limit 的部分应被裁掉（接口会多回一根）"


def test_year_kline_is_aggregated_from_months(monkeypatch):
    """年线必须由月K按自然年聚合：接口的 `year` 只回 1 根**当日的** OHLC。

    实测 `param=sh600519,year,,,12,qfq` → key=`year`、1 根，数值与当天日线逐位相同
    （开 1252.15 / 高 1265.88 / 低 1248.1 / 收 1253.8）。直接透传就是「当日 K 线
    冒充年 K」—— 被移植实现专门为此写了聚合（known-issues ⑯），首版移植漏掉、验证时被抓出。
    """
    month_payload = json.loads(_SAMPLES["_kline_sh600519_qfq_month_36"])
    months = month_payload["data"]["sh600519"]["qfqmonth"]
    urls: list[str] = []

    def fake_http(url, *a, **k):
        urls.append(url)
        return json.dumps({"data": {"sh600519": {"qfqmonth": months}}})
    monkeypatch.setattr(tencent, "_http_get", fake_http)

    res = tencent.kline("600519", "year", 4)
    assert res["ok"] is True
    rows = res["data"]["rows"]
    assert len(rows) == 4, f"年线应聚合出 4 根（2023-2026），实得 {len(rows)} 根"
    assert rows[0]["date"].startswith("2023"), "最早一根应是 2023 年，而不是当日"
    assert "month" in urls[0] and ",year," not in urls[0], "年线取数必须走月线接口"
    # 聚合口径：末年收 = 该年末月收；末年高 = 该年各月高之最大
    y2026 = [m for m in months if str(m[0]).startswith("2026")]
    assert rows[-1]["close"] == float(y2026[-1][2])
    assert rows[-1]["high"] == max(float(m[3]) for m in y2026)
    assert rows[-1]["open"] == float(y2026[0][1])
    assert rows[-1]["volume"] == round(sum(float(m[5]) for m in y2026), 4)


# ── ② 边界语义（故障 ≠ 空数据） ─────────────────────────────────────────────

def test_http_failure_returns_error_envelope(monkeypatch):
    """传输故障 → ok=False + 可读原因。**不许**降级成空结果。"""
    def boom(*a, **k):
        raise tencent.TencentError("模拟断网")
    monkeypatch.setattr(tencent, "_http_get", boom)
    res = tencent.quote("600519")
    assert res["ok"] is False
    assert res["data"] is None
    assert "模拟断网" in (res["error"] or "")


def test_stock_failure_is_not_empty_snapshot(monkeypatch):
    """stock() 同理：故障时不能回一个「成功但没字段」的快照。"""
    def boom(*a, **k):
        raise tencent.TencentError("模拟断网")
    monkeypatch.setattr(tencent, "_http_get", boom)
    res = tencent.stock("600519")
    assert res["ok"] is False and res["data"] is None


def test_unreturned_code_is_reported_as_missing(monkeypatch):
    """接口对未知代码不报错，只是不回那一行 —— 必须显式报出，不能静默少一条。"""
    monkeypatch.setattr(tencent, "_http_get",
                        lambda *a, **k: _SAMPLES["sh600519"])
    res = tencent.quote("600519,sz999999")
    assert res["ok"] is True
    assert "sz999999" in res["data"]["missing"]


def test_unresolved_input_is_reported_as_unresolved_not_missing(monkeypatch):
    """解析不出的输入必须进 unresolved 名单。

    区分 unresolved 与 missing 是有意义的：前者是「我没能把它变成代码」，
    后者是「接口没回这个代码」。若实现把解析失败的原文当成代码发出去
    （原实现 `normalize_code` 的 `return low`），它会落进 missing ——
    用户看到的解释就变成「代码可能不存在」，把问题指向了自己。
    """
    monkeypatch.setattr(tencent, "search", lambda *a, **k: [])
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["sh600519"])
    res = tencent.quote("600519,没有这个标的名")
    assert res["ok"] is True
    data = res["data"]
    assert "没有这个标的名" in data.get("unresolved", []), data
    assert "没有这个标的名" not in data.get("missing", [])


def test_garbage_input_is_not_sent_as_code(monkeypatch):
    """非代码形态的输入不得被当成代码发出去（normalize_code 必须回空串）。"""
    monkeypatch.setattr(tencent, "search", lambda *a, **k: [])
    seen: list[str] = []

    def spy(url, *a, **k):
        seen.append(url)
        return _SAMPLES["sh600519"]
    monkeypatch.setattr(tencent, "_http_get", spy)
    res = tencent.quote("abc-def!xyz")
    assert res["ok"] is False and res["error"]
    assert "abc-def!xyz" not in " ".join(seen), f"脏输入被送进了接口: {seen}"


def test_fund_code_rejected_by_stock_adapter():
    """基金代码不得由 stock 适配器回答（会撞上同号可转债，返回另一个标的）。"""
    res = tencent.stock("110011")
    assert res["ok"] is False
    assert "基金代码" in res["error"] and "invest-cli fund 110011" in res["error"]


def test_number_overlap_is_flagged_not_silently_swapped():
    """11xxxx 段号码重叠：数值照给，但必须带冲突说明。"""
    warn = tencent._domain_conflict("110011", {"name": "歌华转债"})
    assert "歌华转债" in warn and "fund 110011" in warn


def test_number_overlap_does_not_fire_for_etf():
    """ETF 也用 fund 段号码（510300），但接口给的**就是它**，不能误报。"""
    assert tencent._domain_conflict("510300", {"name": "沪深300ETF华泰柏瑞"}) == ""
    assert tencent._domain_conflict("600519", {"name": "贵州茅台"}) == ""


def test_quote_rows_carry_currency_and_volume_unit(monkeypatch):
    """跨市场可比的前提：每行必须带计价货币与成交量单位。

    独立验证实测：不标单位时把 A股 volume（**手**）与港股 volume（**股**）直接相比，
    会得出 2878 倍的差距，按股换算后只有 28.78 倍 —— **100 倍误差**。
    """
    def fake_http(url, *a, **k):
        # 一次请求带多个标的时，接口把它们拼成多行返回 —— mock 也要按这个形状拼，
        # 只回第一条会让后面的断言全 KeyError（这正是首版写法的问题）
        codes = url.split("=", 1)[1].split(",")
        return "".join(_SAMPLES[c] for c in codes if c in _SAMPLES)
    monkeypatch.setattr(tencent, "_http_get", fake_http)
    rows = tencent.quote("600519,00700,AAPL")["data"]["quotes"]
    units = {r["symbol"]: (r["currency"], r["volume_unit"]) for r in rows}
    assert units["sh600519"] == ("CNY", "手")
    assert units["hk00700"] == ("HKD", "股")
    assert units["usAAPL"] == ("USD", "股")


def test_us_snapshot_payload_carries_roe(monkeypatch):
    """文档声明了 ROE，就必须**落到载荷**上，不能只停在解析层。"""
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["usAAPL"])
    snap = tencent.us("AAPL")["data"]
    assert snap.get("financial", {}).get("roe") is not None
    assert abs(snap["financial"]["roe"] - 1.4875) < 1e-3


def test_us_symbol_has_no_exchange_suffix(monkeypatch):
    """美股 symbol 用裸 ticker（带 .OQ 会让同一标的在缓存键上变成两个）。"""
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["usAAPL"])
    res = tencent.us("AAPL")
    assert res["data"]["symbol"] == "AAPL"
    assert res["data"]["exchange_code"] == "AAPL.OQ"


def test_us_units_follow_yfinance_convention(monkeypatch):
    """单位必须换算成 yfinance 的口径，否则渲染器会差 100 倍/一个数量级。"""
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["usAAPL"])
    q = tencent.us("AAPL")["data"]["quote"]
    assert abs(q["dividend_yield"] - 0.0031) < 1e-4      # 百分数 → 小数
    assert abs(q["market_cap"] - 4.9471e12) / 4.9471e12 < 1e-3   # 亿 → 绝对值


def test_uppercase_ticker_skips_name_resolution(monkeypatch):
    """全大写 ticker 不该再走一次搜索解析。

    实测这一步约 130ms，是 us 兜底路径总耗时的一半；而且解析结果还可能被
    同名境外标的抢走。这里把 search 换成「一调就炸」，用来证明它没被调用。
    """
    def must_not_call(*a, **k):
        raise AssertionError("对全大写 ticker 不应触发名称解析")
    monkeypatch.setattr(tencent, "search", must_not_call)
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["usAAPL"])
    assert tencent.us("AAPL")["ok"] is True
    assert tencent._needs_resolution("AAPL") is False
    assert tencent._needs_resolution("BRK.B") is False
    assert tencent._needs_resolution("maotai") is True      # 小写拼音要解析
    assert tencent._needs_resolution("贵州茅台") is True


def _search_payload(items: list[list[str]]) -> str:
    return json.dumps({"data": {"stock": items}}, ensure_ascii=False)


def test_search_cache_key_includes_limit(monkeypatch):
    """缓存键必须含 limit：否则先来的小 limit 会把后面的查询截断 24 小时。

    这是审计发现的真实缺陷形态（原实现键为 `s:<kw>`，一次 limit=2 之后
    24 小时内所有 limit=20 都只回 2 条，而调用方之间 limit 不同：
    名称解析用 5、批量行情用 10）。
    """
    items = [["sh", f"5103{i:02d}", f"测试ETF{i}", "", "etf"] for i in range(20)]
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _search_payload(items))
    assert len(tencent.search("沪深300", limit=2)) == 2
    assert len(tencent.search("沪深300", limit=20)) == 20, "小 limit 的缓存污染了大 limit 的结果"


def test_name_resolution_is_consistent_across_paths(monkeypatch):
    """同一个名字在 quote / kline / stock 三条路径上必须解析到**同一个标的**。

    审计发现的缺陷：原实现里 quote 用 hits[0]（接口排序，可能给境外同名标的），
    而 kline/minute 走「境内优先」重排 —— 同一个名字在两条路径上给出不同公司
    （`沪深300ETF` → quote 给 usASHR、kline 给 sh510300）。
    """
    hits = [["us", "ASHR", "沪深300 ETF-Xtrackers", "", "etf"],
            ["sh", "510300", "沪深300ETF华泰柏瑞", "", "etf"]]
    monkeypatch.setattr(tencent, "search", lambda *a, **k: [
        {"market": h[0], "code": h[1], "symbol": f"{h[0]}{h[1]}", "name": h[2], "type": h[4]}
        for h in hits])
    def fake_http(url, *a, **k):
        # 行情与 K线是两个端点，返回对应的样本形状（同一个 mock 要都伺候得了）
        if "fqkline" in url:
            return json.dumps({"data": {"sh510300": {"qfqday": [
                ["2026-09-22", "4.60", "4.61", "4.62", "4.59", "1000"]]}}})
        return _SAMPLES["sh510300"]
    monkeypatch.setattr(tencent, "_http_get", fake_http)
    assert tencent.resolve_name("沪深300") == "sh510300"      # 境内优先
    assert tencent._codes_for("沪深300")[0] == ["sh510300"]
    assert tencent.kline("沪深300", "day", 1)["data"]["symbol"] == "sh510300"
    assert tencent.quote("沪深300")["data"]["quotes"][0]["symbol"] == "sh510300"


def test_normalize_code_keeps_us_ticker_case():
    """美股 ticker 区分大小写，小写化会让标的静默丢失。"""
    assert tencent.normalize_code("usaapl") == "usAAPL"
    assert tencent.normalize_code("aapl") == "usAAPL"
    assert tencent.normalize_code("00700.HK") == "hk00700"
    assert tencent.normalize_code("600519.SH") == "sh600519"
    assert tencent.normalize_code("510300") == "sh510300"
    # 认不出来的输入必须是空串：原样回吐会让「名字没解析出来」变成一次
    # 「接口少给了一条」的无声查询
    assert tencent.normalize_code("没有这个标的名") == ""
    assert tencent.normalize_code("") == ""


# ── ③ 链路位置（位置错了不报错，只会静默降级） ──────────────────────────────

def test_us_chain_puts_tencent_before_bitget():
    assert route.candidates("us") == ["yfinance", "tencent", "bitget"]


def test_rich_sources_stay_first_for_stock():
    """腾讯不得抢到富源前面：它没有基本面，抢位就是能力降级。"""
    a = route.candidates("stock", market="a")
    assert a[0] == "hithink"
    assert a.index("tencent") > a.index("hithink")
    hk = route.candidates("stock", market="hk")
    assert hk[0] == "eastmoney"
    assert hk.index("tencent") > hk.index("eastmoney")


def test_tencent_not_in_fund_or_screen_chain():
    """没有 fund()/screen() 方法，就不该出现在这两条链上（能力声明与实际一致）。"""
    assert "tencent" not in route.candidates("fund")
    assert "tencent" not in route.candidates("screen")


def test_fallback_uses_tencent_when_rich_source_fails(monkeypatch):
    """富源失败时由腾讯顶上，且信封如实标注 fallback_from。"""
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["usAAPL"])
    calls: list[str] = []

    def fake_invoke(sid, kind, arg):
        calls.append(sid)
        if sid == "yfinance":
            return {"source": sid, "kind": kind, "ok": False, "data": None, "error": "模拟不可达"}
        return tencent.us(arg)

    res = route.fetch("us", "AAPL", order=["yfinance", "tencent", "bitget"],
                      invoke=fake_invoke)
    assert res["ok"] is True and res["source"] == "tencent"
    assert calls == ["yfinance", "tencent"]          # 命中即停，不去碰 bitget
    assert res["fallback_from"] == "yfinance"


# ── ④ 命令层 ────────────────────────────────────────────────────────────────

def test_quote_cmd_exit_codes(monkeypatch, capsys):
    from cmd_quote import run
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["sh600519"])
    assert run("600519") == 0
    assert "贵州茅台" in capsys.readouterr().out

    def boom(*a, **k):
        raise tencent.TencentError("模拟断网")
    monkeypatch.setattr(tencent, "_http_get", boom)
    # 换一个标的：同一个标的会命中上一步写下的 10s 缓存，
    # 于是「通道已断」被缓存成功结果掩盖（缓存本身的语义，非缺陷）
    assert run("000858") == 1
    assert "错误" in capsys.readouterr().err


@pytest.mark.parametrize("codes,expect", [
    ("600519", "sh600519"),
    ("000858", "sz000858"),
    ("00700", "hk00700"),
    ("AAPL", "usAAPL"),
])
def test_quote_cmd_renders_multi_market(monkeypatch, capsys, codes, expect):
    """四类写法都要能渲染出各自的市场前缀（一次请求即可）。"""
    key = {"sh600519": "sh600519", "sz000858": "sz000858",
           "hk00700": "hk00700", "usAAPL": "usAAPL"}[expect]
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES[key])
    from cmd_quote import run
    assert run(codes) == 0
    out = capsys.readouterr().out
    assert expect in out


def test_quote_terminal_reports_missing_codes(monkeypatch, capsys):
    """终端输出里必须出现未返回的代码，否则用户只看到「少了一条」。"""
    monkeypatch.setattr(tencent, "_http_get", lambda *a, **k: _SAMPLES["sh600519"])
    from cmd_quote import run
    run("600519,sz999999")
    assert "sz999999" in capsys.readouterr().out


# ── ⑤ 同号重叠的**告知**：两边都存在时不能只给一边还不吭声 ──────────────────
#
# 000001 是三义的：沪指 sh000001、平安银行 sz000001、场外基金 000001。接口按股票推断，
# 指数那一义被丢掉。旧实现（以及本适配器的首版）在这里**不给任何提示**，而同一份代码
# 对「基金 vs 可转债」（110011）是给提示的 —— 同一类歧义两种待遇，独立验证抓到的就是这处。
#
# 判据不靠猜：指数存不存在由接口回答（同一次批量请求里多带一个探针代码）。
# 这里把 `quote_batch` 换掉而不是拼 qt 报文：造一个指数响应要改一堆下标，脆。


def _quote_row(symbol: str, name: str, price: float) -> dict:
    """够用的行情行（非占位：成交量/额都非 0）。"""
    return {"symbol": symbol, "code": symbol[2:], "name": name, "price": price,
            "prev_close": price, "open": price, "high": price, "low": price,
            "volume": 1234.0, "amount": 1.0e7, "time": "2026-09-22 15:00:00",
            "_market": "a"}


def _fake_batch(monkeypatch, table: dict[str, dict]) -> None:
    def fake_batch(symbols):
        return [table[s] for s in symbols if s in table], [s for s in symbols if s not in table]
    monkeypatch.setattr(tencent, "quote_batch", fake_batch)
    monkeypatch.setattr(tencent, "search", lambda *a, **k: [])


def test_overlapping_bare_code_gets_index_disambiguation(monkeypatch) -> None:
    """两边都存在时：给股票，但必须说明同号还是沪市指数。"""
    _fake_batch(monkeypatch, {
        "sz000001": _quote_row("sz000001", "平安银行", 11.71),
        "sh000001": _quote_row("sh000001", "上证指数", 3952.13),
    })
    res = tencent.quote("000001")
    assert res["ok"] is True, res
    assert [q["symbol"] for q in res["data"]["quotes"]] == ["sz000001"]
    warn = res["data"]["quotes"][0]["code_domain_warning"]
    assert "sh000001" in warn and "上证指数" in warn
    assert "要指数请写 sh000001" in warn
    # 探针行不得混进结果表，也不得被当成「你说缺了一条」
    assert res["data"]["count"] == 1
    assert not res["data"].get("missing")


def test_probe_row_is_not_hidden_when_it_is_the_answer(monkeypatch) -> None:
    """探针不能把「同号换市场」补查来的行藏掉。

    `000300`：sz000300 不是股票、sh000300 是沪深300 —— 那一行就是用户的答案。
    我第一版把探针一律藏掉，`quote 000300` 于是从正常返回退化成
    「错误: 腾讯行情未返回任何标的：sz000300」（实测）。
    """
    _fake_batch(monkeypatch, {"sh000300": _quote_row("sh000300", "沪深300", 4544.59)})
    res = tencent.quote("000300")
    assert res["ok"] is True, res
    assert [q["symbol"] for q in res["data"]["quotes"]] == ["sh000300"]
    assert "sz000300" in res["data"]["missing"]


def test_no_index_notice_when_probe_returns_nothing(monkeypatch) -> None:
    """探针没回行就**不发提示**：宁可不说，也不断言一个取不到的东西存在。"""
    _fake_batch(monkeypatch, {"sz000001": _quote_row("sz000001", "平安银行", 11.71)})
    res = tencent.quote("000001")
    assert res["ok"] is True
    assert "code_domain_warning" not in res["data"]["quotes"][0]
    assert not res["data"].get("conflicts")


def test_no_index_notice_when_both_forms_are_asked(monkeypatch) -> None:
    """用户把两种写法都写了，提示就是噪音，不发。"""
    _fake_batch(monkeypatch, {
        "sz000001": _quote_row("sz000001", "平安银行", 11.71),
        "sh000001": _quote_row("sh000001", "上证指数", 3952.13),
    })
    res = tencent.quote("sz000001,sh000001")
    assert res["ok"] is True
    assert [q["symbol"] for q in res["data"]["quotes"]] == ["sz000001", "sh000001"]
    assert not res["data"].get("conflicts")


def test_no_index_notice_for_non_overlapping_codes(monkeypatch) -> None:
    """沪市股票/港股/美股不落在重叠号段，不该被加提示（否则每条查询都多一行噪音）。"""
    _fake_batch(monkeypatch, {
        "sh600519": _quote_row("sh600519", "贵州茅台", 1253.8),
        "hk00700": _quote_row("hk00700", "腾讯控股", 451.6),
    })
    res = tencent.quote("600519,00700")
    assert res["ok"] is True
    assert all("code_domain_warning" not in q for q in res["data"]["quotes"])
