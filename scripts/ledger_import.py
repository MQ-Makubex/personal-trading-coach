#!/usr/bin/env python3
"""Merge sanitized trade-fact CSV files into the local account ledger."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path


FIELDS = [
    "trade_date",
    "trade_time",
    "stock_code",
    "stock_name",
    "side",
    "quantity",
    "price",
    "amount",
    "net_amount",
    "commission",
    "stamp_tax",
    "transfer_fee",
    "other_fee",
]

DEDUP_KEY = ["trade_date", "trade_time", "stock_code", "stock_name", "side", "quantity", "price", "amount", "net_amount"]

FORBIDDEN_HEADERS = {
    "姓名", "身份证", "手机号", "手机号码", "资金账号", "资金帐号", "客户号", "股东账号", "股东帐号",
    "银行卡", "营业部", "地址", "资金余额", "可用余额", "股份余额",
}


@dataclass
class ImportStats:
    input_rows: int = 0
    existing_rows: int = 0
    imported_rows: int = 0
    duplicate_rows: int = 0


def normalize_header(value: str) -> str:
    return "".join(str(value or "").split()).lower()


def to_float(value: object) -> float | None:
    text = str(value or "").strip().replace(",", "")
    if text in {"", "--", "-", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows = [{field: str(row.get(field, "") or "").strip() for field in FIELDS} for row in reader]
    return rows, headers


def validate_headers(path: Path, headers: list[str]) -> None:
    normalized_headers = {normalize_header(header) for header in headers}
    forbidden = [header for header in FORBIDDEN_HEADERS if normalize_header(header) in normalized_headers]
    missing = [field for field in FIELDS if field not in headers]
    if forbidden:
        raise ValueError(f"{path.name} 包含禁止字段：{', '.join(forbidden)}")
    if missing:
        raise ValueError(f"{path.name} 缺少标准字段：{', '.join(missing)}")


def row_key(row: dict[str, str]) -> tuple[str, ...]:
    return tuple(row.get(field, "") for field in DEDUP_KEY)


def load_existing(ledger_csv: Path) -> list[dict[str, str]]:
    if not ledger_csv.exists():
        return []
    rows, headers = read_csv(ledger_csv)
    validate_headers(ledger_csv, headers)
    return rows


def write_ledger_csv(rows: list[dict[str, str]], ledger_csv: Path) -> None:
    ledger_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=lambda row: (row.get("trade_date", ""), row.get("trade_time", ""), row.get("stock_code", ""), row.get("side", "")))
    with ledger_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in FIELDS} for row in rows)


def write_sqlite(rows: list[dict[str, str]], sqlite_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute("drop table if exists trades")
        conn.execute(
            """
            create table trades (
                trade_date text,
                trade_time text,
                stock_code text,
                stock_name text,
                side text,
                quantity real,
                price real,
                amount real,
                net_amount real,
                commission real,
                stamp_tax real,
                transfer_fee real,
                other_fee real
            )
            """
        )
        conn.executemany(
            """
            insert into trades values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row.get("trade_date", ""),
                    row.get("trade_time", ""),
                    row.get("stock_code", ""),
                    row.get("stock_name", ""),
                    row.get("side", ""),
                    to_float(row.get("quantity")),
                    to_float(row.get("price")),
                    to_float(row.get("amount")),
                    to_float(row.get("net_amount")),
                    to_float(row.get("commission")),
                    to_float(row.get("stamp_tax")),
                    to_float(row.get("transfer_fee")),
                    to_float(row.get("other_fee")),
                )
                for row in rows
            ],
        )
        conn.execute("create index idx_trades_date on trades(trade_date)")
        conn.execute("create index idx_trades_stock on trades(stock_code, stock_name)")


def write_summary(rows: list[dict[str, str]], stats: ImportStats, summary_path: Path) -> None:
    total_fees = 0.0
    for row in rows:
        for field in ("commission", "stamp_tax", "transfer_fee", "other_fee"):
            total_fees += to_float(row.get(field)) or 0.0
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(
        "\n".join(
            [
                "# 历史交易底账摘要",
                "",
                f"- 当前底账行数: {len(rows)}",
                f"- 本次输入行数: {stats.input_rows}",
                f"- 本次新增行数: {stats.imported_rows}",
                f"- 本次去重行数: {stats.duplicate_rows}",
                f"- 累计费用: {total_fees:.2f}",
                "",
                "本摘要只基于标准交易事实，不包含身份信息、账户号或资金余额。",
            ]
        ),
        encoding="utf-8",
    )


def import_files(input_files: list[Path], ledger_csv: Path, sqlite_path: Path, summary_path: Path) -> ImportStats:
    stats = ImportStats()
    existing_rows = load_existing(ledger_csv)
    stats.existing_rows = len(existing_rows)
    rows_by_key = {row_key(row): row for row in existing_rows}

    for input_file in input_files:
        rows, headers = read_csv(input_file)
        validate_headers(input_file, headers)
        for row in rows:
            stats.input_rows += 1
            key = row_key(row)
            if key in rows_by_key:
                stats.duplicate_rows += 1
                continue
            rows_by_key[key] = row
            stats.imported_rows += 1

    merged_rows = list(rows_by_key.values())
    write_ledger_csv(merged_rows, ledger_csv)
    write_sqlite(merged_rows, sqlite_path)
    write_summary(merged_rows, stats, summary_path)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="导入标准交易 CSV，维护本地历史交易底账 CSV + SQLite。")
    parser.add_argument("input_csv", nargs="+", type=Path)
    parser.add_argument("--ledger", type=Path, default=Path("state/account_ledger.csv"))
    parser.add_argument("--sqlite", type=Path, default=Path("state/account_ledger.sqlite"))
    parser.add_argument("--summary", type=Path, default=Path("state/account_ledger_summary.md"))
    args = parser.parse_args()

    stats = import_files(args.input_csv, args.ledger, args.sqlite, args.summary)
    print(f"导入完成：输入 {stats.input_rows} 行，新增 {stats.imported_rows} 行，去重 {stats.duplicate_rows} 行。")
    print(f"ledger: {args.ledger}")
    print(f"sqlite: {args.sqlite}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
