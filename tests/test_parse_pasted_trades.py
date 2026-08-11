from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from parse_pasted_trades import parse_text  # noqa: E402


class ParsePastedTradesTests(unittest.TestCase):
    def test_account_level_events_without_stock_codes_are_not_silently_dropped(self) -> None:
        text = "\n".join(
            [
                "发生日期\t发生时间\t证券代码\t证券名称\t交易类别\t成交数量\t成交均价\t成交金额\t发生金额",
                "2026-06-22\t09:30:00\t000001\tTEST\t证券买入\t100\t10.000\t1000.000\t-1001.000",
                "2026-06-22\t17:37:12\t--\t--\t利息归本\t0\t0.000\t0.000\t1.250",
                "2026-06-01\t11:12:49\t--\t--\t银行转证券\t0\t0.000\t0.000\t5000.000",
            ]
        )

        rows, report = parse_text(text, "2026-06-22")

        self.assertEqual(len(rows), 1)
        self.assertEqual(report["non_trade_event_count"], 2)
        self.assertEqual(report["account_level_event_count"], 2)
        self.assertTrue(report["requires_account_reconciliation"])
        self.assertEqual(
            [(event["category"], event["event_kind"], event["net_amount"]) for event in report["non_trade_events"]],
            [
                ("利息归本", "account_interest", "1.250"),
                ("银行转证券", "account_transfer", "5000.000"),
            ],
        )

    def test_position_affecting_non_trade_event_is_reported_instead_of_silently_dropped(self) -> None:
        text = "\n".join(
            [
                "发生日期\t发生时间\t证券代码\t证券名称\t交易类别\t成交数量\t成交均价\t成交金额\t发生金额",
                "2026-07-24\t11:24:11\t000001\tTEST\t证券买入\t100\t10.000\t1000.000\t-1001.000",
                "2026-07-24\t19:44:02\t700001\t测试配债\t配售缴款\t10\t100.000\t1000.000\t-1000.000",
            ]
        )

        rows, report = parse_text(text, "2026-07-24")

        self.assertEqual(len(rows), 1)
        self.assertEqual(report["non_trade_event_count"], 1)
        self.assertEqual(report["position_affecting_event_count"], 1)
        self.assertTrue(report["requires_asset_reconciliation"])
        self.assertEqual(
            report["non_trade_events"],
            [
                {
                    "trade_date": "2026-07-24",
                    "trade_time": "19:44:02",
                    "stock_code": "700001",
                    "stock_name": "测试配债",
                    "category": "配售缴款",
                    "event_kind": "asset_acquisition",
                    "quantity": "10",
                    "price": "100.000",
                    "amount": "1000.000",
                    "net_amount": "-1000.000",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
