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

from ledger_import import FIELDS, read_csv  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
