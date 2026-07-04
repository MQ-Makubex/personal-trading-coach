#!/usr/bin/env python3
"""Generate a factual local account ledger report."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from render_markdown import build_html, render_markdown


DEFAULT_SQLITE = Path("state/account_ledger.sqlite")


def connect(sqlite_path: Path) -> sqlite3.Connection:
    if not sqlite_path.exists():
        raise SystemExit(f"未找到账本数据库：{sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def collect(conn: sqlite3.Connection, limit: int) -> dict[str, Any]:
    return {
        "summary": rows(
            conn,
            """
            select
              count(*) as trade_rows,
              count(distinct stock_code) as stock_count,
              min(trade_date) as first_trade_date,
              max(trade_date) as last_trade_date,
              round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
              round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
              round(sum(abs(coalesce(amount,0))), 2) as gross_turnover,
              round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as total_fees
            from trades
            """,
        ),
        "fee_drag": rows(
            conn,
            """
            select
              substr(trade_date, 1, 7) as month,
              count(*) as trade_rows,
              round(sum(abs(coalesce(amount,0))), 2) as gross_turnover,
              round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees,
              round(case when sum(abs(coalesce(amount,0))) = 0 then null else sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)) / sum(abs(coalesce(amount,0))) * 10000 end, 2) as fee_bps
            from trades
            group by month
            order by month
            """,
        ),
        "activity": rows(
            conn,
            """
            select
              trade_date,
              count(*) as trade_rows,
              count(distinct stock_code) as stocks,
              round(sum(abs(coalesce(amount,0))), 2) as gross_turnover,
              round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees
            from trades
            group by trade_date
            order by trade_date desc
            limit ?
            """,
            (limit,),
        ),
        "by_stock": rows(
            conn,
            """
            select
              stock_code,
              stock_name,
              count(*) as trade_rows,
              sum(case when side = 'BUY' then 1 else 0 end) as buy_rows,
              sum(case when side = 'SELL' then 1 else 0 end) as sell_rows,
              round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
              round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
              round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees,
              round(sum(case when side = 'SELL' then amount else 0 end) - sum(case when side = 'BUY' then amount else 0 end) - sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as cash_difference_not_realized_pnl
            from trades
            group by stock_code, stock_name
            order by trade_rows desc, abs(cash_difference_not_realized_pnl) desc
            limit ?
            """,
            (limit,),
        ),
        "t_candidates": rows(
            conn,
            """
            select
              trade_date,
              stock_code,
              stock_name,
              sum(case when side = 'BUY' then 1 else 0 end) as buy_rows,
              sum(case when side = 'SELL' then 1 else 0 end) as sell_rows,
              round(sum(case when side = 'BUY' then quantity else 0 end), 2) as buy_qty,
              round(sum(case when side = 'SELL' then quantity else 0 end), 2) as sell_qty,
              round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
              round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
              round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees
            from trades
            group by trade_date, stock_code, stock_name
            having buy_rows > 0 and sell_rows > 0
            order by trade_date desc, stock_code
            limit ?
            """,
            (limit,),
        ),
        "recent": rows(
            conn,
            """
            select
              trade_date,
              trade_time,
              stock_code,
              stock_name,
              side,
              quantity,
              price,
              amount,
              net_amount,
              round(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0), 2) as fees
            from trades
            order by trade_date desc, trade_time desc, stock_code
            limit ?
            """,
            (limit,),
        ),
    }


def table(data: list[dict[str, Any]]) -> list[str]:
    if not data:
        return ["无数据。"]
    headers = list(data[0].keys())
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in data:
        lines.append("| " + " | ".join("" if row.get(header) is None else str(row.get(header)) for header in headers) + " |")
    return lines


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 账户表现事实报告 - {report['report_date']}",
        "",
        "本报告只基于本地历史交易底账，做事实查询和费用统计；不预测未来，不给买卖建议。",
        "",
        "## 核心概览",
        "",
        *table(report["summary"]),
        "",
        "## 费用拖累",
        "",
        *table(report["fee_drag"]),
        "",
        "## 近期交易活动",
        "",
        *table(report["activity"]),
        "",
        "## 单票现金差额",
        "",
        "`cash_difference_not_realized_pnl` 是现金流差额视图；如果仍有持仓，它不等于已实现盈亏。",
        "",
        *table(report["by_stock"]),
        "",
        "## 日内同票买卖候选",
        "",
        *table(report["t_candidates"]),
        "",
        "## 最近成交",
        "",
        *table(report["recent"]),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="从本地历史交易底账生成账户事实报告。")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--json", type=Path, default=Path("reports/account_report.json"))
    parser.add_argument("--md", type=Path, default=Path("reports/account_report.md"))
    parser.add_argument("--html", type=Path, default=Path("reports/account_report.html"))
    args = parser.parse_args()

    with connect(args.sqlite) as conn:
        report = collect(conn, args.limit)
    report["report_date"] = date.today().isoformat()
    report["sqlite"] = str(args.sqlite)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = markdown(report)
    args.md.write_text(md, encoding="utf-8")
    args.html.write_text(build_html("账户表现事实报告", render_markdown(md)), encoding="utf-8")
    print(f"account_report_json: {args.json}")
    print(f"account_report_md: {args.md}")
    print(f"account_report_html: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
