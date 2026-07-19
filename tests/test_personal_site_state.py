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
from personal_site_state import load_discipline_feed, load_mentor_lenses, load_trading_modes  # noqa: E402


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


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


def valid_eligibility(mode_id: str = "mode-a", **overrides: object) -> dict[str, object]:
    eligibility: dict[str, object] = {
        "mode_id": mode_id,
        "status": "eligible",
        "target_date": "2026-07-12",
        "reasons": ["闸门已核验"],
        "source_path": "reports/run-20260711/coach_note.md",
    }
    eligibility.update(overrides)
    return eligibility


def message(
    message_id: str = "message-a",
    level: str = "reminder",
    created_at: str = "2026-07-01T00:00:00+00:00",
    **overrides: str,
) -> dict[str, str]:
    row = {
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
    row.update(overrides)
    return row


def valid_mentor_payload() -> dict[str, object]:
    return {
        "version": 1,
        "mentor": {
            "id": "bingbing-xiaomei",
            "name": "冰冰小美",
            "profile_url": "https://xueqiu.com/u/7143769715",
            "summary": "风险优先的宏观产业交易视角。",
            "updated_at": "2026-07-19",
            "notice": "基于公开表达整理，非本人授权或收益背书。",
            "principles": [
                {
                    "name": "风险先于机会",
                    "summary": "先判断环境，再决定仓位。",
                    "source_url": "https://xueqiu.com/7143769715/319174752",
                }
            ],
            "modes": [
                {
                    "id": "macro-risk-gate",
                    "name": "宏观风险闸门",
                    "horizon": "portfolio",
                    "evidence": "behavior",
                    "environment": ["海外与流动性风险升高"],
                    "signals": ["汇率、利率、融资余额"],
                    "actions": ["降低总仓位"],
                    "exit_conditions": ["风险停止扩散"],
                    "anti_patterns": ["用个股利好覆盖系统风险"],
                    "source_urls": ["https://xueqiu.com/7143769715/396191476"],
                }
            ],
            "risk_prompts": [
                {
                    "id": "risk-first",
                    "text": "驱动没有修复，反弹也可能只是情绪回摆。先把仓位放到能承受判断错误的位置。",
                    "source_url": "https://xueqiu.com/7143769715/319174752",
                }
            ],
        },
    }


def load_modes_payload(
    payload: dict[str, object], cycles: dict[str, dict[str, object]] | None = None
) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trading_modes.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return load_trading_modes(path, cycles or {})


def load_discipline_payload(
    messages: list[dict[str, str]], now: datetime = NOW
) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "discipline_feed.json"
        path.write_text(json.dumps({"version": 1, "messages": messages}), encoding="utf-8")
        return load_discipline_feed(path, now)


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

    def test_validation_mode_can_bind_open_cycle_before_outcome_is_known(self) -> None:
        cycles = {
            "open-cycle": {
                "cycle_id": "open-cycle",
                "status": "open",
                "stock_code": "301396",
                "stock_name": "宏景科技",
            }
        }
        sample = valid_sample(
            "open-cycle",
            evidence_direction="indeterminate",
            note="周期进行中，结果待核验",
        )
        payload = valid_modes_payload([valid_mode([sample])])
        payload["mode_eligibility"] = [valid_eligibility()]

        result = load_modes_payload(payload, cycles)

        self.assertIsNone(result["error"])
        self.assertEqual(result["mode_eligibility"][0]["status"], "eligible")
        self.assertEqual(result["modes"][0]["samples"][0]["cycle_id"], "open-cycle")
        self.assertTrue(result["modes"][0]["samples"][0]["cycle_found"])
        self.assertEqual(result["modes"][0]["valid_formal_sample_count"], 0)

    def test_malformed_mode_json_returns_repair_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trading_modes.json"
            path.write_text("{not json", encoding="utf-8")
            result = load_trading_modes(path, {})

        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")
        self.assertEqual(result["modes"], [])

    def test_unreadable_mode_path_returns_repair_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_trading_modes(Path(tmp), {})

        self.assert_mode_repair_state(result)

    def test_mode_eligibility_records_are_validated_and_returned(self) -> None:
        payload = valid_modes_payload([])
        payload["mode_eligibility"] = [valid_eligibility()]
        result = load_modes_payload(payload)

        self.assertIsNone(result["error"])
        self.assertEqual(result["mode_eligibility"][0]["status"], "eligible")

    def test_unsafe_path_forms_return_non_leaking_repair_state(self) -> None:
        unsafe_paths = {
            "posix_absolute": "/Users/private.md",
            "windows_drive_absolute": "C:\\Users\\private.md",
            "windows_drive_relative": "C:private.md",
            "windows_unc": "\\\\server\\share\\private.md",
            "windows_rooted": "\\private.md",
            "posix_parent": "../private.md",
            "windows_parent": "..\\private.md",
        }

        for case, unsafe_path in unsafe_paths.items():
            with self.subTest(case=case):
                payload = valid_modes_payload([])
                payload["coach_gate"] = valid_gate()
                payload["coach_gate"]["source_path"] = unsafe_path  # type: ignore[index]
                result = load_modes_payload(payload)

                self.assert_mode_repair_state(result)
                self.assertNotIn(unsafe_path, result["error"])

    def test_empty_and_portable_relative_paths_are_allowed(self) -> None:
        allowed_paths = ["", "reports/run/coach_note.md", "reports\\run\\coach_note.md"]

        for source_path in allowed_paths:
            with self.subTest(source_path=source_path):
                payload = valid_modes_payload([])
                payload["coach_gate"] = valid_gate()
                payload["coach_gate"]["source_path"] = source_path  # type: ignore[index]
                result = load_modes_payload(payload)

                self.assertIsNone(result["error"])

    def test_state_paths_are_canonicalized_and_reject_obfuscated_unsafe_forms(self) -> None:
        payload = valid_modes_payload([valid_mode([valid_sample("cycle-a", source_paths=["reports\\run\\note.md"])])])
        payload["coach_gate"]["source_path"] = "reports\\run\\coach_note.md"  # type: ignore[index]
        payload["mode_eligibility"] = [valid_eligibility(source_path="reports\\run\\eligibility.md")]

        result = load_modes_payload(payload)

        self.assertIsNone(result["error"])
        self.assertEqual(result["coach_gate"]["source_path"], "reports/run/coach_note.md")
        self.assertEqual(result["mode_eligibility"][0]["source_path"], "reports/run/eligibility.md")
        self.assertEqual(result["modes"][0]["samples"][0]["source_paths"], ["reports/run/note.md"])

        unsafe_paths = (
            "javascript:alert(1)",
            "https://example.com/private.md",
            "reports/%252e%252e/private.md",
            "reports/run/coach\x00note.md",
            "reports/run/coach\x7fnote.md",
        )
        for unsafe_path in unsafe_paths:
            with self.subTest(unsafe_path=repr(unsafe_path)):
                invalid = valid_modes_payload([])
                invalid["coach_gate"]["source_path"] = unsafe_path  # type: ignore[index]
                self.assert_mode_repair_state(load_modes_payload(invalid))

    def test_percent_encoded_unicode_controls_are_rejected_in_trading_mode_paths(self) -> None:
        for encoded in ("%C2%85", "%E2%80%AE"):
            with self.subTest(encoded=encoded):
                payload = valid_modes_payload([])
                payload["coach_gate"]["source_path"] = f"reports/run/{encoded}note.md"  # type: ignore[index]

                self.assert_mode_repair_state(load_modes_payload(payload))

    def test_every_state_path_field_rejects_windows_parent_traversal(self) -> None:
        def gate_payload() -> dict[str, object]:
            payload = valid_modes_payload([])
            payload["coach_gate"]["source_path"] = "..\\private.md"  # type: ignore[index]
            return payload

        def eligibility_payload() -> dict[str, object]:
            payload = valid_modes_payload([])
            payload["mode_eligibility"] = [valid_eligibility(source_path="..\\private.md")]
            return payload

        def sample_payload() -> dict[str, object]:
            return valid_modes_payload(
                [valid_mode([valid_sample("cycle-a", source_paths=["..\\private.md"])])]
            )

        for field, payload_factory in (
            ("gate", gate_payload),
            ("eligibility", eligibility_payload),
            ("sample", sample_payload),
        ):
            with self.subTest(field=field):
                self.assert_mode_repair_state(load_modes_payload(payload_factory()))

    def test_duplicate_mode_sample_and_eligibility_ids_each_return_repair_state(self) -> None:
        duplicate_mode = valid_modes_payload([valid_mode([]), valid_mode([])])
        duplicate_sample = valid_modes_payload(
            [valid_mode([valid_sample("cycle-a"), valid_sample("cycle-a")])]
        )
        duplicate_eligibility = valid_modes_payload([])
        duplicate_eligibility["mode_eligibility"] = [
            valid_eligibility("mode-a"),
            valid_eligibility("mode-a"),
        ]

        for identifier, payload in (
            ("mode_id", duplicate_mode),
            ("sample_cycle_id", duplicate_sample),
            ("eligibility_mode_id", duplicate_eligibility),
        ):
            with self.subTest(identifier=identifier):
                self.assert_mode_repair_state(load_modes_payload(payload))

    def test_partially_valid_mode_payload_falls_back_to_whole_safe_state(self) -> None:
        valid = valid_mode([])
        invalid = valid_mode([])
        invalid["id"] = "mode-b"
        invalid["status"] = "published"

        result = load_modes_payload(valid_modes_payload([valid, invalid]))

        self.assert_mode_repair_state(result)
        self.assertEqual(result["modes"], [])

    def test_allowed_gate_statuses_for_gate_and_eligibility(self) -> None:
        for location in ("coach_gate", "mode_eligibility"):
            for status in ("pending", "locked", "observe", "eligible"):
                with self.subTest(location=location, status=status):
                    payload = valid_modes_payload([])
                    if location == "coach_gate":
                        payload["coach_gate"]["status"] = status  # type: ignore[index]
                    else:
                        payload["mode_eligibility"] = [valid_eligibility(status=status)]

                    self.assertIsNone(load_modes_payload(payload)["error"])

    def test_rejected_gate_statuses_for_gate_and_eligibility(self) -> None:
        payloads = []
        invalid_gate = valid_modes_payload([])
        invalid_gate["coach_gate"]["status"] = "ready"  # type: ignore[index]
        payloads.append(("coach_gate", invalid_gate))
        invalid_eligibility = valid_modes_payload([])
        invalid_eligibility["mode_eligibility"] = [valid_eligibility(status="ready")]
        payloads.append(("mode_eligibility", invalid_eligibility))

        for location, payload in payloads:
            with self.subTest(location=location):
                self.assert_mode_repair_state(load_modes_payload(payload))

    def test_allowed_mode_statuses(self) -> None:
        for status in ("validating", "review", "replicable", "avoid"):
            with self.subTest(status=status):
                mode = valid_mode([])
                mode["status"] = status

                result = load_modes_payload(valid_modes_payload([mode]))

                self.assertIsNone(result["error"])
                self.assertEqual(result["modes"][0]["status"], status)

    def test_rejected_mode_status_returns_repair_state(self) -> None:
        mode = valid_mode([])
        mode["status"] = "published"

        self.assert_mode_repair_state(load_modes_payload(valid_modes_payload([mode])))

    def test_allowed_sample_enum_values(self) -> None:
        enum_values = {
            "evidence_type": ("formal", "historical_reference"),
            "execution_result": ("planned", "violated", "insufficient"),
            "evidence_direction": ("support", "oppose", "indeterminate"),
        }

        for field, values in enum_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    sample = valid_sample("cycle-a", **{field: value})
                    result = load_modes_payload(valid_modes_payload([valid_mode([sample])]))

                    self.assertIsNone(result["error"])

    def test_rejected_sample_enum_values_return_repair_state(self) -> None:
        for field in ("evidence_type", "execution_result", "evidence_direction"):
            with self.subTest(field=field):
                sample = valid_sample("cycle-a", **{field: "unknown"})
                result = load_modes_payload(valid_modes_payload([valid_mode([sample])]))

                self.assert_mode_repair_state(result)

    def assert_mode_repair_state(self, result: dict[str, object]) -> None:
        self.assertIsInstance(result["error"], str)
        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["coach_gate"]["status"], "pending")
        self.assertEqual(result["mode_eligibility"], [])
        self.assertEqual(result["modes"], [])


class DisciplineStateTest(unittest.TestCase):
    def test_missing_discipline_file_returns_empty_state_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_discipline_feed(Path(tmp) / "missing.json", NOW)

        self.assertIsNone(result["error"])
        self.assertEqual(result["messages"], [])

    def test_malformed_discipline_json_returns_repair_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "discipline_feed.json"
            path.write_text("{not json", encoding="utf-8")
            result = load_discipline_feed(path, NOW)

        self.assert_discipline_repair_state(result)

    def test_unreadable_discipline_path_returns_repair_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_discipline_feed(Path(tmp), NOW)

        self.assert_discipline_repair_state(result)

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

    def test_duplicate_message_ids_return_repair_state(self) -> None:
        result = load_discipline_payload([message("same"), message("same")])

        self.assert_discipline_repair_state(result)

    def test_partially_valid_discipline_payload_falls_back_to_whole_safe_state(self) -> None:
        result = load_discipline_payload([message("valid"), message("invalid", status="published")])

        self.assert_discipline_repair_state(result)
        self.assertEqual(result["messages"], [])

    def test_message_source_path_rejects_windows_parent_traversal(self) -> None:
        result = load_discipline_payload([message(source_path="..\\private.md")])

        self.assert_discipline_repair_state(result)
        self.assertNotIn("..\\private.md", result["error"])

    def test_message_source_path_is_canonicalized_at_ingestion(self) -> None:
        result = load_discipline_payload([message(source_path="reports\\run\\guard.md")])

        self.assertIsNone(result["error"])
        self.assertEqual(result["messages"][0]["source_path"], "reports/run/guard.md")

    def test_percent_encoded_unicode_controls_are_rejected_in_discipline_paths(self) -> None:
        for encoded in ("%C2%85", "%E2%80%AE"):
            with self.subTest(encoded=encoded):
                result = load_discipline_payload([message(source_path=f"reports/run/{encoded}guard.md")])

                self.assert_discipline_repair_state(result)

    def test_allowed_message_enum_values(self) -> None:
        enum_values = {
            "status": ("draft", "active", "archived"),
            "level": ("reminder", "red_card"),
            "scope": ("global", "stock", "mode"),
        }

        for field, values in enum_values.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    result = load_discipline_payload([message(**{field: value})])

                    self.assertIsNone(result["error"])

    def test_rejected_message_enum_values_return_repair_state(self) -> None:
        for field in ("status", "level", "scope"):
            with self.subTest(field=field):
                result = load_discipline_payload([message(**{field: "unknown"})])

                self.assert_discipline_repair_state(result)

    def test_effective_at_boundary_is_inclusive(self) -> None:
        timestamp = "2026-07-11T12:00:00+00:00"

        result = load_discipline_payload([message(effective_at=timestamp)], NOW)

        self.assertEqual([row["id"] for row in result["messages"]], ["message-a"])

    def test_expires_at_boundary_is_exclusive(self) -> None:
        timestamp = "2026-07-11T12:00:00+00:00"

        result = load_discipline_payload([message(expires_at=timestamp)], NOW)

        self.assertEqual(result["messages"], [])

    def test_invalid_datetime_fields_each_return_repair_state(self) -> None:
        for field in ("created_at", "effective_at", "expires_at"):
            with self.subTest(field=field):
                result = load_discipline_payload([message(**{field: "not-a-datetime"})])

                self.assert_discipline_repair_state(result)

    def test_naive_state_datetime_is_normalized_to_utc(self) -> None:
        result = load_discipline_payload([message(effective_at="2026-07-11T12:00:00")], NOW)

        self.assertEqual([row["id"] for row in result["messages"]], ["message-a"])

    def test_naive_now_is_normalized_to_utc(self) -> None:
        naive_now = datetime(2026, 7, 11, 12, 0)

        result = load_discipline_payload(
            [message(effective_at="2026-07-11T12:00:00+00:00")],
            naive_now,
        )

        self.assertEqual([row["id"] for row in result["messages"]], ["message-a"])

    def test_offset_aware_datetimes_compare_by_instant(self) -> None:
        result = load_discipline_payload(
            [
                message(
                    effective_at="2026-07-11T20:00:00+08:00",
                    expires_at="2026-07-11T21:00:00+08:00",
                )
            ],
            NOW,
        )

        self.assertEqual([row["id"] for row in result["messages"]], ["message-a"])

    def assert_discipline_repair_state(self, result: dict[str, object]) -> None:
        self.assertIsInstance(result["error"], str)
        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["messages"], [])


class MentorLensStateTest(unittest.TestCase):
    def test_valid_mentor_lens_preserves_modes_and_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mentor_lenses.json"
            path.write_text(json.dumps(valid_mentor_payload(), ensure_ascii=False), encoding="utf-8")
            result = load_mentor_lenses(path)

        self.assertIsNone(result["error"])
        self.assertEqual(result["mentor"]["id"], "bingbing-xiaomei")
        self.assertEqual(result["mentor"]["modes"][0]["horizon"], "portfolio")
        self.assertEqual(result["mentor"]["risk_prompts"][0]["id"], "risk-first")

    def test_mentor_lens_rejects_non_xueqiu_sources(self) -> None:
        payload = valid_mentor_payload()
        payload["mentor"]["modes"][0]["source_urls"] = ["https://example.com/not-primary"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mentor_lenses.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            result = load_mentor_lenses(path)

        self.assertIn("状态数据待修复", result["error"])
        self.assertEqual(result["mentor"]["modes"], [])

    def test_missing_mentor_lens_returns_empty_state_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_mentor_lenses(Path(tmp) / "missing.json")

        self.assertIsNone(result["error"])
        self.assertEqual(result["mentor"]["modes"], [])


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

if __name__ == "__main__":
    unittest.main()
