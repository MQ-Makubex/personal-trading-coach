#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from init_state import init_state  # noqa: E402
from personal_site_state import load_discipline_feed, load_trading_modes  # noqa: E402


def valid_gate() -> dict[str, object]:
    return {
        "status": "observe",
        "target_date": "2026-07-11",
        "reasons": [],
        "next_check": "等待模式触发",
        "source_path": "",
    }


def valid_sample(cycle_id: str, **overrides: object) -> dict[str, object]:
    sample: dict[str, object] = {
        "cycle_id": cycle_id,
        "evidence_type": "formal",
        "execution_result": "planned",
        "evidence_direction": "support",
        "note": "盘前绑定",
        "source_paths": [f"reports/{cycle_id}/coach_note.md"],
    }
    sample.update(overrides)
    return sample


def valid_mode(samples: list[dict[str, object]]) -> dict[str, object]:
    return {
        "id": "mode-a",
        "name": "模式 A",
        "status": "validating",
        "version": "0.1",
        "applicable_environment": ["环境"],
        "trigger_conditions": ["触发"],
        "execution_boundaries": ["边界"],
        "invalidation_conditions": ["失效"],
        "max_risk": "一单位",
        "next_validation_requirement": "盘前绑定",
        "samples": samples,
    }


def valid_modes_payload(modes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "version": 1,
        "coach_gate": valid_gate(),
        "mode_eligibility": [],
        "modes": modes,
    }


class TradingModeStateTest(unittest.TestCase):
    def test_missing_mode_file_returns_pending_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_trading_modes(Path(tmp) / "missing.json", {})

        self.assertIsNone(result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")
        self.assertEqual(result["modes"], [])

    def test_three_valid_formal_samples_only_make_mode_review_ready(self) -> None:
        cycles = {
            f"cycle-{index}": {
                "cycle_id": f"cycle-{index}",
                "status": "closed",
                "stock_code": "000001",
                "realized_pnl_after_fees": index * 10,
                "return_pct": index,
                "holding_days": index,
            }
            for index in range(1, 5)
        }
        samples = [valid_sample(f"cycle-{index}") for index in range(1, 4)]
        samples.append(
            valid_sample(
                "cycle-4",
                evidence_type="historical_reference",
                execution_result="insufficient",
                evidence_direction="indeterminate",
                note="旧周期",
                source_paths=[],
            )
        )
        payload = valid_modes_payload([valid_mode(samples)])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = load_trading_modes(path, cycles)

        mode = result["modes"][0]
        self.assertIsNone(result["error"])
        self.assertTrue(mode["review_ready"])
        self.assertEqual(mode["status"], "validating")
        self.assertEqual(mode["valid_formal_sample_count"], 3)
        self.assertEqual(mode["historical_reference_count"], 1)
        self.assertTrue(mode["samples"][0]["cycle_found"])
        self.assertEqual(mode["samples"][0]["cycle"], cycles["cycle-1"])

    def test_malformed_mode_json_returns_repair_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text("{not json", encoding="utf-8")
            result = load_trading_modes(path, {})

        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")
        self.assertEqual(result["modes"], [])

    def test_unsafe_or_duplicate_mode_state_returns_repair_state(self) -> None:
        payload = valid_modes_payload(
            [
                valid_mode([valid_sample("cycle-1", source_paths=["../private.md"])]),
                valid_mode([]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_trading_modes(path, {})

        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")

    def test_invalid_gate_status_returns_repair_state(self) -> None:
        payload = valid_modes_payload([])
        payload["coach_gate"]["status"] = "ready"  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_trading_modes(path, {})

        self.assertIn("状态数据待修复", result["error"])

    def test_mode_eligibility_records_are_validated_and_returned(self) -> None:
        payload = valid_modes_payload([])
        payload["mode_eligibility"] = [
            {
                "mode_id": "mode-a",
                "status": "eligible",
                "target_date": "2026-07-12",
                "reasons": ["闸门已核验"],
                "source_path": "reports/run-20260711/coach_note.md",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_trading_modes(path, {})

        self.assertIsNone(result["error"])
        self.assertEqual(result["mode_eligibility"][0]["status"], "eligible")


class DisciplineStateTest(unittest.TestCase):
    def test_only_current_active_messages_are_returned(self) -> None:
        payload = {
            "version": 1,
            "messages": [
                {
                    "id": "live",
                    "status": "active",
                    "level": "reminder",
                    "scope": "global",
                    "stock_code": "",
                    "mode_id": "",
                    "message": "先核验风险锚",
                    "source_path": "reports/a.md",
                    "effective_at": "2026-07-01T00:00:00+00:00",
                    "expires_at": "2026-08-01T00:00:00+00:00",
                    "created_at": "2026-07-01T00:00:00+00:00",
                },
                {
                    "id": "draft",
                    "status": "draft",
                    "level": "reminder",
                    "scope": "global",
                    "stock_code": "",
                    "mode_id": "",
                    "message": "草稿",
                    "source_path": "",
                    "effective_at": "",
                    "expires_at": "",
                    "created_at": "2026-07-01T00:00:00+00:00",
                },
                {
                    "id": "expired",
                    "status": "active",
                    "level": "red_card",
                    "scope": "global",
                    "stock_code": "",
                    "mode_id": "",
                    "message": "已过期",
                    "source_path": "",
                    "effective_at": "2026-06-01T00:00:00+00:00",
                    "expires_at": "2026-06-30T00:00:00+00:00",
                    "created_at": "2026-06-01T00:00:00+00:00",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discipline_feed.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = load_discipline_feed(path, datetime(2026, 7, 11, tzinfo=timezone.utc))

        self.assertIsNone(result["error"])
        self.assertEqual([row["id"] for row in result["messages"]], ["live"])

    def test_active_messages_sort_red_cards_then_newest_first(self) -> None:
        payload = {
            "version": 1,
            "messages": [
                message("reminder-new", "reminder", "2026-07-03T00:00:00+00:00"),
                message("red-old", "red_card", "2026-07-01T00:00:00+00:00"),
                message("red-new", "red_card", "2026-07-04T00:00:00+00:00"),
                message("reminder-old", "reminder", "2026-07-02T00:00:00+00:00"),
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discipline_feed.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_discipline_feed(path, datetime(2026, 7, 11, tzinfo=timezone.utc))

        self.assertEqual(
            [row["id"] for row in result["messages"]],
            ["red-new", "red-old", "reminder-new", "reminder-old"],
        )

    def test_invalid_message_enum_or_absolute_path_returns_repair_state(self) -> None:
        payload = {"version": 1, "messages": [message("bad", "notice", "2026-07-01T00:00:00+00:00")]}
        payload["messages"][0]["source_path"] = "/Users/private.md"  # type: ignore[index]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discipline_feed.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = load_discipline_feed(path, datetime(2026, 7, 11, tzinfo=timezone.utc))

        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["messages"], [])


class StateInitializationTest(unittest.TestCase):
    def test_json_templates_are_initialized_without_overwriting_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            first = init_state(ROOT / "templates" / "state", state)
            (state / "trading_modes.json").write_text('{"private": true}', encoding="utf-8")
            second = init_state(ROOT / "templates" / "state", state)

            self.assertIn(("trading_modes.json", "created"), first)
            self.assertIn(("discipline_feed.json", "created"), first)
            self.assertIn(("trading_modes.json", "kept"), second)
            self.assertEqual((state / "trading_modes.json").read_text(encoding="utf-8"), '{"private": true}')


def message(message_id: str, level: str, created_at: str) -> dict[str, str]:
    return {
        "id": message_id,
        "status": "active",
        "level": level,
        "scope": "global",
        "stock_code": "",
        "mode_id": "",
        "message": message_id,
        "source_path": "reports/a.md",
        "effective_at": "",
        "expires_at": "",
        "created_at": created_at,
    }


if __name__ == "__main__":
    unittest.main()
