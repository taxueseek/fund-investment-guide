#!/usr/bin/env python3
"""present 场景契约 — 纯本地 HTML，不打网络。"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from cmd_present import render_html_summary  # noqa: E402

SAMPLE = """<html><head><title>测试报告</title>
<script>var x = "<p>不应出现</p>";</script></head>
<body><h1>月度总结</h1><p>第一段内容。</p><p>第二段内容。</p></body></html>"""


def _write(tmp: Path) -> Path:
    p = tmp / "sample.html"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_ok(tmp_path: Path) -> None:
    res = render_html_summary(str(_write(tmp_path)))
    assert res["ok"] is True and res["source"] == "present"
    d = res["data"]
    assert d["title"] == "测试报告"
    assert "月度总结" in d["text"] and "第二段内容" in d["text"]
    assert "不应出现" not in d["text"]  # script 内容必须剔除


def test_missing_file() -> None:
    res = render_html_summary("/tmp/不存在_8f2k.html")
    assert res["ok"] is False and "不存在" in (res["error"] or "")


def test_garbled_html(tmp_path: Path) -> None:
    p = tmp_path / "bad.html"
    p.write_text("<html><body><p>未闭合文本", encoding="utf-8")
    res = render_html_summary(str(p))
    assert res["ok"] is True
    assert "未闭合文本" in res["data"]["text"]


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_ok(Path(td))
        test_missing_file()
        test_garbled_html(Path(td))
    print("test_present: OK")
