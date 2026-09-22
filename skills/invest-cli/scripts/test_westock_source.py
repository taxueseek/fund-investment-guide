#!/usr/bin/env python3
"""westock 透传适配器回归测试 — 全部离线（subprocess 被替换成假执行器）。

守的是三类「静默出错」：把帮助文本当数据、把裸代码发出去、把失败吞成空串。
这三类在原实现里都发生过，且都不会报错 —— 只会让用户拿到一份看起来正常的错东西。
"""
from __future__ import annotations

import subprocess

import pytest

from sources import westock


class _FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture
def fake_cli(monkeypatch):
    """把 subprocess.run 换成可编程的假执行器，并记录每次 argv。"""
    calls: list[list[str]] = []
    state = {"proc": _FakeProc(out="| code | name |\n| sh600519 | 贵州茅台 |\n")}

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        state["kwargs"] = kwargs
        return state["proc"]

    monkeypatch.setattr(westock.shutil, "which", lambda name: "/fake/westock")
    monkeypatch.setattr(westock.subprocess, "run", fake_run)
    return calls, state


# ── ① 代码位置归一化：只动该动的那个位置 ─────────────────────────────────────

def test_code_index_maps_two_level_commands():
    assert westock._code_index(["chip", "600519"]) == 1
    assert westock._code_index(["report", "list", "600519"]) == 2
    assert westock._code_index(["fund", "flow", "600519"]) == 2
    assert westock._code_index(["lhb"]) == -1          # 无标的参数
    assert westock._code_index(["hot", "stock"]) == -1  # 这里的 stock 是榜单名，不是标的


def test_normalize_args_touches_only_the_code_position():
    """同一条命令里的其它纯字母取值**不能**被当成 ticker 归一化。

    这是原实现用「命令 → 下标」表而不是「扫描所有参数」的原因：扫描会把
    `hot stock` 的 stock、`ranking CompScore` 的 metric、`--market hs` 的取值
    一起变成 usSTOCK / usCompScore / usHS —— 不报错，只查无结果。
    """
    assert westock.normalize_args(["chip", "600519"]) == ["chip", "sh600519"]
    assert westock.normalize_args(["hot", "stock"]) == ["hot", "stock"]
    assert westock.normalize_args(["screen", "ranking", "CompScore"]) == \
        ["screen", "ranking", "CompScore"]
    assert westock.normalize_args(["chip", "600519", "--market", "hs"]) == \
        ["chip", "sh600519", "--market", "hs"]
    assert westock.normalize_args(["lhb", "--limit", "10"]) == ["lhb", "--limit", "10"]
    assert westock.normalize_args(["chip", "AAPL"]) == ["chip", "usAAPL"]


def test_surveyed_commands_need_the_prefix():
    """逐个核对「裸代码 → 前缀」的必要性（表里每一项都有实测依据）。

    这些命令裸代码时不报错、只给空或一句像真话的说明（`disclosure 600519` 甚至回
    「未找到业绩预告数据」），所以必须靠这张表在**入口**修好，否则用户以为标的没数据。
    """
    for cmd in ("bond", "disclosure", "risk", "score", "esg", "chip", "finance",
                "shareholder", "dividend", "quote", "kline", "minute", "profile",
                "technical", "consensus", "events"):
        assert westock._code_index([cmd, "600519"]) == 1, cmd
    # 两级命令：第二级是子命令名，下标落在第 3 个参数上
    for cmd, sub in (("report", "list"), ("news", "list"), ("fund", "flow"),
                     ("etf", "profile"), ("etf", "holdings")):
        assert westock._code_index([cmd, sub, "600519"]) == 2, f"{cmd} {sub}"
    assert westock.normalize_args(["bond", "113050"]) == ["bond", "sh113050"]
    assert westock.normalize_args(["disclosure", "600519"]) == ["disclosure", "sh600519"]


def test_rating_must_not_be_normalized():
    """`rating` 是唯一的反例：它要**裸代码**，加前缀反而查不到。

    实测：`rating AAPL` → 表格、`rating usAAPL` → 空；`rating 00700` → 表格、
    `rating hk00700` → 空。这条断言的作用是拦住后人「顺手补齐」。
    """
    assert westock._code_index(["rating", "AAPL"]) == -1
    assert westock.normalize_args(["rating", "AAPL"]) == ["rating", "AAPL"]
    assert westock.normalize_args(["rating", "00700"]) == ["rating", "00700"]


def test_normalize_args_leaves_flags_alone():
    """位置上是旗标时不动（`quote -h` 这类）。"""
    assert westock.normalize_args(["quote", "--date", "2026-09-22"]) == \
        ["quote", "--date", "2026-09-22"]


# ── ② 帮助文本不是数据 ───────────────────────────────────────────────────────

_HELP_OUT = ("宏观经济数据查询。子命令：list / indicator / expect。\n\n"
             "Group: 宏观\n\nUsage:\n  westock macro [flags]\n\n"
             "Available Commands:\n  expect  预期日历\n\n")


def test_help_text_is_rejected_as_data(fake_cli):
    """参数没对上子命令时 CLI 打帮助 + rc=0 —— 必须报错，不能当数据回。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out=_HELP_OUT)
    res = westock.call(["macro", "gdp"])
    assert res["ok"] is False
    assert "帮助文本" in res["error"] and "不是数据" in res["error"]


def test_notice_output_is_rejected_as_data(fake_cli):
    """限流通告也是「rc=0 但不是数据」（实测：m5 密集调用后 CLI 打印
    「请求过于频繁，请稍后再试」并 rc=0）。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out="请求过于频繁，请稍后再试\n")
    res = westock.call(["kline", "sh600519", "--period", "m5"])
    assert res["ok"] is False
    assert "通告" in res["error"]


@pytest.mark.parametrize("out,argv", [
    # 以下 7 条来自独立验证会话给出的反例，全部是 vendor 的 rc=0 伪成功。
    # 首版判据两道门各漏一半：长度门(60) 挡住 67 字的失败句、正则缺「未找到/数据为空/未识别」。
    ("查询策略选股失败：[code=1620053001] error_type=2 suggest=3 msg=service error\n",
     ["screen", "strategy", "--type", "bogus_xyz"]),
    ("查询策略选股失败：[code=1620053001] error_type=2 suggest=3 msg=service error\n",
     ["screen", "strategy", "--type", "高股息"]),
    ("未识别的宏观指标: 中国GDP\n", ["macro", "indicator", "中国GDP"]),
    ("未识别的宏观指标: bogus_ind\n", ["macro", "indicator", "bogus_ind"]),
    ('不支持的 K 线周期 "季"。合法取值: m1 m5 m15 m30 m60 m120 day week month season year\n',
     ["kline", "600519", "--period", "季"]),
    ("未找到行情数据\n", ["quote", "sh113050"]),
    ("数据为空\n", ["chip", "000000"]),
])
def test_all_rc0_false_successes_are_rejected(fake_cli, out, argv):
    """rc=0 + 有输出 + 答案是错的 —— 这类比报错更严重，必须全部判为失败。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out=out)
    res = westock.call(argv)
    assert res["ok"] is False, f"伪成功漏过: {argv} -> {out[:40]!r}"


def test_service_error_now_gets_the_domain_hint(fake_cli):
    """`service error` 这条路径原先**永远不触发**取值域提示。

    原因：提示只在 `_run` 抛错时调用，而 vendor 对 service error 给的是 rc=0、不抛错。
    现在这类输出先被判为「不是数据」，提示才有机会出现。
    """
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out="查询策略选股失败：msg=service error\n")
    # list_values 会再调一次 CLI，让它返回真实取值域
    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if "--list" in cmd:
            return _FakeProc(rc=0, out="# 基本面策略\n  big_cap  行业高增长\n  high_dividend  高股息\n")
        return _FakeProc(rc=0, out="查询策略选股失败：msg=service error\n")
    westock.subprocess.run = fake_run
    res = westock.call(["screen", "strategy", "--type", "bogus"])
    assert res["ok"] is False
    assert "high_dividend" in res["error"], "提示里必须出现真实取值"
    assert "# 基本面策略" not in res["error"], "分组标题不是取值，不该混进取值清单"


def test_survey_confirmed_notice_shapes_are_rejected(fake_cli):
    """45 个子命令普查里确认的两条伪成功（rc=0 但不是数据）。"""
    calls, state = fake_cli
    for out in ("bond 仅支持沪深可转债代码\n",
                "期货合约资料。行情用 quote；搜索请用 search --type futures\n\n"
                "Group: 期货\n\nUsage:\n  westock futures [flags]\n"):
        state["proc"] = _FakeProc(rc=0, out=out)
        res = westock.call(["bond", "113050"] if out.startswith("bond") else ["futures", "list"])
        assert res["ok"] is False, f"伪成功漏过: {out[:40]!r}"


def test_legit_non_table_outputs_are_not_blocked(fake_cli):
    """合法但**不是表格**的输出不能误伤（普查里 4 条）。

    这四条是真实数据：`macro list` 的指标清单、`events`/`buyback` 的「数据为空」标题、
    `screen strategy --list` 的取值清单。判据只要稍一放宽成「没有表格就是通告」，
    它们就会被拦掉 —— 那是比漏判更糟的误伤。
    """
    calls, state = fake_cli
    samples = [
        "📊 宏观指标清单\n\n══ cn 中国 ══\n  ── GDP ──\n    cn_gdp   [year] GDP数量指标\n",
        "# 个股事件 (2026-09-22)\n\n数据为空\n",
        "#### sh600519\n\n区间内无回购数据\n",
        "# 基本面策略\n\n  big_cap  行业高增长\n  high_dividend  高股息\n",
    ]
    for out in samples:
        state["proc"] = _FakeProc(rc=0, out=out)
        res = westock.call(["macro", "list"])
        assert res["ok"] is True, f"真实数据被误伤: {out[:40]!r}"


def test_table_data_is_not_mistaken_for_a_notice(fake_cli):
    """真数据（markdown 表格）不能被通告判据误伤。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out="| date | close |\n| --- | --- |\n| 2026-09-22 | 1253.8 |\n")
    assert westock.call(["kline", "sh600519"])["ok"] is True


def test_nul_argument_is_rejected_readably(fake_cli):
    """含 NUL 的参数原本会在 subprocess 里抛 ValueError 穿透调用方。"""
    res = westock.call(["chip", "600519\x00"])
    assert res["ok"] is False and "NUL" in res["error"]


def test_non_string_arguments_are_ignored(fake_cli):
    """非字符串入参（None/数字）不得让 subprocess 抛 TypeError。"""
    calls, state = fake_cli
    res = westock.call(["chip", None, "600519"])
    assert res["ok"] is True
    assert "None" not in " ".join(calls[-1])


def test_explicit_help_request_passes_through(fake_cli):
    """调用方主动要帮助时，帮助就是正确结果。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out=_HELP_OUT)
    res = westock.call(["macro", "--help"])
    assert res["ok"] is True
    assert "Available Commands" in res["data"]["output"]


def test_help_looking_data_is_not_blocked(fake_cli):
    """输出里带 'Flags:' 字样但其实不是帮助页时不能误判（判据要求 Usage: 同时在场）。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out="| code | note |\n| sh600519 | Flags: none |\n")
    assert westock.call(["chip", "600519"])["ok"] is True


# ── ③ 失败不吞成空串（rc≠0 / rc=0 但无输出） ─────────────────────────────────

def test_nonzero_exit_becomes_readable_error(fake_cli):
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=1, out="", err="错误: 股票代码错误")
    res = westock.call(["chip", "600519"])
    assert res["ok"] is False
    assert "股票代码错误" in res["error"] and "rc=1" in res["error"]


def test_rc0_but_empty_output_is_failure(fake_cli):
    """rc=0 但没输出也算失败：那是「跑通了但没数据」的假成功。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out="   \n")
    res = westock.call(["chip", "600519"])
    assert res["ok"] is False
    assert "没有输出" in res["error"]


def test_subprocess_encoding_is_pinned(fake_cli):
    """spawn 边界固定 UTF-8：交给 locale 猜编码会让非 UTF-8 系统整段解码失败。"""
    calls, state = fake_cli
    westock.call(["chip", "600519"])
    kw = state["kwargs"]
    assert kw.get("encoding") == "utf-8" and kw.get("errors") == "replace"


# ── ④ 通用错误要给方向 ───────────────────────────────────────────────────────

def test_generic_service_error_gets_a_hint(fake_cli):
    """`service error` 这类通用错误要附上「去哪查真实取值域」。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=1, out="", err="执行失败: service error")
    res = westock.call(["screen", "strategy", "高股息"])
    assert res["ok"] is False
    assert "--list" in res["error"]
    assert "high_dividend" in res["error"]


def test_specific_error_gets_no_hint(fake_cli):
    """已经是可读的具体错误时不要画蛇添足。"""
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=1, out="", err="错误: 请提供策略名称（--type）或使用 --list")
    res = westock.call(["screen", "strategy"])
    assert "--list" in res["error"]
    assert "英文标识符" not in res["error"]


# ── ⑤ 其它边界 ──────────────────────────────────────────────────────────────

def test_no_args_gives_command_tree_hint():
    res = westock.call([])
    assert res["ok"] is False and "命令树" in res["error"]


def test_detect_requires_runnable_binary(monkeypatch):
    """可用性 = 二进制在 **且** 跑得起来；只有文件存在不算（原技能栽在这里）。"""
    monkeypatch.setattr(westock.shutil, "which", lambda name: None)
    ok, detail = westock.detect()
    assert ok is False and "未找到" in detail

    monkeypatch.setattr(westock.shutil, "which", lambda name: "/fake/westock")
    monkeypatch.setattr(westock.subprocess, "run",
                        lambda cmd, **kw: _FakeProc(rc=2, out="", err="boom"))
    ok, detail = westock.detect()
    assert ok is False and "退出码 2" in detail

    monkeypatch.setattr(westock.subprocess, "run",
                        lambda cmd, **kw: _FakeProc(rc=0, out="Usage:"))
    ok, _detail = westock.detect()
    assert ok is True


def test_list_values_parses_rows(fake_cli):
    calls, state = fake_cli
    state["proc"] = _FakeProc(rc=0, out="\n# 基本面策略\n  big_cap  行业高增长\n  high_dividend  高股息\n")
    res = westock.list_values(["screen", "strategy"])
    assert res["ok"] is True
    assert "high_dividend  高股息" in res["data"]["values"]
    assert calls[-1][-1] == "--list"


def test_chinese_name_in_code_position_is_resolved(fake_cli, monkeypatch):
    """中文名走腾讯搜索解析（复用同一实现，不另写一份映射表）。"""
    calls, state = fake_cli
    monkeypatch.setattr("sources.tencent.resolve_name", lambda name: "sh600519")
    westock.call(["chip", "贵州茅台"])
    # argv = [二进制, 子命令, 代码, ...]：断言「送出的是什么代码」
    assert calls[-1][2] == "sh600519"


def test_resolution_failure_falls_through_to_cli_error(fake_cli, monkeypatch):
    """解析通道不可用时原样放行，由 CLI 报错 —— 不猜、不静默改标的。"""
    calls, state = fake_cli

    def boom(name):
        raise RuntimeError("腾讯不可达")
    monkeypatch.setattr("sources.tencent.resolve_name", boom)
    state["proc"] = _FakeProc(rc=1, out="", err="错误: 股票代码错误")
    res = westock.call(["chip", "贵州茅台"])
    assert res["ok"] is False
    assert calls[-1][2] == "贵州茅台"       # 原样送出，没有被改成别的标的
