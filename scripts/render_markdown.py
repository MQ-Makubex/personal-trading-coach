#!/usr/bin/env python3
"""Render a local Markdown note to a self-contained HTML file.

This is intentionally small and dependency-free. It is for coach notes and
templates, not a full Markdown implementation.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


CSS = """
:root {
  --bg: #f6f7f4;
  --paper: #ffffff;
  --ink: #1f2933;
  --muted: #667085;
  --line: #d9ded6;
  --accent: #245b47;
  --danger: #9f1d20;
  --warn: #926200;
  --good: #1f7a4d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.68;
}
main {
  max-width: 980px;
  margin: 32px auto;
  padding: 40px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 18px 45px rgba(31, 41, 51, 0.08);
}
h1, h2, h3 {
  line-height: 1.25;
  margin: 1.4em 0 0.5em;
}
h1 {
  margin-top: 0;
  font-size: 2rem;
  color: var(--accent);
  border-bottom: 2px solid var(--line);
  padding-bottom: 0.55rem;
}
h2 {
  font-size: 1.35rem;
  border-left: 5px solid var(--accent);
  padding-left: 0.65rem;
}
h3 { font-size: 1.08rem; }
p { margin: 0.65em 0; }
ul, ol { padding-left: 1.4rem; }
li { margin: 0.25rem 0; }
code {
  background: #eef2ef;
  padding: 0.12rem 0.32rem;
  border-radius: 4px;
}
pre {
  background: #1f2933;
  color: #f8fafc;
  padding: 1rem;
  border-radius: 8px;
  overflow-x: auto;
}
pre code { background: transparent; padding: 0; color: inherit; }
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1rem 0;
  font-size: 0.95rem;
}
th, td {
  border: 1px solid var(--line);
  padding: 0.5rem 0.6rem;
  vertical-align: top;
}
th {
  background: #eef2ef;
  text-align: left;
}
blockquote {
  margin: 1rem 0;
  padding: 0.2rem 1rem;
  border-left: 4px solid var(--line);
  color: var(--muted);
}
hr { border: 0; border-top: 1px solid var(--line); margin: 2rem 0; }
.meta {
  color: var(--muted);
  font-size: 0.9rem;
  margin-top: -0.2rem;
}
@media (max-width: 720px) {
  main {
    margin: 0;
    padding: 22px;
    border: 0;
    border-radius: 0;
  }
  h1 { font-size: 1.55rem; }
  h2 { font-size: 1.16rem; }
  table { display: block; overflow-x: auto; white-space: nowrap; }
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a Markdown coach note to HTML.")
    parser.add_argument("input", type=Path, help="Input Markdown file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output HTML file")
    parser.add_argument("--title", default=None, help="Optional HTML title")
    return parser.parse_args()


def inline_markup(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def render_table(lines: list[str]) -> str:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return ""
    head, body = rows[0], rows[1:]
    html_lines = ["<table>", "<thead><tr>"]
    html_lines.extend(f"<th>{inline_markup(cell)}</th>" for cell in head)
    html_lines.append("</tr></thead>")
    if body:
        html_lines.append("<tbody>")
        for row in body:
            html_lines.append("<tr>")
            html_lines.extend(f"<td>{inline_markup(cell)}</td>" for cell in row)
            html_lines.append("</tr>")
        html_lines.append("</tbody>")
    html_lines.append("</table>")
    return "\n".join(html_lines)


def render_markdown(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_mode: str | None = None
    table_lines: list[str] = []
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{inline_markup(' '.join(paragraph).strip())}</p>")
            paragraph = []

    def flush_list() -> None:
        nonlocal list_mode
        if list_mode:
            output.append(f"</{list_mode}>")
            list_mode = None

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            output.append(render_table(table_lines))
            table_lines = []

    for raw_line in lines:
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            flush_paragraph()
            flush_list()
            flush_table()
            if in_code:
                output.append(f"<pre><code>{html.escape(chr(10).join(code_lines), quote=True)}</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue

        if in_code:
            code_lines.append(line)
            continue

        if not line.strip():
            flush_paragraph()
            flush_list()
            flush_table()
            continue

        if is_table_line(line):
            flush_paragraph()
            flush_list()
            table_lines.append(line)
            continue
        flush_table()

        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            flush_paragraph()
            flush_list()
            level = len(heading_match.group(1))
            output.append(f"<h{level}>{inline_markup(heading_match.group(2))}</h{level}>")
            continue

        if line.strip() == "---":
            flush_paragraph()
            flush_list()
            output.append("<hr>")
            continue

        quote_match = re.match(r"^>\s?(.*)$", line)
        if quote_match:
            flush_paragraph()
            flush_list()
            output.append(f"<blockquote>{inline_markup(quote_match.group(1))}</blockquote>")
            continue

        bullet_match = re.match(r"^\s*[-*]\s+(.+)$", line)
        if bullet_match:
            flush_paragraph()
            if list_mode != "ul":
                flush_list()
                output.append("<ul>")
                list_mode = "ul"
            output.append(f"<li>{inline_markup(bullet_match.group(1))}</li>")
            continue

        ordered_match = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if ordered_match:
            flush_paragraph()
            if list_mode != "ol":
                flush_list()
                output.append("<ol>")
                list_mode = "ol"
            output.append(f"<li>{inline_markup(ordered_match.group(1))}</li>")
            continue

        flush_list()
        paragraph.append(line.strip())

    flush_paragraph()
    flush_list()
    flush_table()
    if in_code:
        output.append(f"<pre><code>{html.escape(chr(10).join(code_lines), quote=True)}</code></pre>")
    return "\n".join(output)


def build_html(title: str, body: str) -> str:
    safe_title = html.escape(title, quote=True)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="zh-CN">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>{safe_title}</title>",
            f"<style>{CSS}</style>",
            "</head>",
            "<body>",
            "<main>",
            body,
            '<p class="meta">由 personal-trading-coach 本地渲染。历史复盘与风控训练，不荐股，不预测涨跌。</p>',
            "</main>",
            "</body>",
            "</html>",
        ]
    )


def main() -> int:
    args = parse_args()
    markdown_text = args.input.read_text(encoding="utf-8")
    title = args.title or args.input.stem.replace("_", " ")
    body = render_markdown(markdown_text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(title, body), encoding="utf-8")
    print(f"rendered: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
