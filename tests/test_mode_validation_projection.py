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

from mode_validation_projection import build_mode_validation_projection  # noqa: E402
from mode_validation_state import ModeValidationStore  # noqa: E402


def mode() -> dict[str, object]:
    return {
        "id": "mode-a",
        "name": "收盘确认模式",
        "status": "validating",
        "version": "1.0",
        "applicable_environment": ["指数位于 50 日线上方"],
        "trigger_conditions": ["收盘站上 5 日线"],
        "execution_boundaries": ["计划风险内执行"],
        "invalidation_conditions": ["收盘跌破 5 日线"],
        "max_risk": "0.5%",
        "next_validation_requirement": "三个独立样本",
        "samples": [],
    }


def trading_state() -> dict[str, object]:
    return {"version": 1, "modes": [mode()], "error": None}


class ProjectionTests(unittest.TestCase):
    def test_missing_database_returns_an_empty_read_only_projection_with_available_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "missing.sqlite"
            projection = build_mode_validation_projection(database, trading_state())

        self.assertEqual(projection["surface"], "read_only")
        self.assertEqual(projection["tasks"], [])
        self.assertEqual(projection["modes"][0]["id"], "mode-a")
        self.assertEqual(projection["modes"][0]["active_task_id"], None)
        self.assertEqual([group["kind"] for group in projection["risk_queue"]], [
            "invalidated_dependency",
            "audit_failure",
            "needs_rereview",
            "awaiting_first_review",
            "collecting_evidence",
        ])
        self.assertFalse(database.exists())

    def test_failed_audit_body_and_absolute_source_path_are_not_published(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "mode_validation.sqlite"
            store = ModeValidationStore(database)
            task_id = store.create_task(mode(), {"goal": "验证模式"})
            proposition_id = store.create_proposition(
                task_id,
                "触发有效",
                "触发后执行应改善。",
                [{"metric": "sample_count", "operator": ">=", "value": 3}],
                [{"metric": "sample_count", "operator": "<", "value": 1}],
                True,
            )
            store.confirm_proposition(proposition_id)
            run_id = store.create_run(
                task_id,
                proposition_id,
                "historical-cycle-replay",
                "formal",
                {"date_from": "2026-01-01", "date_to": "2026-08-01"},
                {"validator_version": "1"},
                "ledger-hash",
                [],
            )
            store.queue_run(run_id)
            store.mark_run_running(run_id)
            store.finish_run(run_id, {"sample_count": 3}, [])
            store.record_evidence(
                run_id,
                proposition_id,
                "support",
                "这段失败证据正文不能上线。",
                {"sample_count": 3},
                ["/Users/private/raw-result.json"],
                True,
                {"sources_exist": False, "artifact_hash_matches": True},
            )

            projection = build_mode_validation_projection(database, trading_state())

        serialized = json.dumps(projection, ensure_ascii=False)
        self.assertEqual(projection["evidence"], [])
        self.assertNotIn("这段失败证据正文不能上线", serialized)
        self.assertNotIn("/Users/", serialized)
        audit_group = next(group for group in projection["risk_queue"] if group["kind"] == "audit_failure")
        self.assertEqual(audit_group["count"], 1)

    def test_warning_evidence_is_visible_but_does_not_satisfy_a_required_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "mode_validation.sqlite"
            store = ModeValidationStore(database)
            task_id = store.create_task(mode(), {"goal": "验证模式"})
            proposition_id = store.create_proposition(
                task_id,
                "触发有效",
                "触发后执行应改善。",
                [{"metric": "sample_count", "operator": ">=", "value": 3}],
                [{"metric": "sample_count", "operator": "<", "value": 1}],
                True,
            )
            store.confirm_proposition(proposition_id)
            run_id = store.create_run(
                task_id,
                proposition_id,
                "historical-cycle-replay",
                "formal",
                {"date_from": "2026-01-01", "date_to": "2026-08-01"},
                {"validator_version": "1"},
                "ledger-hash",
                [],
            )
            store.queue_run(run_id)
            store.mark_run_running(run_id)
            store.finish_run(run_id, {"sample_count": 3}, [])
            evidence_id = store.record_evidence(
                run_id,
                proposition_id,
                "support",
                "样本支持，但缺少独立证据段。",
                {"sample_count": 3},
                ["reports/mode_validation/mode-a/1.0/run-a/result.json"],
                False,
                {"sources_exist": True, "artifact_hash_matches": True},
            )

            projection = build_mode_validation_projection(database, trading_state())

        evidence = next(item for item in projection["evidence"] if item["evidence_id"] == evidence_id)
        self.assertEqual(evidence["audit_outcome"], "pass_with_warning")
        self.assertFalse(evidence["satisfies_required_criterion"])
        self.assertEqual(evidence["source_refs"], ["reports/mode_validation/mode-a/1.0/run-a/result.json"])


if __name__ == "__main__":
    unittest.main()
