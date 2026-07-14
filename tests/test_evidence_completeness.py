from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evidence_completeness import validate_candidate_data, validate_market_snapshot  # noqa: E402


class EvidenceCompletenessTests(unittest.TestCase):
    def test_rejects_small_or_inconsistent_market_breadth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "market.json"
            path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "verified": True,
                        "major_indices": [
                            {"name": name, "change_pct": -1}
                            for name in ("上证指数", "深证成指", "创业板指", "科创50")
                        ],
                        "us_indices": [{"name": "标普500", "change_pct": -1}, {"name": "纳斯达克综合", "change_pct": -1}],
                        "market_breadth": {"total": 100, "up": 100, "down": 0, "flat": 0},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            errors = validate_market_snapshot(path)
        self.assertTrue(any("样本异常" in error for error in errors))

    def test_accepts_complete_candidate_ma_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.csv"
            fields = ["stock_code", "data_status", "latest_trade_date", "bar_count", "ma5", "ma10", "ma20", "ma50", "ma200"]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for index in range(15):
                    writer.writerow(
                        {
                            "stock_code": f"300{index:03d}",
                            "data_status": "ok",
                            "latest_trade_date": "2026-07-13",
                            "bar_count": 250,
                            "ma5": 1,
                            "ma10": 1,
                            "ma20": 1,
                            "ma50": 1,
                            "ma200": 1,
                        }
                    )
            errors = validate_candidate_data(path, "2026-07-13")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
