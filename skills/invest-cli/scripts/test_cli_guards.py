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
    """
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-c", "import cmd_stock; import cmd_fund"],
        capture_output=True,
        text=True,
        cwd=str(_SCRIPTS),
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    assert "NotOpenSSLWarning" not in combined, f"stderr 被库噪音污染: {combined[:200]}"

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

    旧写法 `result["data"]["data"]` 会直接抛 TypeError 裸异常（用户看到 traceback）。
    """
    import cmd_screen

    monkeypatch.setattr("sources.route.fetch", lambda kind, arg, **kw: {
        "source": "eastmoney", "kind": kind, "ok": True,
        "data": {"data": None}, "error": None})

    assert cmd_screen.run("") == 0
    assert "未找到结果" in capsys.readouterr().out


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
