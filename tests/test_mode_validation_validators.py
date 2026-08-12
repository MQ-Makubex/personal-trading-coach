from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ledger_import import write_sqlite  # noqa: E402
from mode_validation_state import ModeValidationError  # noqa: E402
from mode_validation_validators import (  # noqa: E402
    preview_forward_events,
    preview_historical_cycles,
    qualification_deadline,
    validate_forward_protocol_change,
    validate_validator_request,
    validator_catalog,
    write_run_artifacts,
)


def trade(
    trade_date: str,
    trade_time: str,
    stock_code: str,
    stock_name: str,
    side: str,
    quantity: float,
    price: float,
    amount: float,
    net_amount: float,
) -> dict[str, str]:
    return {
        "trade_date": trade_date,
        "trade_time": trade_time,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "side": side,
        "quantity": str(quantity),
        "price": str(price),
        "amount": str(amount),
        "net_amount": str(net_amount),
        "commission": "0",
        "stamp_tax": "0",
        "transfer_fee": "0",
        "other_fee": "0",
    }


class ValidatorRegistryTests(unittest.TestCase):
    def test_catalog_exposes_only_two_enabled_validators(self) -> None:
        catalog = validator_catalog()

        self.assertEqual(
            [item["id"] for item in catalog],
            ["historical-cycle-replay", "forward-decision-observation"],
        )
        self.assertTrue(all(item["enabled"] for item in catalog))
        self.assertTrue(all("execute" not in item for item in catalog))

    def test_unknown_validator_and_extra_parameters_are_rejected(self) -> None:
        with self.assertRaisesRegex(ModeValidationError, "validator_id"):
            validate_validator_request("shell", {}, "formal")

        with self.assertRaisesRegex(ModeValidationError, "unexpected_parameter"):
            validate_validator_request(
                "historical-cycle-replay",
                {
                    "date_from": "2026-01-01",
                    "date_to": "2026-08-01",
                    "inclusion_rules": ["完整周期"],
                    "exclusion_rules": [],
                    "control_definition": "全部同期完整周期",
                    "command": "python arbitrary.py",
                },
                "formal",
            )

    def test_forward_protocol_deadline_cannot_be_extended_after_first_candidate(self) -> None:
        existing = {
            "event_timing": "after_close",
            "qualification_deadline": {"anchor": "next_open", "lead_minutes": 30},
        }
        proposed = {
            "event_timing": "after_close",
            "qualification_deadline": {"anchor": "next_open", "lead_minutes": 0},
        }

        with self.assertRaisesRegex(ModeValidationError, "deadline_extension"):
            validate_forward_protocol_change(existing, proposed, candidate_count=1)


class HistoricalCyclePreviewTests(unittest.TestCase):
    def test_history_preview_masks_outcomes_and_marks_existing_samples_non_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.sqlite"
            write_sqlite(
                [
                    trade("2026-01-05", "09:35:00", "000001", "样本一", "BUY", 100, 10, 1000, -1000),
                    trade("2026-01-10", "14:50:00", "000001", "样本一", "SELL", 100, 12, 1200, 1200),
                    trade("2026-02-05", "09:35:00", "000002", "样本二", "BUY", 100, 20, 2000, -2000),
                    trade("2026-02-10", "14:50:00", "000002", "样本二", "SELL", 100, 18, 1800, 1800),
                ],
                ledger,
            )
            first_pass = preview_historical_cycles(
                ledger,
                {"samples": []},
                {"date_from": "2026-01-01", "date_to": "2026-12-31"},
            )
            existing_cycle_id = first_pass[0]["masked_context"]["cycle_id"]

            candidates = preview_historical_cycles(
                ledger,
                {"samples": [{"cycle_id": existing_cycle_id}]},
                {"date_from": "2026-01-01", "date_to": "2026-12-31"},
            )

        serialized = json.dumps(candidates, ensure_ascii=False).lower()
        self.assertEqual(len(candidates), 2)
        self.assertNotIn("pnl", serialized)
        self.assertNotIn("return_pct", serialized)
        self.assertNotIn("close_date", serialized)
        self.assertNotIn("exit", serialized)
        self.assertFalse(candidates[0]["masked_context"]["independent_segment"])
        self.assertTrue(candidates[1]["masked_context"]["independent_segment"])
        self.assertTrue(all(item["source_ref"].startswith("ledger-cycle:") for item in candidates))


class ForwardObservationPreviewTests(unittest.TestCase):
    def test_forward_preview_registers_every_event_after_confirmation(self) -> None:
        markdown = """# 交易决策事件

## Update - 2026-08-10
### 事件 1：旧事件
- 动作：观察。

## Update - 2026-08-13
### 事件 1：收盘确认
- 动作：等待收盘。
### 事件 2：计划内放弃
- 动作：不交易。
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "decision_events.md"
            path.write_text(markdown, encoding="utf-8")

            candidates = preview_forward_events(
                path,
                confirmed_at="2026-08-12T08:00:00Z",
                protocol={"window_start": "2026-08-12", "window_end": "2026-08-20", "event_timing": "after_close"},
            )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            [item["masked_context"]["title"] for item in candidates],
            ["事件 1：收盘确认", "事件 2：计划内放弃"],
        )
        self.assertTrue(all(item["observed_at"].startswith("2026-08-13") for item in candidates))
        self.assertTrue(all(item["qualification_deadline"].startswith("2026-08-14T09:30:00") for item in candidates))
        self.assertTrue(all("/Users/" not in item["source_ref"] for item in candidates))

    def test_default_deadlines_follow_event_timing_and_skip_weekends(self) -> None:
        self.assertEqual(
            qualification_deadline("2026-08-14", "after_close"),
            "2026-08-17T09:30:00+08:00",
        )
        self.assertEqual(
            qualification_deadline("2026-08-14", "intraday"),
            "2026-08-14T15:00:00+08:00",
        )


class ArtifactWriterTests(unittest.TestCase):
    def test_artifact_writer_uses_create_new_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            written = write_run_artifacts(
                root,
                "mode-a",
                "1.0",
                "run-a",
                run_card={"run_id": "run-a"},
                candidate_manifest={"candidates": []},
                result={"sample_count": 0},
                audit={"outcome": "pass_with_warning"},
            )

            self.assertEqual(
                sorted(path.name for path in written["files"]),
                ["candidate_manifest.json", "publication_audit.json", "result.json", "run_card.json"],
            )
            self.assertEqual(len(written["artifact_hash"]), 64)
            with self.assertRaises(FileExistsError):
                write_run_artifacts(
                    root,
                    "mode-a",
                    "1.0",
                    "run-a",
                    run_card={"run_id": "run-a"},
                    candidate_manifest={"candidates": []},
                    result={"sample_count": 0},
                    audit={"outcome": "pass_with_warning"},
                )


if __name__ == "__main__":
    unittest.main()
