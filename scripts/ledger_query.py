#!/usr/bin/env python3
"""Run factual account-ledger queries."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from ledger_analytics import fifo_analytics


def connect(sqlite_path: Path) -> sqlite3.Connection:
    if not sqlite_path.exists():
        raise SystemExit(f"未找到底账数据库：{sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def print_rows(rows: list[sqlite3.Row] | list[dict[str, object]]) -> None:
    if not rows:
        print("无结果")
        return
    headers = rows[0].keys()
    print("\t".join(headers))
    for row in rows:
        print("\t".join("" if row[key] is None else str(row[key]) for key in headers))


def query_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          count(*) as trade_rows,
          count(distinct stock_code) as stock_count,
          round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
          round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as total_fees
        from trades
        """
    ).fetchall()


def query_fees(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          substr(trade_date, 1, 7) as month,
          count(*) as trade_rows,
          round(sum(coalesce(commission,0)), 2) as commission,
          round(sum(coalesce(stamp_tax,0)), 2) as stamp_tax,
          round(sum(coalesce(transfer_fee,0)), 2) as transfer_fee,
          round(sum(coalesce(other_fee,0)), 2) as other_fee,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as total_fees
        from trades
        group by month
        order by month
        """
    ).fetchall()


def query_frequency(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          trade_date,
          count(*) as trade_rows,
          count(distinct stock_code) as stocks,
          sum(case when side = 'BUY' then 1 else 0 end) as buy_rows,
          sum(case when side = 'SELL' then 1 else 0 end) as sell_rows
        from trades
        group by trade_date
        order by trade_date
        """
    ).fetchall()


def query_by_stock(conn: sqlite3.Connection, stock_code: str | None) -> list[sqlite3.Row]:
    where = "where stock_code = ?" if stock_code else ""
    params = (stock_code,) if stock_code else ()
    return conn.execute(
        f"""
        select
          stock_code,
          stock_name,
          count(*) as trade_rows,
          sum(case when side = 'BUY' then 1 else 0 end) as buy_rows,
          sum(case when side = 'SELL' then 1 else 0 end) as sell_rows,
          round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
          round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees
        from trades
        {where}
        group by stock_code, stock_name
        order by trade_rows desc, stock_code
        """,
        params,
    ).fetchall()


def query_monthly(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          substr(trade_date, 1, 7) as month,
          count(*) as trade_rows,
          count(distinct stock_code) as stocks,
          round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
          round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees
        from trades
        group by month
        order by month
        """
    ).fetchall()


def query_fee_drag(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          substr(trade_date, 1, 7) as month,
          count(*) as trade_rows,
          round(sum(abs(coalesce(amount,0))), 2) as gross_turnover,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees,
          round(
            case when sum(abs(coalesce(amount,0))) = 0 then null
            else sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)) / sum(abs(coalesce(amount,0))) * 10000
            end,
            2
          ) as fee_bps
        from trades
        group by month
        order by month
        """
    ).fetchall()


def query_activity(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          trade_date,
          count(*) as trade_rows,
          count(distinct stock_code) as stocks,
          round(sum(abs(coalesce(amount,0))), 2) as gross_turnover,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees,
          round(
            case when sum(abs(coalesce(amount,0))) = 0 then null
            else sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)) / sum(abs(coalesce(amount,0))) * 10000
            end,
            2
          ) as fee_bps
        from trades
        group by trade_date
        order by trade_date
        """
    ).fetchall()


def query_recent(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    return conn.execute(
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
    ).fetchall()


def query_t_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
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
        order by trade_date, stock_code
        """
    ).fetchall()


def query_cash_diff_by_stock(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        select
          stock_code,
          stock_name,
          count(*) as trade_rows,
          round(sum(case when side = 'BUY' then amount else 0 end), 2) as buy_amount,
          round(sum(case when side = 'SELL' then amount else 0 end), 2) as sell_amount,
          round(sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as fees,
          round(sum(case when side = 'SELL' then amount else 0 end) - sum(case when side = 'BUY' then amount else 0 end) - sum(coalesce(commission,0) + coalesce(stamp_tax,0) + coalesce(transfer_fee,0) + coalesce(other_fee,0)), 2) as cash_difference_not_realized_pnl
        from trades
        group by stock_code, stock_name
        order by cash_difference_not_realized_pnl asc
        """
    ).fetchall()


def analytics_rows(conn: sqlite3.Connection, key: str, limit: int | None = None) -> list[dict[str, object]]:
    data = fifo_analytics(conn).get(key, [])
    if limit is not None:
        return data[:limit]
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="查询本地历史交易底账。")
    parser.add_argument(
        "query",
        choices=[
            "summary",
            "fees",
            "fee-drag",
            "frequency",
            "activity",
            "stock",
            "monthly",
            "recent",
            "t-candidates",
            "cash-diff",
            "realized",
            "positions",
            "pnl-by-stock",
        ],
    )
    parser.add_argument("--sqlite", type=Path, default=Path("state/account_ledger.sqlite"))
    parser.add_argument("--stock-code", default=None)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()

    with connect(args.sqlite) as conn:
        if args.query == "summary":
            rows = query_summary(conn)
        elif args.query == "fees":
            rows = query_fees(conn)
        elif args.query == "fee-drag":
            rows = query_fee_drag(conn)
        elif args.query == "frequency":
            rows = query_frequency(conn)
        elif args.query == "activity":
            rows = query_activity(conn)
        elif args.query == "stock":
            rows = query_by_stock(conn, args.stock_code)
        elif args.query == "recent":
            rows = query_recent(conn, args.limit)
        elif args.query == "t-candidates":
            rows = query_t_candidates(conn)
        elif args.query == "cash-diff":
            rows = query_cash_diff_by_stock(conn)
        elif args.query == "realized":
            print_rows(analytics_rows(conn, "realized_lots", args.limit))
            return 0
        elif args.query == "positions":
            print_rows(analytics_rows(conn, "open_positions"))
            return 0
        elif args.query == "pnl-by-stock":
            print_rows(analytics_rows(conn, "realized_by_stock"))
            return 0
        else:
            rows = query_monthly(conn)
    print_rows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
