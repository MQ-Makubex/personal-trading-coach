#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ledger_import import FIELDS, import_files, read_csv  # noqa: E402


class LedgerImportTests(unittest.TestCase):
    def test_read_csv_preserves_trimmed_trade_date_strings_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trades.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for trade_date in (" 2026/07/01 ", "20260701"):
                    writer.writerow({"trade_date": trade_date})

            rows, _ = read_csv(path)

        self.assertEqual([row["trade_date"] for row in rows], ["2026/07/01", "20260701"])

    def test_import_preserves_same_source_multiplicity_without_reimporting_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "trades.csv"
            ledger = root / "ledger.csv"
            sqlite = root / "ledger.sqlite"
            summary = root / "summary.md"
            row = {
                "trade_date": "2026-07-01",
                "trade_time": "09:30:00",
                "stock_code": "000001",
                "stock_name": "TEST",
                "side": "BUY",
                "quantity": "100",
                "price": "10",
                "amount": "1000",
                "net_amount": "-1001",
            }
            with source.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow(row)
                writer.writerow(row)

            first = import_files([source], ledger, sqlite, summary)
            first_rows, _ = read_csv(ledger)
            second = import_files([source], ledger, sqlite, summary)
            second_rows, _ = read_csv(ledger)

        self.assertEqual(first.imported_rows, 2)
        self.assertEqual(len(first_rows), 2)
        self.assertEqual(second.imported_rows, 0)
        self.assertEqual(second.duplicate_rows, 2)
        self.assertEqual(len(second_rows), 2)


if __name__ == "__main__":
    unittest.main()
