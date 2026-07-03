#!/usr/bin/env python3
"""Build a Markdown evidence packet from sanitized trade facts and journal text."""

from __future__ import annotations

import argparse
import csv
import html
from pathlib import Path


def read_text(path: Path | None) -> str:
    if not path:
        return ""
    return path.read_text(encoding="utf-8").strip()


def escape_md_cell(value: object) -> str:
    text = str(value or "").replace("|", "\\|").replace("\n", " ")
    return html.escape(text, quote=False)


def security_label(row: dict[str, str]) -> str:
    code = row.get("stock_code", "")
    name = row.get("stock_name", "")
    return f"{code} {name}".strip()


def read_trades(path: Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def trade_table(rows: list[dict[str, str]]) -> list[str]:
    lines = [
        "| Time | Security | Side | Quantity | Price | Amount | Net Amount | Fees |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        fee_total = 0.0
        for field in ("commission", "stamp_tax", "transfer_fee", "other_fee"):
            try:
                fee_total += float(row.get(field) or 0)
            except ValueError:
                pass
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_md_cell(row.get("trade_time", "")),
                    escape_md_cell(security_label(row)),
                    escape_md_cell(row.get("side", "")),
                    escape_md_cell(row.get("quantity", "")),
                    escape_md_cell(row.get("price", "")),
                    escape_md_cell(row.get("amount", "")),
                    escape_md_cell(row.get("net_amount", "")),
                    f"{fee_total:.2f}",
                ]
            )
            + " |"
        )
    if not rows:
        lines.append("|  |  |  |  |  |  |  |  |")
    return lines


def build_packet(args: argparse.Namespace) -> str:
    trades = read_trades(args.trades)
    journal = read_text(args.journal)
    market_view = read_text(args.market_view)
    articles = read_text(args.articles)
    current_positions = read_text(args.positions)
    market_snapshot = read_text(getattr(args, "market_snapshot", None))
    research_pool = read_text(getattr(args, "research_pool", None))

    lines = [
        f"# Evidence Packet - {args.trade_date}",
        "",
        "## Source Checks",
        "",
        f"- Trade source: {escape_md_cell(args.trades) if args.trades else '未提供'}",
        "- Privacy check: 必须先运行 `scripts/privacy_guard.py`，此文件只承接通过检查后的交易事实。",
        "- Market data source: 由教练联网或用户提供后在手记中标明。",
        "- Missing evidence: 对缺失证据的结论写 `无法判断`。",
        "",
        "## Today Trade Facts",
        "",
        *trade_table(trades),
        "",
        "## User Journal",
        "",
        journal or "未提供。",
        "",
        "## Market View To Correct",
        "",
        market_view or "未提供。",
        "",
        "## Market Snapshot",
        "",
        market_snapshot or "未提供。需要联网或用户提供市场事实后再校正。",
        "",
        "## Current Positions",
        "",
        current_positions or "未提供。",
        "",
        "## Article Inputs",
        "",
        articles or "未提供。",
        "",
        "## Research Pool Input",
        "",
        research_pool or "未提供。",
        "",
        "## Coach Work Required",
        "",
        "- 识别今天的交易决策事件。",
        "- 更新持仓故事线。",
        "- 校正用户市场判断，而不是直接接受为事实。",
        "- 写出最重要的一处错误和明日唯一纪律。",
        "- 如果需要明日研究股票池，使用 `templates/research_pool.md`。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="从标准交易事实和用户文本生成证据包 Markdown。")
    parser.add_argument("--trades", type=Path, default=None)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--journal", type=Path, default=None)
    parser.add_argument("--market-view", type=Path, default=None)
    parser.add_argument("--articles", type=Path, default=None)
    parser.add_argument("--positions", type=Path, default=None)
    parser.add_argument("--market-snapshot", type=Path, default=None)
    parser.add_argument("--research-pool", type=Path, default=None)
    parser.add_argument("-o", "--output", type=Path, default=Path("reports/evidence_packet.md"))
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_packet(args), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
