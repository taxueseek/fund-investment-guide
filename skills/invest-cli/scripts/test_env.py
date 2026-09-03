#!/usr/bin/env python3
"""环境变量识别器测试 — 不依赖真实 launchctl/rc。

覆盖：rc 文件解析（引号/注释/命令替换跳过/后加载覆盖）、
进程环境优先于 rc、launchctl 分支可注入。
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import sources.env as env  # noqa: E402


def test_rc_parse_basic(tmp_path) -> None:
    zshenv = tmp_path / ".zshenv"
    zshrc = tmp_path / ".zshrc"
    zshenv.write_text('export EASTMONEY_APIKEY="from_zshenv_123"\n', encoding="utf-8")
    zshrc.write_text("export EASTMONEY_APIKEY=from_zshrc_456\n", encoding="utf-8")
    assert env.read_rc_var("EASTMONEY_APIKEY", [zshenv, zshrc]) == "from_zshrc_456"


def test_rc_quotes_and_comment() -> None:
    rc = Path("/tmp/x")
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".zshrc"
        p.write_text("VAR='abc # not comment'  # real comment\n", encoding="utf-8")
        assert env.read_rc_var("VAR", [p]) == "abc # not comment"


def test_rc_skip_command_substitution() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / ".zshrc"
        p.write_text("export SECRET=$(echo hi)\nVAR='plain_ok'\n", encoding="utf-8")
        assert env.read_rc_var("SECRET", [p]) == ""
        assert env.read_rc_var("VAR", [p]) == "plain_ok"


def test_process_env_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EASTMONEY_APIKEY", "from_process")
    rc = tmp_path / ".zshrc"
    rc.write_text("export EASTMONEY_APIKEY=from_rc\n", encoding="utf-8")
    assert env.read_env("EASTMONEY_APIKEY") == "from_process"


def test_launchctl_injectable(monkeypatch) -> None:
    calls: list[str] = []

    def fake_getenv(name: str) -> str:
        calls.append(name)
        return "from_launchctl"

    monkeypatch.setattr(env, "_launchctl_getenv", fake_getenv)
    monkeypatch.delenv("LAUNCHTEST_VAR", raising=False)
    assert env.read_env("LAUNCHTEST_VAR") == "from_launchctl"
    assert calls == ["LAUNCHTEST_VAR"]


if __name__ == "__main__":
    test_rc_parse_basic(Path(__import__("tempfile").gettempdir()))
    test_rc_quotes_and_comment()
    test_rc_skip_command_substitution()
    print("test_env: OK")
