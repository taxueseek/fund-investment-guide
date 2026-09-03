#!/usr/bin/env python3
"""present 场景落地件：本地渲染 HTML → 终端摘要 + 可读正文。

为 intent present 提供 `render_html_summary(path)` 信封接口：
- 不依赖任何外部渲染引擎或 Wind 工具（原 ROUTES 引用的 RenderHtmlToPdf 在
  wind-mcp-skill 七个 server 的工具清单里不存在，属声明即崩溃的死路由）。
- 用标准库 html.parser 提取标题与可见文本，终端直接可读；
  浏览器打开/打印成 PDF 交给用户，不在 CLI 内伪装。
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import sys
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """抽取 <title>、标题层级与块级文本，跳过 script/style。"""

    _SKIP = {"script", "style", "head"}
    _HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str = ""
        self.blocks: list[str] = []
        self._in_skip = 0
        self._in_title = False
        self._buf: list[str] = []
        self._heading_level = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag in self._SKIP:
            self._in_skip += 1
        elif tag in self._HEADINGS:
            self._flush()
            self._heading_level = int(tag[1])
        elif tag in ("p", "div", "li", "tr", "br", "section", "article", "table"):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag in self._SKIP and self._in_skip > 0:
            self._in_skip -= 1
        elif tag in self._HEADINGS:
            self._flush()
            self._heading_level = 0
        elif tag in ("p", "div", "li", "tr", "section", "article", "table"):
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._in_skip:
            return
        if self._heading_level and not self._buf:
            # 标题行优先记录
            self._buf.append("\n" + "#" * self._heading_level + " ")
        self._buf.append(data)

    def _flush(self) -> None:
        text = "".join(self._buf).strip()
        self._buf = []
        if text:
            self.blocks.append(text)

    def close(self) -> None:  # noqa: D102
        super().close()
        self._flush()


def _extract(path: str) -> dict:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception as e:  # 畸形 HTML 也要给可用摘要
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
        return {
            "title": html_mod.unescape(m.group(1)).strip() if m else "",
            "text": re.sub(r"<[^>]+>", " ", raw),
            "parse_error": str(e),
        }
    title = parser.title or next((b.lstrip("# ").strip() for b in parser.blocks
                                   if b.startswith("#")), "")
    text = "\n".join(parser.blocks)
    return {"title": title, "text": text}


def render_html_summary(path: str) -> dict:
    """信封风格：{source, ok, data|error}。data 含 title/text 与提取说明。"""
    p = os.path.expanduser(path)
    if not p or not os.path.isfile(p):
        return {"source": "present", "ok": False, "data": None,
                "error": f"文件不存在: {path}"}
    if os.path.getsize(p) > 5 * 1024 * 1024:
        return {"source": "present", "ok": False, "data": None,
                "error": "文件超过 5MB，请先拆分再渲染"}
    try:
        ext = _extract(p)
    except OSError as e:
        return {"source": "present", "ok": False, "data": None,
                "error": f"读取失败: {e}"}
    text = ext["text"].strip()
    data = {
        "file": p,
        "title": ext.get("title") or os.path.basename(p),
        "text": text[:8000],
        "truncated": len(text) > 8000,
        "note": "本地提取正文供终端阅读；PDF 导出请用浏览器打开打印",
    }
    if ext.get("parse_error"):
        data["warnings"] = [f"HTML 解析异常已降级: {ext['parse_error']}"]
    return {"source": "present", "ok": True, "data": data, "error": None}


def _terminal(data: dict) -> str:
    lines = [f"\n{'=' * 60}", f"  {data['title']} — present 摘要", f"{'=' * 60}", ""]
    lines.append(data["text"])
    if data.get("truncated"):
        lines.append("\n  …（正文超长已截断，完整内容请打开原文件）")
    lines.append(f"\n  文件: {data['file']}")
    if data.get("warnings"):
        lines.append(f"  警告: {'; '.join(data['warnings'])}")
    return "\n".join(lines)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="HTML → 终端摘要")
    parser.add_argument("path", help="HTML 文件路径")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    res = render_html_summary(args.path)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        if res.get("ok"):
            print(_terminal(res["data"]))
        else:
            print(f"错误: {res.get('error')}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
