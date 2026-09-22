"""命令行输出与本地状态的守卫 — 不联网。

守护的是「**用户看到的那一层**」：

- stderr 是错误通道，不该被库噪音（urllib3 告警、yfinance 的裸 HTTP 响应体）占据。
- 自选股是用户数据，必须落在 state_root 而不是会被系统清理的缓存目录。
- 选股输出的「还有 N 条结果」必须按**实际打印的行数**算。
- 选股回包不是 JSON 时要报错，不能抛裸异常。

缓存/状态目录隔离由 conftest.py 统一提供。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent

# ── 1. stderr 不得被库噪音占据

def test_urllib3_warning_is_suppressed_on_import() -> None:
    """导入 requests 不得向 stderr 打印 urllib3 告警（会污染错误信息）。

    该告警继承链为 NotOpenSSLWarning → SecurityWarning → Warning，
    与 UserWarning 无关；用 UserWarning 或 message 正则均拦不住。

    契约要求的是「模块导入先装过滤器、requests 的首次导入在其后」——
    cmd_stock/cmd_fund 现在把 `import requests` 下沉到了 query_eastmoney()
    里（省 70ms 的模块级 import），所以这里必须**显式再导一次 requests**，
    否则本用例会退化成「只导入两个 cmd 模块、requests 从未被导入」的空断言。
    """
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", "import cmd_stock; import cmd_fund; import requests"],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "NotOpenSSLWarning" not in combined, f"stderr 被库噪音污染: {combined[:200]}"


def test_heavy_libs_are_not_imported_at_module_scope() -> None:
    """反回归：重库不得在模块顶层 import（实测每次调用白付的量）。

    `requests` 的 import 自耗时实测约 70ms（含 urllib3/certifi 一整串），
    而它只服务东财**兜底**路径；放在 cmd_stock/cmd_fund 顶层等于每次
    `invest-cli stock` / `fund` 先白付 70ms，无论走不走东财。
    yaml 同理（约 9ms），只服务配置读取，已下沉到 sources.load_registry()。
    """
    import ast

    for rel, forbidden in (
        ("cmd_stock.py", "requests"),
        ("cmd_fund.py", "requests"),
        ("sources/__init__.py", "yaml"),
    ):
        tree = ast.parse((_SCRIPTS / rel).read_text(encoding="utf-8"))
        top = set()
        for node in tree.body:  # 只看模块顶层，函数体内的下沉导入不算
            if isinstance(node, ast.Import):
                top.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top.add(node.module.split(".")[0])
        assert forbidden not in top, (
            f"{rel} 顶层又 import 了 {forbidden}——每次调用都会白付一次重库导入"
        )

# ── 2. watchlist 落在用户数据目录，不是缓存目录

def test_watchlist_uses_state_root(monkeypatch, tmp_path) -> None:
    """自选股是用户数据：放缓存目录会被系统清理清掉，也会与缓存语义混淆。"""
    import cmd_watchlist

    monkeypatch.setenv("INVEST_CLI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cmd_watchlist, "_LEGACY_FILE", tmp_path / "nope.json")

    path = cmd_watchlist.watch_file()
    assert str(path).startswith(str(tmp_path / "state")), "watchlist 未走 state_root"

    assert cmd_watchlist.add("005827", "易方达蓝筹", "fund")["ok"] is True
    assert [i["code"] for i in cmd_watchlist._load()] == ["005827"]

# ── 3. 选股输出：剩余条数必须按实际打印行数算

def _screen_rows(n: int) -> str:
    return "|代码|名称|\n|---|---|\n" + "".join(f"|{i:06d}|银行{i}|\n" for i in range(n))


def _fake_screen(monkeypatch, *, rows: int, security_count: int) -> None:
    payload = {"data": {"data": {"partialResults": _screen_rows(rows),
                                 "securityCount": security_count, "totalCondition": ""}}}
    monkeypatch.setattr("sources.route.fetch", lambda kind, arg, **kw: {
        "source": "eastmoney", "kind": kind, "ok": True, "data": payload, "error": None})


def test_screen_remaining_count_uses_actual_rows(monkeypatch, capsys) -> None:
    """东财 partialResults 只带首页（实测 pageSize=20 时仅 10 行），
    旧写法按固定 15 算剩余，17 条结果会说「还有 2 条」而实际少 7 条。"""
    import cmd_screen

    _fake_screen(monkeypatch, rows=10, security_count=17)
    assert cmd_screen.run("x") == 0

    out = capsys.readouterr().out
    assert "还有 7 条结果" in out, f"剩余条数算错：{out!r}"
    assert "还有 2 条结果" not in out


def test_screen_full_page_has_no_remaining_line(monkeypatch, capsys) -> None:
    """反向用例：条数与首页行数一致时不得多打一行「还有 N 条」。"""
    import cmd_screen

    _fake_screen(monkeypatch, rows=10, security_count=10)
    assert cmd_screen.run("x") == 0

    assert "还有" not in capsys.readouterr().out

# ── 4. 选股回包非 JSON 时要报错，不能抛出裸异常

def test_screen_non_json_body_is_reported(monkeypatch) -> None:
    import sources.eastmoney as em

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(em, "load_api_key", lambda: "k")
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Resp())

    res = em.screen("x")
    assert res["ok"] is False
    assert "非 JSON" in res["error"]


def test_screen_null_business_payload_does_not_crash(monkeypatch, capsys) -> None:
    """上游业务失败时 data.data 可能为 null（实测空条件即如此）。

    原始诉求（保留）：旧写法 `result["data"]["data"]` 会直接抛 TypeError 裸异常。

    本轮收紧（实测发现「上游没答」与「答了但零结果」被合并成同一句话且 rc=0）：
    结果体缺失 = 上游没答上来，必须 rc=1 并说明原因；只有**拿到结果体**而
    没有匹配行时，「未找到结果」才是真话（见
    test_screen_genuine_zero_results_stays_success）。
    """
    import cmd_screen

    monkeypatch.setattr("sources.route.fetch", lambda kind, arg, **kw: {
        "source": "eastmoney", "kind": kind, "ok": True,
        "data": {"data": None}, "error": None})

    rc = cmd_screen.run("")
    captured = capsys.readouterr()
    assert rc == 1, "结果体缺失被当成「零结果」——调用方会把失败读成成功"
    assert "上游未返回结果体" in captured.err
    assert "未找到结果" not in captured.out
    assert "Traceback" not in captured.err


def test_screen_missing_count_does_not_crash(monkeypatch, capsys) -> None:
    """securityCount 缺失/为 null 时按 0 算，不得在减法处抛 TypeError。"""
    import cmd_screen

    payload = {"data": {"data": {"partialResults": _screen_rows(3),
                                "securityCount": None, "totalCondition": None}}}
    monkeypatch.setattr("sources.route.fetch", lambda kind, arg, **kw: {
        "source": "eastmoney", "kind": kind, "ok": True, "data": payload, "error": None})

    assert cmd_screen.run("x") == 0
    assert "还有" not in capsys.readouterr().out


def test_yfinance_logger_does_not_pollute_stderr() -> None:
    """yfinance 把原始 HTTP 响应体经 root logger 打到 stderr；必须被压掉。

    否则错误通道里混进整段 `HTTP Error 404: {"quoteSummary":...}`，
    真实原因（守卫给出的中文错误）会被淹没。
    """
    import logging

    import cmd_us  # noqa: F401  导入即装上过滤器

    assert logging.getLogger("yfinance").level >= logging.CRITICAL


# ── 5. 代码域：所问的 kind 与代码号段不匹配时必须拒绝，不能返回假快照
#
# 实测（2026-09-22）：`invest-cli stock 110011` 通过东财的模糊匹配拿到
# 「易方达优质精选混合(QDII)(110011.OF)」，以**行情快照**名义输出：24 个字段
# 里 23 个 `-`，唯一的数字是基金利润被摆在「净利润」栏，退出码 0、warnings 空。
# 这不是数据缺失，是问错了对象——用户/agent 会以为拿到了这只票的行情。
#
# 位置教训（对抗审查发现）：守卫最初写在 `cmd_stock.fetch_stock_with_fallback` 里，
# 于是 `stock 110011` 被拒、`intent deep stock 110011` 仍拿到同一张假快照（rc=0）；
# `intent deep fund` 先问盈米（不经 route），也要单独接。现在判据唯一真源在
# `route.code_domain_error`，主路在 `route.fetch` 里生效，盈米直连那条单独接。

def test_route_fetch_rejects_wrong_code_domain() -> None:
    """主路：route.fetch 在任何网络动作之前就拒绝。"""
    from sources.route import fetch

    invoked = []
    res = fetch("stock", "110011", invoke=lambda *a: invoked.append(a) or {"ok": True, "data": {}})
    assert res["ok"] is False, "基金代码被当成股票取数"
    assert "基金代码" in res["error"] and "invest-cli fund 110011" in res["error"]
    assert invoked == [], "应在取数前拦截，不该发起任何调用"

    res = fetch("stock", "113050")
    assert res["ok"] is False and "可转债" in res["error"]
    res = fetch("fund", "600519")
    assert res["ok"] is False and "股票代码" in res["error"]
    res = fetch("fund", "113050")
    assert res["ok"] is False and "可转债" in res["error"]


def test_code_domain_guard_lets_ambiguous_codes_through(monkeypatch) -> None:
    """守卫只拦**确定段**：000858 这类与基金号段重叠的必须继续放行。

    否则会把正常查询误杀（比原缺陷更糟：原来是拿到坏数据，改错是拿不到数据）。
    """
    from _common import kind_from_code
    from sources.route import code_domain_error

    assert kind_from_code("000858") is None, "000858 被误判为确定段"
    assert kind_from_code("茅台") is None
    assert kind_from_code("00700") == "stock"
    assert kind_from_code("110011") == "fund"
    assert kind_from_code("113050") == "bond"

    assert code_domain_error("stock", "600519") == ""
    assert code_domain_error("stock", "000858") == ""
    assert code_domain_error("stock", "茅台") == ""
    assert code_domain_error("stock", "00700") == ""
    assert code_domain_error("fund", "110011") == ""
    assert code_domain_error("fund", "000858") == ""
    # screen 的入参是条件不是代码，us 是境外代码，都不该被这条守卫触碰
    assert code_domain_error("screen", "110011") == ""
    assert code_domain_error("us", "110011") == ""


def test_intent_paths_are_not_bypassed(monkeypatch) -> None:
    """反回归：`intent deep` 的两条入口都必须被同一守卫拦住。

    - `deep stock` 经 route.fetch（已由上面的用例覆盖），这里钉住 deep fund：
      它**先问盈米**，不走 route，实测曾拿到盈米 `{"ok": true, "未识别到具体基金"}` 且 rc=0。
    """
    import cmd_intent

    res = cmd_intent._fund_with_fallback("600519")
    assert res.get("ok") is False, "deep fund 绕过了代码域守卫"
    assert "股票代码" in res["error"]


def test_code_domain_classifier_has_single_source() -> None:
    """反回归：判据与守卫都不得在别处出现第二份实现（历史上重复实体的主要 bug 源）。"""
    import ast

    for rel in ("cmd_intent.py", "cmd_stock.py", "cmd_fund.py", "sources/route.py"):
        tree = ast.parse((_SCRIPTS / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                assert node.name != "kind_from_code", f"{rel} 又定义了一份 kind_from_code"
    src = (_SCRIPTS / "cmd_intent.py").read_text(encoding="utf-8")
    assert "from _common import kind_from_code" in src, "cmd_intent 未复用唯一真源"
    route_src = (_SCRIPTS / "sources" / "route.py").read_text(encoding="utf-8")
    assert "from _common import kind_from_code" in route_src, "route 未复用唯一真源"


# ── 6. 终端表格：adapter 算出的 note 与别名键位都不能被终端层丢掉
#
# 实测：东财港股行情缺失时 payload 带 note「行情缺失（可能停牌/无成交）…」，
# 但终端只印一张全 `-` 的表格；同一 payload 的 `最新价` 也不会出现在
# 「收盘价」行（终端只按同花顺的键名取值）。

def test_stock_terminal_prints_adapter_note() -> None:
    import cmd_stock

    out = cmd_stock.format_terminal(
        {"name": "腾讯控股", "code": "00700", "note": "行情缺失（可能停牌/无成交）", "data": {}}
    )
    assert "行情缺失" in out, "adapter 写明的告警被终端丢掉，用户只看到空表"


def test_stock_terminal_labels_alias_key_by_its_own_name() -> None:
    """落在别名键上的值要用别名当标签，不能张冠李戴。"""
    import cmd_stock

    out = cmd_stock.format_terminal(
        {"name": "腾讯控股", "code": "00700", "data": {"最新价": "451.600"}}
    )
    assert "最新价" in out and "451.600" in out
    assert "收盘价" not in out, "把「最新价」印成「收盘价」是另一种失真"


# ── 7. 环境编码表达不了中文时必须降级输出，不能抛 traceback
#
# 实测：`PYTHONIOENCODING=ascii invest-cli stock 600519` 抛 UnicodeEncodeError
# 并打出完整栈帧（在一轮 78 次真实调用里是唯一一条 traceback）。
# CLI 的输出契约就是中文指标名，环境编码不够用时正确行为是降级，不是崩。

def test_non_utf8_output_encoding_degrades_instead_of_crashing() -> None:
    import os
    import subprocess

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "ascii"
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "invest_cli.py"), "capabilities"],
        capture_output=True,
        env=env,
        timeout=120,
    )
    err = (proc.stderr or b"").decode("utf-8", "replace")
    assert "Traceback" not in err, f"非 UTF-8 环境下抛了 traceback: {err[:300]}"
    assert "UnicodeEncodeError" not in err, f"编码错误外泄: {err[:300]}"
    assert proc.returncode == 0, f"降级输出应保持 rc=0，实际 {proc.returncode}"
    assert proc.stdout, "输出被整个丢掉——应降级输出而不是不输出"


# ── 8. 「上游没答」与「上游答了但零结果」必须分开报
#
# 实测（monkeypatch 上游回包）：`payload.data` 为 null（上游业务失败）与
# `payload.data.data = {"securityCount": 0, ...}`（真的零结果）在旧实现下
# 输出**一模一样**（「未找到结果，请调整筛选条件」）且 rc 都是 0。
# 用户/agent 于是去改一个本来没问题的筛选条件。

def _screen_with(monkeypatch, payload: dict) -> tuple[int, str, str]:
    import io
    import contextlib

    import cmd_screen
    import sources.route as route

    monkeypatch.setattr(route, "fetch", lambda kind, arg, **kw: payload)
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = cmd_screen.run("市盈率低于10的银行股")
    return rc, out.getvalue(), err.getvalue()


def test_screen_upstream_failure_is_not_reported_as_no_results(monkeypatch) -> None:
    """上游业务失败（结果体为 null）必须 rc=1 并说明原因。"""
    payload = {"ok": True, "source": "eastmoney",
               "data": {"success": False, "data": None, "message": "业务失败"}, "error": None}
    rc, out, err = _screen_with(monkeypatch, payload)
    assert rc == 1, "上游没答上来却报 rc=0，调用方会把失败当成功"
    assert "上游未返回结果体" in err, f"未说明真实原因: {err!r}"
    assert "未找到结果" not in out


def test_screen_genuine_zero_results_stays_success(monkeypatch) -> None:
    """反向用例：上游确实答了、只是没匹配到，必须仍是 rc=0。"""
    payload = {"ok": True, "source": "eastmoney",
               "data": {"success": True,
                        "data": {"data": {"securityCount": 0, "partialResults": "", "totalCondition": "x"}}},
               "error": None}
    rc, out, err = _screen_with(monkeypatch, payload)
    assert rc == 0, "真的零结果被当成失败——会把正常查询误报为故障"
    assert "未找到结果" in out


# ── 9. 参数被无声吞掉：sec --filings 非正数必须报错
#
# `sec_edgar.filings` 内部用 `max(1, limit)` 兜底，于是 `--filings 0` 与
# `--filings -3` 都静默返回 1 条——agent 会以为参数生效了。边界上直接报错。

def test_sec_rejects_non_positive_filings(monkeypatch, capsys) -> None:
    import cmd_sec

    called = {"n": 0}
    monkeypatch.setattr(cmd_sec.sec_edgar, "snapshot",
                        lambda *a, **kw: called.__setitem__("n", called["n"] + 1) or {})
    for bad in (0, -1, -99):
        assert cmd_sec.run("AAPL", limit=bad) == 1, f"--filings {bad} 被接受了"
    assert called["n"] == 0, "参数非法时不该发起取数"
    assert "≥1" in capsys.readouterr().err


def test_sec_accepts_positive_filings(monkeypatch) -> None:
    """反向用例：正常参数不能被这条守卫误拦。"""
    import cmd_sec

    seen = {}

    def _fake_snapshot(ticker, forms=None, limit=5):
        seen["limit"] = limit
        return {"ok": True, "data": {"ticker": ticker, "metrics": {}, "filings": []}}

    monkeypatch.setattr(cmd_sec.sec_edgar, "snapshot", _fake_snapshot)
    assert cmd_sec.run("AAPL", limit=3, as_json=True) == 0
    assert seen["limit"] == 3


# ── 10. watchlist：空代码不得写盘；--json 的退出码必须与信封一致
#
# 实测：`watchlist add ""` 往用户自选（持久数据，不是缓存）写了一条
# `{"code": "", ...}` 并 rc=0；`watchlist add <已存在>` 加 --json 时返回 ok=false
# 却仍是 rc=0（终端分支反而正确地 rc=1）——同一结论两条路径相反。

def test_watchlist_rejects_empty_code(monkeypatch, tmp_path, capsys) -> None:
    import cmd_watchlist

    written = []
    monkeypatch.setattr(cmd_watchlist, "_load", lambda: [])
    monkeypatch.setattr(cmd_watchlist, "_save", lambda items: written.append(items))

    for action in ("add", "remove"):
        assert cmd_watchlist.run(action, code="") == 1, f"{action} 接受了空代码"
        assert cmd_watchlist.run(action, code="   ") == 1, f"{action} 接受了空白代码"
    assert written == [], "空代码被写进了用户自选"

    # 反向：正常代码必须照常写入
    assert cmd_watchlist.run("add", code="600519") == 0
    assert written and written[0][0]["code"] == "600519"


def test_watchlist_json_exit_code_matches_envelope(monkeypatch, capsys) -> None:
    """--json 下失败必须 rc=1（此前无论 ok 与否都 return 0）。"""
    import cmd_watchlist

    monkeypatch.setattr(cmd_watchlist, "add",
                        lambda code, name="", typ="": {"source": "watchlist", "ok": False,
                                                       "data": None, "error": "600519 已在自选"})
    assert cmd_watchlist.run("add", code="600519", as_json=True) == 1
    capsys.readouterr()

    monkeypatch.setattr(cmd_watchlist, "add",
                        lambda code, name="", typ="": {"source": "watchlist", "ok": True,
                                                       "data": {"code": code, "added": True}, "error": None})
    assert cmd_watchlist.run("add", code="600519", as_json=True) == 0


# ── 11. stock 走 yfinance 兜底时，表格必须渲染兜底源的载荷结构
#
# 实测（2026-09-22）：A 股无凭据走 yfinance 兜底时，`--json` 有完整数据
# （price 9.04 / pe_trailing 6.41 / market_cap 301084770304），而终端表格印的是
# 「收盘价 - / 开盘价 - / 昨收 - / PE - / PB - / 总市值 -」，财务与年报两个区块
# 整块消失——查到了名字、字段全空。根因：表格只认同花顺/东财的中文键。

def test_stock_terminal_renders_yfinance_fallback() -> None:
    import cmd_stock

    payload = {
        "source": "yfinance", "symbol": "600000", "name": "SHANGHAI PUDONG DEVELOPMENT BANK",
        "currency": "CNY",
        "quote": {"price": 9.04, "pe_trailing": 6.41, "pb": 0.399, "market_cap": 301084770304},
        "financial": {"revenue": 1.7e11, "net_income": 4.4e10, "roe": 0.08},
        "analyst": {}, "risk": {}, "business": {},
        "timestamp": "2026-09-22T18:10:23",
    }
    out = cmd_stock.format_terminal(payload)
    assert "9.04" in out, "价格没渲染出来——又是「JSON 有数、表格是 -」"
    assert "6.41" in out and "0.399" in out
    assert "营收" in out, "财务区块整块消失了"
    assert "yfinance 兜底" in out, "没有标明这是兜底源的数据"


def test_stock_terminal_keeps_cn_shape() -> None:
    """反向用例：同花顺/东财的中文键载荷必须仍走原表格（不能被上面的分支截走）。"""
    import cmd_stock

    out = cmd_stock.format_terminal({
        "name": "贵州茅台", "code": "600519",
        "data": {"收盘价": "1253.8", "市盈率PE(TTM)": "19.25"},
        "quote": {"last": 1253.8},
        "valuation": {"pe_ttm": 19.25},
        "timestamp": "2026-09-22T18:00:00",
    })
    assert "1253.8" in out and "19.25" in out
    assert "yfinance 兜底" not in out


def test_watchlist_defaults_to_list():
    """裸 `watchlist` 必须等同 `watchlist list`。

    真实调用里裸写法（7 次）比 `watchlist list`（6 次）更多，而旧定义把 action
    设成必填，最常见的写法直接拿到 argparse 的 rc=2 + usage —— 用户以为自选股坏了。
    """
    import subprocess
    import sys
    from pathlib import Path

    cli = Path(__file__).resolve().parent / "invest_cli.py"
    bare = subprocess.run([sys.executable, str(cli), "watchlist"],
                          capture_output=True, text=True, encoding="utf-8")
    explicit = subprocess.run([sys.executable, str(cli), "watchlist", "list"],
                              capture_output=True, text=True, encoding="utf-8")
    assert bare.returncode == 0, f"裸 watchlist 退出码 {bare.returncode}: {bare.stderr[:200]}"
    assert bare.returncode == explicit.returncode
    assert bare.stdout == explicit.stdout


def test_kline_routes_unknown_periods_to_cli():
    """原生内核不认识的周期直接交 CLI，别再套一层自相矛盾的模板。

    独立验证抓到的原文案：「原生通道不可用（…不支持周期 '季'…）。分钟级请走
    invest-cli kline <代码> --period 季（自动转 westock CLI）」—— 把用户输入套进
    分钟级的示例里，等于让用户再跑一次刚失败的命令。
    """
    from unittest import mock
    from sources import tencent
    import cmd_kline

    with mock.patch.object(cmd_kline, "_via_cli") as via, \
         mock.patch.object(cmd_kline.tencent, "kline") as native:
        via.return_value = 0
        cmd_kline.run("600519", period="season", limit=3)
        via.assert_called_once()
        args = via.call_args[0]
        assert args[1] == "season", "未知周期应原样交给 CLI，由它给权威取值域"
        # 关键：**不要先试一次原生**再失败。未知周期在原生命中内核里必然失败，
        # 那一趟是白付的往返（约 150ms），也正是旧实现在错误文案里套模板的原因。
        native.assert_not_called()
    # 原生认识的周期不走 CLI
    with mock.patch.object(cmd_kline, "_via_cli") as via, \
         mock.patch.object(tencent, "kline") as native:
        native.return_value = {"ok": True, "data": {"rows": [{"date": "2026-09-22", "open": 1,
                                 "high": 1, "low": 1, "close": 1, "volume": 1}],
                                 "period": "day", "name": "x", "symbol": "sh600519"}}
        cmd_kline.run("600519", period="day", limit=1)
        native.assert_called_once()
        via.assert_not_called()
