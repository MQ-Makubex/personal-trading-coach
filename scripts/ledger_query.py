#!/usr/bin/env python3
"""Run factual account-ledger queries."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def connect(sqlite_path: Path) -> sqlite3.Connection:
    if not sqlite_path.exists():
        raise SystemExit(f"未找到底账数据库：{sqlite_path}")
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    return conn


def print_rows(rows: list[sqlite3.Row]) -> None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="查询本地历史交易底账。")
    parser.add_argument("query", choices=["summary", "fees", "frequency", "stock", "monthly"])
    parser.add_argument("--sqlite", type=Path, default=Path("state/account_ledger.sqlite"))
    parser.add_argument("--stock-code", default=None)
    args = parser.parse_args()

    with connect(args.sqlite) as conn:
        if args.query == "summary":
            rows = query_summary(conn)
        elif args.query == "fees":
            rows = query_fees(conn)
        elif args.query == "frequency":
            rows = query_frequency(conn)
        elif args.query == "stock":
            rows = query_by_stock(conn, args.stock_code)
        else:
            rows = query_monthly(conn)
    print_rows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
