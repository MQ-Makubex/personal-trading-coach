#!/usr/bin/env python3
"""Generate a factual local account ledger report."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from ledger_analytics import fifo_analytics
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
    report = {
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
            with trade_cash as (
              select
                stock_code,
                coalesce(max(case when stock_name not like 'XD%' then stock_name end), max(stock_name)) as stock_name,
                count(*) as trade_rows,
                sum(case when side = 'BUY' then 1 else 0 end) as buy_rows,
                sum(case when side = 'SELL' then 1 else 0 end) as sell_rows,
                round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
                round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
                round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees,
                round(sum(coalesce(net_amount,0)), 2) as trade_cash_difference
              from trades
              group by stock_code
            ),
            adjustment_cash as (
              select
                stock_code,
                coalesce(max(case when stock_name not like 'XD%' then stock_name end), max(stock_name)) as stock_name,
                count(*) as cash_adjustment_rows,
                round(sum(coalesce(net_amount,0)), 2) as cash_adjustment_amount
              from cash_adjustments
              group by stock_code
            ),
            all_codes as (
              select stock_code from trade_cash
              union
              select stock_code from adjustment_cash
            )
            select
              c.stock_code,
              coalesce(t.stock_name, a.stock_name) as stock_name,
              coalesce(t.trade_rows, 0) as trade_rows,
              coalesce(t.buy_rows, 0) as buy_rows,
              coalesce(t.sell_rows, 0) as sell_rows,
              coalesce(t.buy_amount, 0) as buy_amount,
              coalesce(t.sell_amount, 0) as sell_amount,
              coalesce(t.fees, 0) as fees,
              coalesce(a.cash_adjustment_rows, 0) as cash_adjustment_rows,
              coalesce(a.cash_adjustment_amount, 0) as cash_adjustment_amount,
              round(coalesce(t.trade_cash_difference, 0) + coalesce(a.cash_adjustment_amount, 0), 2) as cash_difference_not_realized_pnl
            from all_codes c
            left join trade_cash t on t.stock_code = c.stock_code
            left join adjustment_cash a on a.stock_code = c.stock_code
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
    analytics = fifo_analytics(conn)
    report["broker_like_realized_by_stock"] = analytics["broker_like_realized_by_stock"][:limit]
    report["broker_like_realized_lots"] = analytics["broker_like_realized_lots"][:limit]
    report["fifo_realized_by_stock"] = analytics["realized_by_stock"][:limit]
    report["open_positions"] = analytics["open_positions"][:limit]
    report["fifo_realized_lots"] = analytics["realized_lots"][:limit]
    return report


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
        "## 券商成本口径已实现盈亏",
        "",
        "本节按卖出前的券商滚动持仓成本估算：买入增加成本，卖出用卖出净额冲减成本；清仓后的盈亏残差只在同日回补时继续影响显示成本，隔日重新开仓重置。此口径用于教练手记和个人站主展示。",
        "",
        *table(report["broker_like_realized_by_stock"]),
        "",
        "## 当前剩余仓位成本",
        "",
        "本节只来自历史成交推算，不读取资金余额或券商持仓截图。",
        "",
        *table(report["open_positions"]),
        "",
        "## 最近券商口径平仓批次",
        "",
        *table(report["broker_like_realized_lots"]),
        "",
        "## FIFO 已实现盈亏审计",
        "",
        "本节保留先进先出估算用于审计，不作为教练手记和个人站主展示口径。买入成本包含买入费用，卖出收入扣除卖出费用；若历史数据不完整，`unmatched_sell_quantity` 会提示存在无法匹配的卖出。",
        "",
        *table(report["fifo_realized_by_stock"]),
        "",
        "## 最近 FIFO 闭合批次",
        "",
        *table(report["fifo_realized_lots"]),
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
