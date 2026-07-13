#!/usr/bin/env python3
"""Create a pre-trade or intraday discipline guard note."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from render_markdown import build_html, render_markdown


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
TEMPLATE = ROOT / "templates" / "pre_trade_guard.md"


def read_text(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def extract_section(text: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_match = re.search(r"^##\s+", text[start:], re.MULTILINE)
    end = start + next_match.start() if next_match else len(text)
    return text[start:end].strip()


def classify_action(plan_text: str, trigger: str, invalidation: str, position: str) -> list[str]:
    findings: list[str] = []
    if not plan_text.strip():
        findings.append("红牌风险：没有读取到已写好的交易预案。先补预案，再讨论动作。")
    if not trigger.strip():
        findings.append("红牌风险：没有明确触发条件，容易把盘中波动解释成机会。")
    if not invalidation.strip():
        findings.append("红牌风险：没有明确失效条件，亏损后容易补理由。")
    if position and re.search(r"(满仓|梭哈|all\s*in)", position, re.IGNORECASE):
        findings.append("红牌风险：仓位描述包含极端加风险特征。")
    if not findings:
        findings.append("待人工确认：基础条件齐全，但仍需判断是否计划内、是否提前、是否加风险。")
    return findings


def build_guard(args: argparse.Namespace) -> str:
    template = TEMPLATE.read_text(encoding="utf-8").replace("YYYY-MM-DD", args.trade_date)
    plan_text = read_text(args.plan)
    coach_memory = read_text(args.state_dir / "coach_memory.md")
    modes = read_text(args.state_dir / "personal_trading_modes.md")
    storylines = read_text(args.state_dir / "position_storylines.md")

    avoid_modes = extract_section(modes, "应避免")
    repeat_weakness = extract_section(coach_memory, "反复出现的弱点")
    open_storylines = extract_section(storylines, "Open Storylines")
    findings = classify_action(plan_text, args.trigger or "", args.invalidation or "", args.position or "")

    replacements = {
        "- 股票:": f"- 股票: {args.security or '未提供'}",
        "- 拟执行动作:": f"- 拟执行动作: {args.action or '未提供'}",
        "- 仓位:": f"- 仓位: {args.position or '未提供'}",
        "- 触发条件:": f"- 触发条件: {args.trigger or '未提供'}",
        "- 失效条件:": f"- 失效条件: {args.invalidation or '未提供'}",
        "- 止损锚点:": f"- 止损锚点: {args.stop_anchor or '未提供'}",
    }
    body = template
    for source, target in replacements.items():
        body = body.replace(source, target)

    body += "\n## 自动纪律扫描\n\n"
    for finding in findings:
        body += f"- {finding}\n"

    if repeat_weakness:
        body += "\n## 近期反复弱点\n\n" + repeat_weakness + "\n"
    if avoid_modes:
        body += "\n## 应避免模式摘录\n\n" + avoid_modes + "\n"
    if open_storylines:
        body += "\n## 当前持仓故事线摘录\n\n" + open_storylines + "\n"
    if plan_text:
        body += "\n## 已提供预案摘录\n\n" + plan_text + "\n"

    body += "\n## 边界\n\n- 本文件只做风控反问，不输出买入/卖出建议，不预测涨跌。\n"
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="生成盘前/盘中纪律检查 Markdown/HTML。")
    parser.add_argument("--trade-date", default=date.today().isoformat())
    parser.add_argument("--security", default="")
    parser.add_argument("--action", default="")
    parser.add_argument("--position", default="")
    parser.add_argument("--trigger", default="")
    parser.add_argument("--invalidation", default="")
    parser.add_argument("--stop-anchor", default="")
    parser.add_argument("--plan", type=Path, default=None)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("-o", "--output", type=Path, default=Path("reports/intraday_guard.md"))
    parser.add_argument("--html", type=Path, default=None)
    args = parser.parse_args()

    markdown = build_guard(args)
    write_text(args.output, markdown)
    if args.html:
        write_text(args.html, build_html("盘前盘中纪律检查", render_markdown(markdown)))
    print(f"wrote {args.output}")
    if args.html:
        print(f"html: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
