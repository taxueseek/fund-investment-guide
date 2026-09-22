"""数据源适配器的契约守卫 — 不联网（上游与子进程被 monkeypatch）。

守护的是「**适配器把上游的坏行为原样透给用户**」这一类缺陷：

- 实体守卫：东财对未知标的会模糊匹配到别家并正常返回，不得让别家的数据
  冒充用户查询的标的；同时**传输失败**不得被误报成「标的不存在」。
- argo：引擎清单不本地维护（白名单漂移曾造成「0 结果 + ok=true」的静默空答复），
  以 argo 自己的 `--list-engines` 为准。
- FRED：四条序列必须并发；缓存只在完整结果上写；`use_cache=False` 不读也不写。
- fund 深取：ttskill 两次子进程必须落盘缓存，否则主快照命中缓存也白搭。
- us：yfinance 的空壳 info（非空但无内容）不得冒充成功；传输异常与「未找到」
  必须分开报；类别股按**事实**回退连字符形式，而不是按字符串形状改写。

缓存/状态目录隔离由 conftest.py 统一提供。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# ── 1. 数据可信度：模糊匹配不得冒充用户查询的标的
#
# 实测缺陷：查「不存在的公司XYZ」时东财模糊匹配到 Block Inc-A(XYZ.N)，
# 旧实现把它的 ROE/毛利率挂在用户输入的名字下、以 exit=0 输出。
# 用户会以为拿到了自己查的那家公司——静默错误比报错危险得多。

def _fake_tables(t1, t2, t3):
    """按顺序喂给三次东财查询（行情/财务/年报）。"""
    seq = iter([t1, t2, t3])

    def _fake_query(q: str) -> dict:
        return {"_": next(seq)}

    return _fake_query


def test_stock_fuzzy_match_is_rejected(monkeypatch) -> None:
    """行情表为空、财务表来自别家 → 必须报错，不得冒充成功。"""
    import cmd_stock

    monkeypatch.setattr(
        cmd_stock, "query_eastmoney", _fake_tables([], [{"entityName": "Block Inc-A(XYZ.N)", "销售毛利率(%)": "47.93"}], [])
    )
    monkeypatch.setattr(cmd_stock, "parse_tables", lambda raw: raw["_"])

    try:
        cmd_stock.fetch_stock_data("不存在的公司XYZ")
        raise AssertionError("别家公司的数据不得冒充用户查询的标的")
    except ValueError as e:
        assert "未找到标的" in str(e)
        assert "Block Inc-A" in str(e), "报错应指明实际匹配到的标的"


def test_stock_empty_result_is_rejected(monkeypatch) -> None:
    """三表全空 → 明确报未找到，而不是返回空快照假装成功。"""
    import cmd_stock

    monkeypatch.setattr(cmd_stock, "query_eastmoney", _fake_tables([], [], []))
    monkeypatch.setattr(cmd_stock, "parse_tables", lambda raw: raw["_"])

    try:
        cmd_stock.fetch_stock_data("000000")
        raise AssertionError("空结果不得当成功返回")
    except ValueError as e:
        assert "未找到标的" in str(e)


def test_stock_valid_quote_still_passes(monkeypatch) -> None:
    """有行情表时必须正常合并（守卫不能把正常查询拦掉）。"""
    import cmd_stock

    monkeypatch.setattr(
        cmd_stock,
        "query_eastmoney",
        _fake_tables(
            [{"entityName": "贵州茅台(600519.SH)", "总市值": "1.616万亿"}],
            [{"entityName": "贵州茅台(600519.SH)", "销售毛利率(%)": "91.3"}],
            [{"entityName": "贵州茅台(600519.SH)", "营业收入": "1500亿"}],
        ),
    )
    monkeypatch.setattr(cmd_stock, "parse_tables", lambda raw: raw["_"])

    snap = cmd_stock.fetch_stock_data("600519")
    assert "贵州茅台" in snap["name"]
    assert snap["data"]["销售毛利率(%)"] == "91.3"


def test_stock_suspended_with_matching_name_is_accepted(monkeypatch) -> None:
    """停牌类：行情为空但财务/年报都指向**同一且与代码相符**的标的 → 应放行。

    这是守卫的反向用例（防止修成「一律拒绝」）。放行需同时满足：
    行情请求成功 + ≥2 张表 entityName 一致 + 该名称与查询代码确有对应。
    """
    import cmd_stock

    monkeypatch.setattr(
        cmd_stock,
        "query_eastmoney",
        _fake_tables(
            [],
            [{"entityName": "贵州茅台(600519.SH)", "销售毛利率(%)": "91.3"}],
            [{"entityName": "贵州茅台(600519.SH)", "营业收入": "1500亿"}],
        ),
    )
    monkeypatch.setattr(cmd_stock, "parse_tables", lambda raw: raw["_"])

    snap = cmd_stock.fetch_stock_data("600519")
    assert "贵州茅台" in snap["name"]
    assert snap.get("note"), "应说明行情缺失的原因，不能静默"


def test_stock_single_other_table_does_not_authorize(monkeypatch) -> None:
    """只有一张非行情表有值时**不得**放行——正是真实模糊匹配的形态。

    实测：查「不存在的公司XYZ」只有 financial 一张表返回 Block Inc-A。
    只数「有几张表有值」就会把 Block 的数据当成用户要的标的（回归过一次）。
    """
    import cmd_stock

    monkeypatch.setattr(
        cmd_stock,
        "query_eastmoney",
        _fake_tables([], [{"entityName": "Block Inc-A(XYZ.N)", "销售毛利率(%)": "47.93"}], []),
    )
    monkeypatch.setattr(cmd_stock, "parse_tables", lambda raw: raw["_"])

    try:
        cmd_stock.fetch_stock_data("不存在的公司XYZ")
        raise AssertionError("单张表有值不足以证明匹配到同一标的")
    except ValueError as e:
        assert "未找到标的" in str(e)


def test_stock_transport_failure_is_not_reported_as_not_found(monkeypatch) -> None:
    """行情查询**失败**（传输问题）时不得报「未找到」——那是两回事。"""
    import cmd_stock

    def _flaky(q: str):
        # 按查询内容判定，而不是按调用序号：三组查询是并发的，
        # 无锁计数器（calls["n"] += 1）在并发下会误判是哪一路失败。
        if "最新行情" in q:
            raise ConnectionError("simulated network failure")
        return {"_": []}

    monkeypatch.setattr(cmd_stock, "query_eastmoney", _flaky)
    monkeypatch.setattr(cmd_stock, "parse_tables", lambda raw: raw["_"])

    try:
        cmd_stock.fetch_stock_data("600519")
        raise AssertionError("全失败时应报取数失败")
    except RuntimeError as e:
        assert "取数失败" in str(e)
        assert "未找到" not in str(e), "传输失败被误报成标的不存在"


def test_fund_transport_failure_is_not_reported_as_not_found(monkeypatch) -> None:
    """基金同理：基础信息查询失败 → 报取数失败，不报「未找到基金」。"""
    import cmd_fund

    def _flaky(q: str):
        # 同 cmd_stock：六组查询并发，按内容判定才是确定的
        if "基金基本信息" in q:
            raise ConnectionError("simulated network failure")
        return {"_": []}

    monkeypatch.setattr(cmd_fund, "query_eastmoney", _flaky)
    monkeypatch.setattr(cmd_fund, "parse_tables", lambda raw: raw["_"])

    try:
        cmd_fund.fetch_fund_data("110011")
        raise AssertionError("全失败时应报取数失败")
    except RuntimeError as e:
        assert "取数失败" in str(e)
        assert "未找到" not in str(e)


def test_fund_fuzzy_match_is_rejected(monkeypatch) -> None:
    """基金同形问题：基础信息为空而其余表有值 → 必须报错。"""
    import cmd_fund

    seq = iter([[], [{"entityName": "别家基金", "近1年回报": "10%"}], [], [], [], []])

    monkeypatch.setattr(cmd_fund, "query_eastmoney", lambda q: {"_": next(seq)})
    monkeypatch.setattr(cmd_fund, "parse_tables", lambda raw: raw["_"])

    try:
        cmd_fund.fetch_fund_data("999999")
        raise AssertionError("别家基金的数据不得冒充用户查询的代码")
    except ValueError as e:
        assert "未找到基金" in str(e)


def test_fund_valid_basic_still_passes(monkeypatch) -> None:
    """有基础信息表时必须正常返回。"""
    import cmd_fund

    seq = iter([
        [{"entityName": "优质精选(110011)", "基金名称": "优质精选"}],
        [{"entityName": "优质精选(110011)", "近1年回报": "12%"}],
        [], [], [], [],
    ])
    monkeypatch.setattr(cmd_fund, "query_eastmoney", lambda q: {"_": next(seq)})
    monkeypatch.setattr(cmd_fund, "parse_tables", lambda raw: raw["_"])

    snap = cmd_fund.fetch_fund_data("110011")
    assert snap["name"] == "优质精选"
    assert snap["data"]["近1年回报"] == "12%"

# ── 2. argo 协作：引擎清单不本地维护（白名单漂移曾造成静默空答复）
#
# 历史缺陷（2026-09-19 实测）：sources/argo.py 维护了一份 FIN_ENGINES 白名单，
#   ① 名单里的 `cn-web-search` 在 argo 里早已不存在 → 用户拿到「0 结果 + ok=true」；
#   ② 名单外的合法引擎（如 anysearch）被**静默替换**成 eastmoney，且不告知；
#   ③ `--max-results` 未透传 → limit>5 被 argo 默认值静默截断。
# 修法是删掉白名单，让 argo 自己裁决。以下用例钉死这三点。

def _argo_proc(stdout="", stderr="", returncode=0):
    class _P:
        pass

    p = _P()
    p.stdout, p.stderr, p.returncode = stdout, stderr, returncode
    return p


def test_argo_engine_is_passed_through_not_whitelisted(monkeypatch) -> None:
    """合法但不在任何本地名单里的引擎必须原样送达 argo（不得被换成 eastmoney）。"""
    import sources.argo as argo

    seen: dict[str, list[str]] = {}

    def _run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return _argo_proc(stdout=json.dumps({"results": [], "errors": []}))

    monkeypatch.setattr(argo.subprocess, "run", _run)
    monkeypatch.setattr(argo, "known_engines", lambda: {"anysearch", "eastmoney"})
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    res = argo.search("人工智能", engine="anysearch")

    assert "anysearch" in seen["cmd"], "引擎被本地白名单改写了"
    assert "eastmoney" not in seen["cmd"]
    assert res["data"]["engine"] == "anysearch"


def test_argo_max_results_is_forwarded(monkeypatch) -> None:
    """limit 必须下推到 argo：argo 默认只回 5 条，不透传则 limit>5 静默截断。"""
    import sources.argo as argo

    seen: dict[str, list[str]] = {}

    def _run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return _argo_proc(stdout=json.dumps({"results": [], "errors": []}))

    monkeypatch.setattr(argo.subprocess, "run", _run)
    monkeypatch.setattr(argo, "known_engines", lambda: {"eastmoney"})
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    argo.search("茅台", limit=10)

    cmd = seen["cmd"]
    assert "--max-results" in cmd and cmd[cmd.index("--max-results") + 1] == "10"


def test_argo_unknown_engine_is_an_error_not_empty_success(monkeypatch) -> None:
    """argo 打「未知引擎」时必须是 ok=False —— 空结果 + ok=true 会让人以为「真的没有」。

    这是**兜底**信号（清单探测失败时走这里）；主判据见下一条。
    """
    import sources.argo as argo

    monkeypatch.setattr(argo, "known_engines", lambda: None)
    monkeypatch.setattr(
        argo.subprocess, "run",
        lambda cmd, **kw: _argo_proc(
            stdout=json.dumps({"results": [], "count": 0}),
            stderr="未知引擎: cn-web-search\n未知引擎: cn-web-search\n",
        ),
    )
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    res = argo.search("茅台", engine="cn-web-search")

    assert res["ok"] is False, "未知引擎被当成了「无结果」"
    assert "cn-web-search" in res["error"]
    assert "--list-engines" in res["error"], "错误信息要给出下一步动作"
    assert "search.py" in res["error"], "清单命令要给具体路径，不能是占位符"


def test_argo_engine_validated_against_argo_own_list(monkeypatch) -> None:
    """主判据：向 argo 要一次合法引擎清单再校验。

    为什么不能只靠 stderr：argo 命中自己的缓存后**不再解析引擎**，stderr 为空
    （实测同一 query 连跑两次：第一次 112 字节，第二次 0 字节且 cached=true）。
    只看 stderr 会让这个 bug 在第二次查询时原样复现。
    """
    import sources.argo as argo

    monkeypatch.setattr(argo, "known_engines", lambda: {"eastmoney", "zhihu"})
    called = {"n": 0}

    def _run(cmd, **kw):
        called["n"] += 1
        return _argo_proc(stdout=json.dumps({"results": []}))

    monkeypatch.setattr(argo.subprocess, "run", _run)
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))

    # 非法引擎：必须在**发起检索之前**就被拦下（stderr 为空也不放过）
    res = argo.search("x", engine="totally-bogus")
    assert res["ok"] is False
    assert "totally-bogus" in res["error"]
    assert called["n"] == 0, "引擎校验没拦住检索请求"

    # 反向用例：清单内的引擎必须照常检索
    res = argo.search("x", engine="zhihu")
    assert res["ok"] is True
    assert called["n"] == 1


def test_argo_nonzero_exit_surfaces_real_reason_not_traceback_header(monkeypatch) -> None:
    """argo 崩在异常时，错误里不能只有「Traceback (most recent call last)」。

    旧写法取 stderr 前 160 字符，用户看到的「原因」是 traceback 表头；
    真正的原因在最后一行。
    """
    import sources.argo as argo

    tb = (
        "Traceback (most recent call last):\n"
        "  File \"search.py\", line 1, in <module>\n"
        "ModuleNotFoundError: No module named 'x'\n"
    )
    monkeypatch.setattr(argo, "known_engines", lambda: {"eastmoney"})
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    monkeypatch.setattr(argo.subprocess, "run",
                        lambda cmd, **kw: _argo_proc(stderr=tb, returncode=1))

    res = argo.search("x", engine="eastmoney")
    assert res["ok"] is False
    assert "ModuleNotFoundError" in res["error"], f"未取到最后一行真实原因: {res['error']!r}"
    assert "Traceback" not in res["error"], "错误里混进了 traceback 表头"


def test_argo_engine_list_probe_failure_fails_open(monkeypatch) -> None:
    """拿不到引擎清单时必须放行 —— 校验本身出问题不能阻断取数。"""
    import sources.argo as argo

    monkeypatch.setattr(argo, "known_engines", lambda: None)
    monkeypatch.setattr(
        argo.subprocess, "run",
        lambda cmd, **kw: _argo_proc(stdout=json.dumps({"results": [{"title": "t"}]}), stderr=""),
    )
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    res = argo.search("x", engine="some-engine")

    assert res["ok"] is True
    assert len(res["data"]["results"]) == 1


def test_argo_engine_list_is_cached_and_parsed(monkeypatch, tmp_path) -> None:
    """引擎清单要落盘缓存，且只接受 argo 自己给的 JSON 数组。"""
    import sources.argo as argo

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    calls = {"n": 0}

    def _run(cmd, **kw):
        calls["n"] += 1
        return _argo_proc(stdout=json.dumps(["eastmoney", "zhihu"]))

    monkeypatch.setattr(argo.subprocess, "run", _run)
    first = argo.known_engines()
    assert first == {"eastmoney", "zhihu"}
    assert calls["n"] == 1
    second = argo.known_engines()
    assert second == {"eastmoney", "zhihu"}
    assert calls["n"] == 1, "引擎清单没走缓存，每次检索都要多起一个子进程"


def test_argo_no_result_note_quotes_argo_errors(monkeypatch) -> None:
    """无结果时给的原因要来自 argo 信封，而不是本地猜（本地猜 = 又一份会漂移的知识）。"""
    import sources.argo as argo

    monkeypatch.setattr(
        argo.subprocess, "run",
        lambda cmd, **kw: _argo_proc(
            stdout=json.dumps({"results": [], "errors": ["fred: auto_disabled"]}),
        ),
    )
    monkeypatch.setattr(argo, "known_engines", lambda: {"fred"})
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    res = argo.search("US GDP", engine="fred")

    assert res["ok"] is True
    assert "auto_disabled" in res["data"]["note"], "argo 自己给的原因被丢掉了"


def test_argo_valid_run_has_no_unknown_engine_false_positive(monkeypatch) -> None:
    """反向用例：stderr 为空（合法引擎的真实表现）时必须正常返回，不能被误判为未知引擎。"""
    import sources.argo as argo

    monkeypatch.setattr(
        argo.subprocess, "run",
        lambda cmd, **kw: _argo_proc(
            stdout=json.dumps({"results": [{"title": "t", "url": "u", "snippet": "s"}]}),
            stderr="",
        ),
    )
    monkeypatch.setattr(argo, "known_engines", lambda: {"eastmoney"})
    monkeypatch.setattr(argo, "locate", lambda: Path("/fake/argo/scripts/search.py"))
    res = argo.search("茅台")

    assert res["ok"] is True
    assert len(res["data"]["results"]) == 1

# ── 3. FRED：四条序列必须并发（串行 = 四段 RTT 相加）

def test_fred_series_are_fetched_concurrently(monkeypatch, tmp_path) -> None:
    """四条序列互不依赖，必须并发取；串行时耗时是四段之和（实测 2.34s vs 0.64s）。"""
    import threading

    import sources.fred as fred

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    live = {"n": 0, "max": 0}
    lock = threading.Lock()

    def _slow(sid, **kw):
        with lock:
            live["n"] += 1
            live["max"] = max(live["max"], live["n"])
        time.sleep(0.15)
        with lock:
            live["n"] -= 1
        return [{"date": "2026-09-16", "value": 1.0}], None

    monkeypatch.setattr(fred, "load_api_key", lambda: None)
    monkeypatch.setattr(fred, "_fetch_series_keyless", _slow)
    res = fred.liquidity(use_cache=False)

    assert res["ok"] is True
    assert live["max"] >= 2, f"序列仍是串行取数（峰值并发 {live['max']}）"


def test_fred_liquidity_is_cached(monkeypatch, tmp_path) -> None:
    """第二次调用不得再打网络（FRED 是周度/日度口径，30 分钟内不可能变）。"""
    import sources.fred as fred

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def _count(sid, **kw):
        calls["n"] += 1
        return [{"date": "2026-09-16", "value": 100.0}], None

    monkeypatch.setattr(fred, "load_api_key", lambda: None)
    monkeypatch.setattr(fred, "_fetch_series_keyless", _count)

    first = fred.liquidity()
    assert first["ok"] is True and calls["n"] == 4
    second = fred.liquidity()
    assert second.get("cached") is True
    assert calls["n"] == 4, "第二次调用仍打了网络 = 缓存没生效"
    # 反向：use_cache=False 必须真的绕过缓存（测试与强制刷新依赖它）
    fred.liquidity(use_cache=False)
    assert calls["n"] == 8


def test_fred_use_cache_false_writes_nothing(monkeypatch, tmp_path) -> None:
    """`use_cache=False` 必须**完全不碰缓存**。

    第一版只绕过「读」而仍然「写」，于是 test_fred 的 mock 值被写进真实缓存目录
    （实测污染过 ~/Library/Caches/invest-cli/macro，之后的真实查询命中假数据）。
    """
    import sources.fred as fred

    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(fred, "load_api_key", lambda: None)
    monkeypatch.setattr(fred, "_fetch_series_keyless",
                        lambda sid, **kw: ([{"date": "2026-09-16", "value": 100.0}], None))

    assert fred.liquidity(use_cache=False)["ok"] is True
    leftovers = list(cache_dir.rglob("*.json")) if cache_dir.exists() else []
    assert leftovers == [], f"use_cache=False 仍写了缓存：{leftovers}"


def test_fred_partial_failure_is_not_cached(monkeypatch, tmp_path) -> None:
    """四条序列里有一条失败时不得写缓存：半成品会被固定 30 分钟。"""
    import sources.fred as fred

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(fred, "load_api_key", lambda: None)

    def _flaky(sid, **kw):
        if sid == "SOFR":
            return None, "FRED CSV 请求失败: timeout"
        return [{"date": "2026-09-16", "value": 100.0}], None

    monkeypatch.setattr(fred, "_fetch_series_keyless", _flaky)
    res = fred.liquidity()
    assert res["ok"] is True and res["data"]["series_errors"], "本用例需要「部分失败」的前置"
    # 目录本身会被 cache_path 的 mkdir 建出来，要看有没有真的落下条目
    assert list((tmp_path / "macro").glob("*.json")) == [], "部分失败的结果被缓存了"

# ── 4. fund 深取必须落盘缓存（否则主快照命中缓存也白搭）

def test_fund_deep_fetch_is_cached(monkeypatch, tmp_path) -> None:
    """ttskill 深取是两次子进程调用（~1.0-1.3s），必须缓存；否则每次 fund 都重付。"""
    import cmd_fund
    import sources.ttskill as ttskill

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("sources.registry.detect", lambda conf: (True, "ok"))
    monkeypatch.setattr(
        "sources.route.fetch",
        lambda kind, arg, **kw: {"source": "hithink", "kind": kind, "ok": True,
                                 "data": {"code": arg, "name": "X", "data": {"基金类型": "otc"}}, "error": None},
    )
    calls = {"n": 0}

    def _fund(keyword):
        calls["n"] += 1
        return {"source": "ttskill", "kind": "fund", "ok": True,
                "data": {"data": {"近1年同类分位": "10/100"}}, "error": None}

    monkeypatch.setattr(ttskill, "fund", _fund)

    first = cmd_fund.fetch_fund_with_fallback("110011")
    assert calls["n"] == 1
    assert first["data"]["近1年同类分位"] == "10/100"
    second = cmd_fund.fetch_fund_with_fallback("110011")
    assert calls["n"] == 1, "深取没走缓存 —— 缓存等于白建"
    assert second["data"]["近1年同类分位"] == "10/100"


def test_fund_deep_failure_is_not_cached(monkeypatch, tmp_path) -> None:
    """失败不写缓存：一次网络抖动不该被缓存成一小时的空字段。"""
    import cmd_fund
    import sources.ttskill as ttskill

    monkeypatch.setenv("INVEST_CLI_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("sources.registry.detect", lambda conf: (True, "ok"))
    monkeypatch.setattr(
        "sources.route.fetch",
        lambda kind, arg, **kw: {"source": "hithink", "kind": kind, "ok": True,
                                 "data": {"code": arg, "name": "X", "data": {}}, "error": None},
    )
    calls = {"n": 0}

    def _fail(keyword):
        calls["n"] += 1
        return {"source": "ttskill", "kind": "fund", "ok": False, "data": None, "error": "boom"}

    monkeypatch.setattr(ttskill, "fund", _fail)

    cmd_fund.fetch_fund_with_fallback("110011")
    cmd_fund.fetch_fund_with_fallback("110011")
    assert calls["n"] == 2, "失败结果被缓存了 —— 一次抖动会被放大成持续缺字段"

# ── 5. us：yfinance 的空壳 info 不得冒充成功

class _FakeTicker:
    def __init__(self, info, hist_exc=None):
        self._info = info
        self._hist_exc = hist_exc

    @property
    def info(self):
        return self._info

    def history(self, **kw):
        if self._hist_exc:
            raise self._hist_exc
        raise AssertionError("本用例不应走到真实 history")


def _install_fake_yfinance(monkeypatch, ticker):
    import types

    mod = types.ModuleType("yfinance")
    mod.Ticker = lambda sym: ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def test_us_hollow_info_is_rejected(monkeypatch) -> None:
    """yfinance 对不存在的代码返回**非空但无内容**的 info（实测 {'trailingPegRatio': None}）。

    若不拦，用户会拿到一张全 None 的「美股快照」且 ok=true —— 静默假成功比报错危险。
    """
    import cmd_us

    _install_fake_yfinance(monkeypatch, _FakeTicker({"trailingPegRatio": None},
                                                    hist_exc=TypeError("argument of type 'NoneType'")))
    try:
        cmd_us.fetch_us_data("NOTAREALSYM")
        raise AssertionError("空壳 info 被当成了有效快照")
    except ValueError as e:
        assert "未找到标的" in str(e)
        assert "NOTAREALSYM" in str(e)


def test_us_echoed_symbol_alone_is_not_evidence(monkeypatch) -> None:
    """`symbol` 是请求侧原样回显的，不能算「有数据」。

    实测 BRK.B（未规范化的类别股写法）得到的就是 `{"symbol": "BRK.B"}` 加一片 None；
    若把 symbol 当身份证据，守卫等于不存在。
    """
    import cmd_us

    _install_fake_yfinance(monkeypatch, _FakeTicker({"symbol": "BRK.B", "currency": "USD"},
                                                    hist_exc=TypeError("x")))
    try:
        cmd_us.fetch_us_data("BRK.B")
        raise AssertionError("只有回显的 symbol 就被当成有效快照")
    except ValueError as e:
        assert "未找到标的" in str(e)


def test_us_info_exception_is_not_reported_as_not_found(monkeypatch) -> None:
    """info 抛异常 = 传输/库层问题，不得报「标的不存在」（与 cmd_stock 同一条纪律）。"""
    import cmd_us

    class _Boom:
        @property
        def info(self):
            raise ConnectionError("simulated network failure")

        def history(self, **kw):
            raise AssertionError("不应走到 history")

    _install_fake_yfinance(monkeypatch, _Boom())
    try:
        cmd_us.fetch_us_data("AAPL")
        raise AssertionError("传输失败被当成了成功")
    except RuntimeError as e:
        assert "取数失败" in str(e)
        assert "未找到标的" not in str(e), "传输失败被误报成标的不存在"


def test_us_class_share_falls_back_to_hyphen(monkeypatch) -> None:
    """类别股：点号形式是空壳，连字符形式有数据 → 必须回退并取到真数据。

    判据是**事实**（点号形式有没有标识字段），不是字符串形状；这样才不会
    像按形状改写那样误伤 VOD.L / VOW3.F 这类交易所后缀。
    """
    import cmd_us

    seen: list[str] = []

    class _Ticker:
        def __init__(self, sym):
            seen.append(sym)
            self._sym = sym

        @property
        def info(self):
            # 只有连字符形式有数据（与 Yahoo 实测一致）
            return ({"shortName": "Berkshire Hathaway Inc. New", "currentPrice": 509.77}
                    if self._sym == "BRK-B" else {"symbol": "BRK.B"})

        def history(self, **kw):
            raise TypeError("x")

    import types

    mod = types.ModuleType("yfinance")
    mod.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", mod)

    snap = cmd_us.fetch_us_data("BRK.B")
    assert seen == ["BRK.B", "BRK-B"], f"没有按事实回退连字符形式：{seen}"
    assert snap["name"] == "Berkshire Hathaway Inc. New"
    assert snap["quote"]["price"] == 509.77


def test_us_exchange_suffix_is_not_retried(monkeypatch) -> None:
    """反向用例：点号形式**有**数据时（VOD.L 这类交易所后缀）不得再试连字符形式。

    否则每次查伦敦/法兰克福上市标的都要白付一轮网络。
    """
    import cmd_us

    seen: list[str] = []

    class _Ticker:
        def __init__(self, sym):
            seen.append(sym)

        @property
        def info(self):
            return {"shortName": "VODAFONE GROUP PLC", "currentPrice": 127.25}

        def history(self, **kw):
            raise TypeError("x")

    import types

    mod = types.ModuleType("yfinance")
    mod.Ticker = _Ticker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "yfinance", mod)

    cmd_us.fetch_us_data("VOD.L")
    assert seen == ["VOD.L"], f"点号形式已成功却仍做了回退：{seen}"


def test_us_real_info_still_passes(monkeypatch) -> None:
    """反向用例：有标识字段时必须放行，不能修成一律拒绝。"""
    import cmd_us

    class _Hist:
        empty = True

    tk = _FakeTicker({"symbol": "AAPL", "shortName": "Apple Inc.", "currentPrice": 200.0})
    tk.history = lambda **kw: _Hist()  # type: ignore[assignment]
    _install_fake_yfinance(monkeypatch, tk)

    snap = cmd_us.fetch_us_data("AAPL")
    assert snap["name"] == "Apple Inc."
    assert snap["quote"]["price"] == 200.0


# ── 可用性判据必须与凭据加载器共用同一查找面
#
# 实测（2026-09-22）：把 HITHINK_FINANCE_API_KEY 只写在 ~/.zshenv 时——
#     read_env 找到 key 吗: True
#     hithink.load_api_key 找到吗: True
#     hithink.detect() -> (False, '缺少 HITHINK_FINANCE_API_KEY 且无凭据文件')
#     registry.detect(hithink) -> (False, ...)
# registry 对 env_or_file 型会**直接采信适配器判断**（不回退到 _probe_env），
# 于是同花顺被静默移出 A 股快照链、股票落到东财（口径不同），
# `datasources` 还给出「缺少环境变量 且无凭据文件」这个错误原因。
# sources/env.py 的模块说明正是把「只读 os.environ」点名为漂移源。

def _stub_env_sources(monkeypatch, tmp_path, rc_lines: str):
    """把 read_env 的查找面收敛到一份临时 rc 文件（并关掉 launchctl 分支）。"""
    from sources import env as envmod

    rc = tmp_path / ".zshenv"
    rc.write_text(rc_lines, encoding="utf-8")
    monkeypatch.setattr(envmod, "default_rc_files", lambda: [rc])
    monkeypatch.setattr(envmod, "_launchctl_getenv", lambda name: "")
    return envmod


def test_hithink_detect_agrees_with_loader_on_rc_key(monkeypatch, tmp_path) -> None:
    """rc/launchctl 里配好的 key，detect 必须认（与 load_api_key 同结论）。"""
    from sources import hithink

    envmod = _stub_env_sources(
        monkeypatch, tmp_path, f"export {hithink.ENV_KEY}=KEY_FROM_RC\n"
    )
    monkeypatch.delenv(hithink.ENV_KEY, raising=False)
    monkeypatch.setattr(hithink, "credential_files", lambda: [])

    assert envmod.read_env(hithink.ENV_KEY) == "KEY_FROM_RC"
    assert hithink.load_api_key() == "KEY_FROM_RC"
    ok, detail = hithink.detect()
    assert ok is True, (
        f"detect 与 load_api_key 结论不一致（{detail}）——主数据源会被静默丢掉"
    )


def test_hithink_detect_still_reports_missing_when_truly_absent(monkeypatch, tmp_path) -> None:
    """反向用例：真的没配时必须报不可用，不能修成一律可用。"""
    from sources import hithink

    _stub_env_sources(monkeypatch, tmp_path, "# 没有这个变量\n")
    monkeypatch.delenv(hithink.ENV_KEY, raising=False)
    monkeypatch.setattr(hithink, "credential_files", lambda: [])

    ok, detail = hithink.detect()
    assert ok is False and hithink.ENV_KEY in detail


def test_wind_api_key_agrees_with_detect_on_rc_key(monkeypatch, tmp_path) -> None:
    """Wind 的 key 回退同样走 read_env（只读 os.environ 是同一个漂移）。"""
    from sources import wind

    _stub_env_sources(monkeypatch, tmp_path, "export WIND_API_KEY=WIND_FROM_RC\n")
    monkeypatch.delenv("WIND_API_KEY", raising=False)
    monkeypatch.setattr(wind, "GLOBAL_CONFIG", tmp_path / "no-such-config")
    monkeypatch.delenv("WIND_SKILL_DIR", raising=False)

    assert wind._api_key() == "WIND_FROM_RC"
    assert wind.detect()[0] is True


# ── 可用性判据 = 凭据加载器（东财曾是唯一的例外）
#
# 实测：~/.config/invest-cli/eastmoney.env 里只写一行注释时，
# registry 的通用「文件存在性」回退给出 (True, '读到 credentials.env')，
# 而 eastmoney.load_api_key() 返回 ''——`datasources` 报「文件凭据可用」，
# 每次 screen/港股取数却报「未设置 EASTMONEY_APIKEY」，排障被带偏。

def test_eastmoney_detect_uses_loader_not_file_existence(monkeypatch, tmp_path) -> None:
    """空凭据文件（只有注释）不得被判可用。"""
    from sources import eastmoney

    envfile = tmp_path / "eastmoney.env"
    envfile.write_text("# 只有注释，没有 key\n", encoding="utf-8")
    monkeypatch.setattr(eastmoney, "credential_files", lambda: [envfile])
    monkeypatch.delenv(eastmoney.ENV_KEY, raising=False)

    assert eastmoney.load_api_key() == "", "前提失效：加载器竟然读到了 key"
    ok, detail = eastmoney.detect()
    assert ok is False, "空凭据文件被判可用——datasources 会给出与实取不符的结论"
    assert str(envfile) in detail, "报错未指出检查过哪个文件，排障无从下手"


def test_eastmoney_detect_accepts_real_key(monkeypatch, tmp_path) -> None:
    """反向用例：文件里真有 key 时必须判可用。"""
    from sources import eastmoney

    envfile = tmp_path / "eastmoney.env"
    envfile.write_text(f'{eastmoney.ENV_KEY}="real-key"\n', encoding="utf-8")
    monkeypatch.setattr(eastmoney, "credential_files", lambda: [envfile])
    monkeypatch.delenv(eastmoney.ENV_KEY, raising=False)

    ok, detail = eastmoney.detect()
    assert ok is True, f"真有 key 却判不可用：{detail}"


# ── 回撤：上游「全 0」是缺位，不是真的没有回撤
#
# 实测：`fund 110011` / `fund 163406` 的 /api/fund/performance/drawdowns 全返回 0，
# 而同一份载荷里近 1 年回报是 −29.43%——一只近一年跌近三成的基金不可能最大回撤为 0。
# 旧实现把缺位渲染成 0.0，让下游框架把它当事实用。

def test_zero_drawdown_is_treated_as_missing() -> None:
    from sources.hithink import _dd

    assert _dd(0) is None, "全 0 回撤被当成有效值"
    assert _dd(0.0) is None
    assert _dd(None) is None
    # 反向：真实负回撤必须保留
    assert _dd(-12.5) == -12.5
    assert _dd(-0.3) == -0.3


# ── 输入层失败必须终止整条链，不能换源去猜
#
# 实测（2026-09-22）：`invest-cli fund -1` 时同花顺正确报「多个候选无法唯一消歧」，
# 但 route 按「整单回退」继续问 ttskill——而 ttskill 自己也会模糊解析，
# 于是同一输入在不同时刻返回**两只不同基金**（先 003376、后 006961），rc=0、无告警。
# 消歧失败是「输入不足以定位标的」，不是「这个源不可用」。

def test_ambiguous_input_stops_the_chain(monkeypatch) -> None:
    from sources.route import fetch

    invoked = []

    def _ambiguous(sid, kind, arg):
        invoked.append(sid)
        return {"source": sid, "kind": kind, "ok": False, "data": None,
                "error": "多个候选无法唯一消歧: 001.OF 甲, 002.OF 乙", "input_error": True}

    res = fetch("fund", "-1", invoke=_ambiguous, order=["hithink", "ttskill", "eastmoney"])
    assert res["ok"] is False
    assert invoked == ["hithink"], f"输入层失败后仍继续换源去猜：{invoked}"
    assert "无法唯一消歧" in res["error"]


def test_source_level_failure_still_falls_back(monkeypatch) -> None:
    """反向用例：普通的源失败必须照旧回退（不能把孩子跟洗澡水一起倒掉）。"""
    from sources.route import fetch

    invoked = []

    def _invoke(sid, kind, arg):
        invoked.append(sid)
        if sid == "hithink":
            return {"source": sid, "kind": kind, "ok": False, "data": None, "error": "HTTP 500"}
        return {"source": sid, "kind": kind, "ok": True, "data": {"ok": True}, "error": None}

    res = fetch("fund", "110011", invoke=_invoke, order=["hithink", "ttskill"])
    assert res["ok"] is True and res.get("source") == "ttskill"
    assert invoked == ["hithink", "ttskill"]


def test_hithink_marks_ambiguity_as_input_error(monkeypatch) -> None:
    """产生侧：消歧失败的信封必须带 input_error（产消两侧共用同一常量）。"""
    from sources import hithink

    env = hithink._envelope("fund", False, error=f"{hithink.AMBIGUOUS_PREFIX}: 001.OF 甲, 002.OF 乙")
    assert env.get("input_error") is True
    # 反向：普通错误不得被标记（否则会把可回退的失败也终止掉）
    assert "input_error" not in hithink._envelope("fund", False, error="HTTP 500")
    assert "input_error" not in hithink._envelope("fund", True, data={})
