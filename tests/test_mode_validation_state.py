from __future__ import annotations

import json
import math
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mode_validation_state import (  # noqa: E402
    ModeValidationError,
    ModeValidationStore,
    audit_evidence,
    content_hash,
    draft_propositions,
)


def sample_mode(version: str = "1.0") -> dict[str, object]:
    return {
        "id": "mode-a",
        "name": "收盘确认模式",
        "status": "validating",
        "version": version,
        "applicable_environment": ["指数位于 50 日线上方"],
        "trigger_conditions": ["收盘重新站上 5 日线"],
        "execution_boundaries": ["只在计划风险内执行"],
        "invalidation_conditions": ["收盘再次跌破 5 日线"],
        "max_risk": "账户权益 0.5%",
        "next_validation_requirement": "积累三个独立样本",
        "samples": [],
    }


class ModeValidationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "mode_validation.sqlite"
        self.store = ModeValidationStore(self.database)

    def create_confirmed_proposition(self, task_id: str) -> str:
        proposition_id = self.store.create_proposition(
            task_id,
            title="触发后风险收益改善",
            statement="模式触发后，计划内执行优于对照。",
            acceptance_criteria=[{"metric": "planned_execution_rate", "operator": ">=", "value": 0.6}],
            falsifiers=[{"metric": "planned_execution_rate", "operator": "<", "value": 0.4}],
            required=True,
        )
        self.store.confirm_proposition(proposition_id)
        return proposition_id

    def test_new_task_supersedes_the_existing_active_task_without_deleting_it(self) -> None:
        first = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        second = self.store.create_task(sample_mode(), {"goal": "重新验证模式"})

        tasks = self.store.list_tasks("mode-a", "1.0")

        self.assertEqual([row["task_id"] for row in tasks], [second, first])
        self.assertEqual(tasks[0]["status"], "active")
        self.assertEqual(tasks[1]["status"], "superseded")
        self.assertEqual(tasks[1]["superseded_by_task_id"], second)
        self.assertEqual(json.loads(tasks[1]["mode_snapshot_json"])["name"], "收盘确认模式")

    def test_confirming_a_proposition_requires_acceptance_criteria_and_falsifier(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.store.create_proposition(
            task_id,
            title="缺少证伪条件",
            statement="这条命题还不能验证。",
            acceptance_criteria=[{"metric": "sample_count", "operator": ">=", "value": 3}],
            falsifiers=[],
            required=True,
        )

        with self.assertRaisesRegex(ModeValidationError, "falsifier"):
            self.store.confirm_proposition(proposition_id)

        proposition = self.store.get_proposition(proposition_id)
        self.assertEqual(proposition["workflow_status"], "draft")
        self.assertIsNone(proposition["confirmed_at"])

    def test_run_contract_columns_are_immutable_even_through_direct_sql(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_id = self.store.create_run(
            task_id,
            proposition_id,
            validator_id="historical-cycle-replay",
            run_kind="formal",
            protocol={"date_from": "2025-01-01", "date_to": "2025-12-31"},
            config={"validator_version": "1"},
            data_fingerprint="ledger-hash",
            candidates=[],
        )

        connection = sqlite3.connect(self.database)
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute(
                "update validation_runs set protocol_json = ? where run_id = ?",
                ('{"date_from":"2024-01-01"}', run_id),
            )

    def test_qualified_run_waits_for_explicit_execution_request_before_queueing(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_id = self.store.create_run(
            task_id,
            proposition_id,
            validator_id="historical-cycle-replay",
            run_kind="formal",
            protocol={"date_from": "2025-01-01", "date_to": "2025-12-31"},
            config={"validator_version": "1"},
            data_fingerprint="ledger-hash",
            candidates=[
                {
                    "source_ref": "ledger-cycle:cycle-a",
                    "observed_at": "2025-02-01T09:30:00+08:00",
                    "masked_context": {"cycle_id": "cycle-a"},
                    "qualification_deadline": None,
                }
            ],
        )
        candidate_id = self.store.list_candidates(run_id)[0]["candidate_id"]

        self.store.qualify_candidate(candidate_id, "included")
        self.assertEqual(self.store.get_run(run_id)["status"], "awaiting_qualification")

        self.store.queue_run(run_id)
        self.assertEqual(self.store.get_run(run_id)["status"], "queued")

    def test_queue_claim_is_serial_and_interrupted_runs_fail_without_retry(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_ids = []
        for suffix in ("a", "b"):
            run_id = self.store.create_run(
                task_id,
                proposition_id,
                validator_id="historical-cycle-replay",
                run_kind="formal",
                protocol={"date_from": "2025-01-01", "date_to": "2025-12-31", "suffix": suffix},
                config={"validator_version": "1"},
                data_fingerprint="ledger-hash-%s" % suffix,
                candidates=[],
            )
            self.store.queue_run(run_id)
            run_ids.append(run_id)

        claimed = self.store.claim_next_queued_run()
        second_claim = self.store.claim_next_queued_run()

        self.assertEqual(claimed["run_id"], run_ids[0])
        self.assertIsNone(second_claim)
        self.assertEqual(self.store.get_run(run_ids[1])["status"], "queued")

        recovered = self.store.fail_interrupted_runs()
        self.assertEqual(recovered, [run_ids[0]])
        self.assertEqual(self.store.get_run(run_ids[0])["status"], "failed")
        self.assertEqual(self.store.get_run(run_ids[0])["failure_reason"], "service_interrupted")
        self.assertEqual(self.store.get_run(run_ids[1])["status"], "queued")

    def test_cancel_queued_run_and_request_safe_stop_for_running_run(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        queued = self.store.create_run(
            task_id,
            proposition_id,
            "historical-cycle-replay",
            "formal",
            {"date_from": "2025-01-01", "date_to": "2025-12-31"},
            {"validator_version": "1"},
            "ledger-a",
            [],
        )
        self.store.queue_run(queued)
        self.store.cancel_run(queued)
        self.assertEqual(self.store.get_run(queued)["status"], "cancelled")

        running = self.store.create_run(
            task_id,
            proposition_id,
            "historical-cycle-replay",
            "formal",
            {"date_from": "2024-01-01", "date_to": "2024-12-31"},
            {"validator_version": "1"},
            "ledger-b",
            [],
        )
        self.store.queue_run(running)
        self.store.mark_run_running(running)
        self.store.cancel_run(running)
        current = self.store.get_run(running)
        self.assertEqual(current["status"], "running")
        self.assertEqual(current["stop_requested"], 1)

    def test_candidate_outcomes_are_revealed_only_after_qualification_and_never_rewritten(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_id = self.store.create_run(
            task_id,
            proposition_id,
            "historical-cycle-replay",
            "formal",
            {"date_from": "2025-01-01", "date_to": "2025-12-31"},
            {"validator_version": "1"},
            "ledger-a",
            [
                {
                    "source_ref": "ledger-cycle:cycle-a",
                    "observed_at": "2025-02-01T09:30:00+08:00",
                    "masked_context": {"cycle_id": "cycle-a"},
                    "qualification_deadline": None,
                }
            ],
        )
        candidate_id = self.store.list_candidates(run_id)[0]["candidate_id"]

        with self.assertRaisesRegex(ModeValidationError, "qualification_pending"):
            self.store.reveal_candidate_outcomes(run_id, {"ledger-cycle:cycle-a": {"realized_pnl": 50.0}})

        self.store.qualify_candidate(candidate_id, "included")
        self.store.queue_run(run_id)
        self.store.mark_run_running(run_id)
        self.store.reveal_candidate_outcomes(run_id, {"ledger-cycle:cycle-a": {"realized_pnl": 50.0}})

        candidate = self.store.list_candidates(run_id)[0]
        self.assertEqual(json.loads(candidate["outcome_json"])["realized_pnl"], 50.0)
        with self.assertRaisesRegex(ModeValidationError, "outcome_already_revealed"):
            self.store.reveal_candidate_outcomes(run_id, {"ledger-cycle:cycle-a": {"realized_pnl": -50.0}})

    def test_overdue_forward_candidates_become_qualification_missing_without_silent_exclusion(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_id = self.store.create_run(
            task_id,
            proposition_id,
            "forward-decision-observation",
            "formal",
            {"window_start": "2026-08-12", "window_end": "2026-08-20"},
            {"validator_version": "1"},
            "events-a",
            [
                {
                    "source_ref": "state/decision_events.md#L10",
                    "observed_at": "2026-08-12T15:00:00+08:00",
                    "masked_context": {"title": "事件一"},
                    "qualification_deadline": "2026-08-13T09:30:00+08:00",
                },
                {
                    "source_ref": "state/decision_events.md#L20",
                    "observed_at": "2026-08-13T15:00:00+08:00",
                    "masked_context": {"title": "事件二"},
                    "qualification_deadline": "2026-08-14T09:30:00+08:00",
                },
            ],
        )

        expired = self.store.expire_candidate_qualifications("2026-08-13T10:00:00+08:00")
        candidates = self.store.list_candidates(run_id)

        self.assertEqual(len(expired), 1)
        self.assertEqual(candidates[0]["qualification"], "qualification_missing")
        self.assertEqual(candidates[0]["qualification_reason"], "deadline_missed")
        self.assertEqual(candidates[1]["qualification"], "pending")

        self.store.qualify_candidate(candidates[0]["candidate_id"], "included", "按当时记录本应纳入")
        late = self.store.list_candidates(run_id)[0]
        self.assertEqual(late["qualification"], "qualification_missing")
        self.assertEqual(late["qualification_reason"], "deadline_missed;late_backfill=included:按当时记录本应纳入")

    def test_review_events_append_and_supersede_without_rewriting_history(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)

        first = self.store.append_review(
            task_id,
            scope="proposition",
            verdict="supported",
            note="第一轮证据支持。",
            proposition_id=proposition_id,
            evidence_ids=[],
        )
        second = self.store.append_review(
            task_id,
            scope="proposition",
            verdict="mixed",
            note="新增反向证据后改为混合。",
            proposition_id=proposition_id,
            evidence_ids=[],
        )

        history = self.store.list_reviews(task_id)
        current = self.store.current_review(task_id, "proposition", proposition_id)

        self.assertEqual([row["review_event_id"] for row in history], [second, first])
        self.assertEqual(history[0]["supersedes_event_id"], first)
        self.assertEqual(history[1]["verdict"], "supported")
        self.assertEqual(current["review_event_id"], second)
        self.assertEqual(current["verdict"], "mixed")

    def test_mode_review_requires_current_verdict_for_every_required_proposition(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        first = self.create_confirmed_proposition(task_id)
        second = self.store.create_proposition(
            task_id,
            title="失效条件有效",
            statement="失效条件应及时停止模式。",
            acceptance_criteria=[{"metric": "exit_rate", "operator": ">=", "value": 0.8}],
            falsifiers=[{"metric": "exit_rate", "operator": "<", "value": 0.5}],
            required=True,
        )
        self.store.confirm_proposition(second)
        self.store.append_review(
            task_id,
            scope="proposition",
            verdict="supported",
            note="第一条命题已评审。",
            proposition_id=first,
            evidence_ids=[],
        )

        with self.assertRaisesRegex(ModeValidationError, "required_propositions_unreviewed"):
            self.store.append_review(
                task_id,
                scope="mode",
                verdict="continue_validating",
                note="仍需继续验证。",
                proposition_id=None,
                evidence_ids=[],
            )

        self.store.append_review(
            task_id,
            scope="proposition",
            verdict="insufficient",
            note="第二条命题证据不足。",
            proposition_id=second,
            evidence_ids=[],
        )
        review_id = self.store.append_review(
            task_id,
            scope="mode",
            verdict="continue_validating",
            note="证据不足，继续验证。",
            proposition_id=None,
            evidence_ids=[],
        )

        self.assertTrue(review_id.startswith("review_"))

    def test_invalidating_reviewed_evidence_marks_projection_for_rereview(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_id = self.store.create_run(
            task_id,
            proposition_id,
            validator_id="historical-cycle-replay",
            run_kind="formal",
            protocol={"date_from": "2025-01-01", "date_to": "2025-12-31"},
            config={"validator_version": "1"},
            data_fingerprint="ledger-hash",
            candidates=[],
        )
        self.store.queue_run(run_id)
        self.store.mark_run_running(run_id)
        self.store.finish_run(run_id, result={"sample_count": 4}, warnings=[])
        evidence_id = self.store.record_evidence(
            run_id,
            proposition_id,
            direction="support",
            summary="四个独立样本支持命题。",
            metrics={"sample_count": 4},
            source_refs=["reports/mode_validation/mode-a/1.0/run/result.json"],
            independent_segment=True,
            audit_context={"sources_exist": True, "artifact_hash_matches": True},
        )
        review_id = self.store.append_review(
            task_id,
            scope="proposition",
            verdict="supported",
            note="基于当前证据支持。",
            proposition_id=proposition_id,
            evidence_ids=[evidence_id],
        )

        self.store.invalidate_run(run_id, "发现输入数据重复。")
        snapshot = self.store.snapshot_rows()
        historical_review = next(row for row in snapshot["reviews"] if row["review_event_id"] == review_id)
        proposition = next(row for row in snapshot["propositions"] if row["proposition_id"] == proposition_id)

        self.assertEqual(historical_review["verdict"], "supported")
        self.assertTrue(historical_review["needs_rereview"])
        self.assertEqual(proposition["workflow_status"], "awaiting_review")
        with self.assertRaisesRegex(ModeValidationError, "required_propositions_need_rereview"):
            self.store.append_review(
                task_id,
                scope="mode",
                verdict="replicable",
                note="不能在证据失效后直接升级模式。",
                proposition_id=None,
                evidence_ids=[],
            )

    def test_human_review_cannot_cite_evidence_that_failed_publication_audit(self) -> None:
        task_id = self.store.create_task(sample_mode(), {"goal": "验证模式"})
        proposition_id = self.create_confirmed_proposition(task_id)
        run_id = self.store.create_run(
            task_id,
            proposition_id,
            "historical-cycle-replay",
            "formal",
            {"date_from": "2025-01-01", "date_to": "2025-12-31"},
            {"validator_version": "1"},
            "ledger-a",
            [],
        )
        self.store.queue_run(run_id)
        self.store.mark_run_running(run_id)
        self.store.finish_run(run_id, {"sample_count": 1}, [])
        evidence_id = self.store.record_evidence(
            run_id,
            proposition_id,
            "support",
            "来源缺失，因此不能用于评审。",
            {"sample_count": 1},
            ["reports/missing/result.json"],
            True,
            {"sources_exist": False, "artifact_hash_matches": True},
        )

        with self.assertRaisesRegex(ModeValidationError, "evidence_not_publishable"):
            self.store.append_review(
                task_id,
                scope="proposition",
                verdict="supported",
                note="这条评审不应成功。",
                proposition_id=proposition_id,
                evidence_ids=[evidence_id],
            )


class ModeValidationDomainTests(unittest.TestCase):
    def test_content_hash_is_stable_across_mapping_key_order(self) -> None:
        self.assertEqual(content_hash({"b": 2, "a": 1}), content_hash({"a": 1, "b": 2}))

    def test_mode_definition_creates_four_editable_drafts(self) -> None:
        drafts = draft_propositions(sample_mode())

        self.assertEqual(
            [draft["category"] for draft in drafts],
            ["environment", "trigger", "boundary", "invalidation"],
        )
        self.assertTrue(all(draft["workflow_status"] == "draft" for draft in drafts))
        self.assertTrue(all(draft["acceptance_criteria"] for draft in drafts))
        self.assertTrue(all(draft["falsifiers"] for draft in drafts))

    def test_audit_fails_closed_on_non_finite_metrics(self) -> None:
        outcome, reasons = audit_evidence(
            {
                "run_status": "succeeded",
                "mode_hash_matches": True,
                "sources_exist": True,
                "proposition_exists": True,
                "falsifier_exists": True,
                "metrics": {"profit_factor": math.inf},
                "artifact_hash_matches": True,
                "run_kind": "formal",
                "presented_as_formal": True,
                "independent_segment": True,
                "limitations": [],
            }
        )

        self.assertEqual(outcome, "fail")
        self.assertIn("non_finite_metric", reasons)

    def test_audit_warns_when_formal_evidence_has_no_independent_segment(self) -> None:
        outcome, reasons = audit_evidence(
            {
                "run_status": "succeeded",
                "mode_hash_matches": True,
                "sources_exist": True,
                "proposition_exists": True,
                "falsifier_exists": True,
                "metrics": {"sample_count": 3},
                "artifact_hash_matches": True,
                "run_kind": "formal",
                "presented_as_formal": True,
                "independent_segment": False,
                "limitations": [],
            }
        )

        self.assertEqual(outcome, "pass_with_warning")
        self.assertEqual(reasons, ["independent_segment_missing"])


if __name__ == "__main__":
    unittest.main()
