from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mode_validation_service import create_server  # noqa: E402
from ledger_import import write_sqlite  # noqa: E402


def trading_modes() -> dict[str, object]:
    return {
        "version": 1,
        "coach_gate": {"status": "pending", "target_date": None, "reasons": [], "next_check": "", "source_path": ""},
        "mode_eligibility": [],
        "modes": [
            {
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
        ],
    }


class ModeValidationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.site = self.root / "site"
        self.reports = self.root / "reports" / "mode_validation"
        self.state.mkdir(parents=True)
        self.site.mkdir(parents=True)
        (self.site / "index.html").write_text("<!doctype html><title>test</title>", encoding="utf-8")
        (self.state / "trading_modes.json").write_text(
            json.dumps(trading_modes(), ensure_ascii=False),
            encoding="utf-8",
        )
        (self.state / "decision_events.md").write_text("# 交易决策事件\n", encoding="utf-8")
        self.server = create_server(
            host="127.0.0.1",
            port=0,
            site_dir=self.site,
            state_dir=self.state,
            reports_dir=self.reports,
            session_ttl=0.12,
            start_worker=False,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.port = self.server.server_address[1]
        self.base_url = "http://127.0.0.1:%d" % self.port
        self.origin = self.base_url

    def stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self,
        method: str,
        path: str,
        payload: object | None = None,
        origin: str | None = None,
        token: str | None = None,
        raw_body: bytes | None = None,
    ) -> tuple[int, dict[str, object]]:
        body = raw_body if raw_body is not None else json.dumps(payload if payload is not None else {}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if origin is not None:
            headers["Origin"] = origin
        if token is not None:
            headers["X-Workbench-Token"] = token
        request = urllib.request.Request(self.base_url + path, data=body if method != "GET" else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def open_session(self) -> str:
        status, payload = self.request("POST", "/api/mode-validation/session", origin=self.origin)
        self.assertEqual(status, 201)
        return str(payload["token"])

    def test_non_loopback_origin_cannot_open_a_session(self) -> None:
        status, payload = self.request(
            "POST",
            "/api/mode-validation/session",
            origin="https://malicious.example",
        )

        self.assertEqual(status, 403)
        self.assertEqual(payload["error"], "origin_forbidden")

    def test_write_requires_a_live_token_and_exact_origin(self) -> None:
        token = self.open_session()
        command = {"mode_id": "mode-a", "mode_version": "1.0"}

        missing_status, _ = self.request(
            "POST", "/api/mode-validation/tasks", command, origin=self.origin
        )
        wrong_origin_status, _ = self.request(
            "POST", "/api/mode-validation/tasks", command, origin="http://localhost:%d" % self.port, token=token
        )
        created_status, created = self.request(
            "POST", "/api/mode-validation/tasks", command, origin=self.origin, token=token
        )
        snapshot_status, snapshot = self.request("GET", "/api/mode-validation/snapshot")

        self.assertEqual(missing_status, 403)
        self.assertEqual(wrong_origin_status, 403)
        self.assertEqual(created_status, 201)
        self.assertTrue(str(created["task_id"]).startswith("task_"))
        self.assertEqual(snapshot_status, 200)
        self.assertEqual(len(snapshot["tasks"]), 1)
        self.assertEqual(len(snapshot["propositions"]), 4)

    def test_close_and_expiry_revoke_write_capability(self) -> None:
        token = self.open_session()
        close_status, _ = self.request(
            "POST", "/api/mode-validation/session/close", origin=self.origin, token=token
        )
        closed_status, _ = self.request(
            "POST",
            "/api/mode-validation/tasks",
            {"mode_id": "mode-a", "mode_version": "1.0"},
            origin=self.origin,
            token=token,
        )
        replacement = self.open_session()
        time.sleep(0.16)
        expired_status, expired = self.request(
            "POST", "/api/mode-validation/session/heartbeat", origin=self.origin, token=replacement
        )

        self.assertEqual(close_status, 200)
        self.assertEqual(closed_status, 403)
        self.assertEqual(expired_status, 403)
        self.assertEqual(expired["error"], "session_expired")

    def test_request_body_over_256_kib_is_rejected_without_parsing(self) -> None:
        token = self.open_session()
        status, payload = self.request(
            "POST",
            "/api/mode-validation/tasks",
            origin=self.origin,
            token=token,
            raw_body=b"{" + (b"a" * (256 * 1024)) + b"}",
        )

        self.assertEqual(status, 413)
        self.assertEqual(payload["error"], "request_too_large")

    def test_run_preview_rejects_extra_parameters_and_never_accepts_a_command(self) -> None:
        token = self.open_session()
        _, task = self.request(
            "POST",
            "/api/mode-validation/tasks",
            {"mode_id": "mode-a", "mode_version": "1.0"},
            origin=self.origin,
            token=token,
        )
        snapshot_status, snapshot = self.request("GET", "/api/mode-validation/snapshot")
        self.assertEqual(snapshot_status, 200)
        proposition_id = snapshot["propositions"][0]["proposition_id"]
        confirm_status, _ = self.request(
            "POST",
            "/api/mode-validation/propositions/%s/confirm" % proposition_id,
            {},
            origin=self.origin,
            token=token,
        )
        preview_status, preview = self.request(
            "POST",
            "/api/mode-validation/runs/preview",
            {
                "task_id": task["task_id"],
                "proposition_id": proposition_id,
                "validator_id": "historical-cycle-replay",
                "run_kind": "formal",
                "parameters": {
                    "date_from": "2026-01-01",
                    "date_to": "2026-08-01",
                    "inclusion_rules": ["完整周期"],
                    "exclusion_rules": [],
                    "control_definition": "同期完整周期",
                    "command": "python arbitrary.py",
                },
            },
            origin=self.origin,
            token=token,
        )

        self.assertEqual(confirm_status, 200)
        self.assertEqual(preview_status, 400)
        self.assertEqual(preview["error"], "invalid_request")
        self.assertNotIn("arbitrary.py", json.dumps(preview))

    def test_confirmed_historical_run_executes_once_and_publishes_audited_evidence(self) -> None:
        self.server.application.session_ttl = 5
        write_sqlite(
            [
                {
                    "trade_date": "2026-01-05", "trade_time": "09:35:00", "stock_code": "000001",
                    "stock_name": "样本一", "side": "BUY", "quantity": "100", "price": "10",
                    "amount": "1000", "net_amount": "-1000", "commission": "0", "stamp_tax": "0",
                    "transfer_fee": "0", "other_fee": "0",
                },
                {
                    "trade_date": "2026-01-10", "trade_time": "14:50:00", "stock_code": "000001",
                    "stock_name": "样本一", "side": "SELL", "quantity": "100", "price": "12",
                    "amount": "1200", "net_amount": "1200", "commission": "0", "stamp_tax": "0",
                    "transfer_fee": "0", "other_fee": "0",
                },
            ],
            self.state / "account_ledger.sqlite",
        )
        token = self.open_session()
        _, task = self.request(
            "POST", "/api/mode-validation/tasks",
            {"mode_id": "mode-a", "mode_version": "1.0"}, origin=self.origin, token=token,
        )
        _, snapshot = self.request("GET", "/api/mode-validation/snapshot")
        proposition_id = snapshot["propositions"][0]["proposition_id"]
        self.request(
            "POST", "/api/mode-validation/propositions/%s/confirm" % proposition_id,
            {}, origin=self.origin, token=token,
        )
        preview_status, preview = self.request(
            "POST", "/api/mode-validation/runs/preview",
            {
                "task_id": task["task_id"], "proposition_id": proposition_id,
                "validator_id": "historical-cycle-replay", "run_kind": "formal",
                "parameters": {
                    "date_from": "2026-01-01", "date_to": "2026-08-01",
                    "inclusion_rules": ["完整周期"], "exclusion_rules": [],
                    "control_definition": "同期完整周期",
                },
            },
            origin=self.origin, token=token,
        )
        create_status, created = self.request(
            "POST", "/api/mode-validation/runs", {"preview_id": preview["preview_id"]},
            origin=self.origin, token=token,
        )
        _, snapshot = self.request("GET", "/api/mode-validation/snapshot")
        candidate_id = snapshot["candidates"][0]["candidate_id"]
        qualify_status, _ = self.request(
            "POST", "/api/mode-validation/runs/%s/candidates/%s/qualify" % (created["run_id"], candidate_id),
            {"qualification": "included", "reason": "符合预注册完整周期条件"},
            origin=self.origin, token=token,
        )
        execute_status, queued = self.request(
            "POST", "/api/mode-validation/runs/%s/execute" % created["run_id"],
            {}, origin=self.origin, token=token,
        )

        processed = self.server.application.process_next_run()
        _, final_snapshot = self.request("GET", "/api/mode-validation/snapshot")
        final_run = next(item for item in final_snapshot["runs"] if item["run_id"] == created["run_id"])

        self.assertEqual(preview_status, 200)
        self.assertEqual(create_status, 201)
        self.assertEqual(qualify_status, 200)
        self.assertEqual(execute_status, 200)
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(processed, created["run_id"])
        self.assertEqual(final_run["status"], "succeeded")
        self.assertEqual(len(final_snapshot["evidence"]), 1)
        self.assertEqual(final_snapshot["evidence"][0]["audit_outcome"], "pass")
        self.assertTrue((self.reports / "mode-a" / "1.0" / created["run_id"] / "run_card.json").exists())

    def test_mode_status_change_requires_recorded_mode_review_and_second_confirmation(self) -> None:
        self.server.application.session_ttl = 5
        token = self.open_session()
        _, task = self.request(
            "POST", "/api/mode-validation/tasks",
            {"mode_id": "mode-a", "mode_version": "1.0"}, origin=self.origin, token=token,
        )
        _, snapshot = self.request("GET", "/api/mode-validation/snapshot")
        for proposition in snapshot["propositions"]:
            proposition_id = proposition["proposition_id"]
            self.request(
                "POST", "/api/mode-validation/propositions/%s/confirm" % proposition_id,
                {}, origin=self.origin, token=token,
            )
            review_status, _ = self.request(
                "POST", "/api/mode-validation/reviews",
                {
                    "task_id": task["task_id"], "scope": "proposition", "verdict": "supported",
                    "note": "当前证据支持这条命题。", "proposition_id": proposition_id, "evidence_ids": [],
                },
                origin=self.origin, token=token,
            )
            self.assertEqual(review_status, 201)
        mode_review_status, mode_review = self.request(
            "POST", "/api/mode-validation/reviews",
            {
                "task_id": task["task_id"], "scope": "mode", "verdict": "replicable",
                "note": "全部必需命题已经人工评审。", "proposition_id": None, "evidence_ids": [],
            },
            origin=self.origin, token=token,
        )
        preview_status, preview = self.request(
            "POST", "/api/mode-validation/mode-change/preview",
            {"task_id": task["task_id"], "review_event_id": mode_review["review_event_id"], "target_status": "replicable"},
            origin=self.origin, token=token,
        )
        before = json.loads((self.state / "trading_modes.json").read_text(encoding="utf-8"))
        confirm_status, confirmed = self.request(
            "POST", "/api/mode-validation/mode-change/confirm",
            {"preview_id": preview["preview_id"], "pre_write_hash": preview["pre_write_hash"]},
            origin=self.origin, token=token,
        )
        after = json.loads((self.state / "trading_modes.json").read_text(encoding="utf-8"))
        with sqlite3.connect(self.state / "mode_validation.sqlite") as connection:
            mode_change = connection.execute(
                "select review_event_id, pre_write_hash, target_status from mode_change_writes"
            ).fetchone()

        self.assertEqual(mode_review_status, 201)
        self.assertEqual(preview_status, 200)
        self.assertEqual(before["modes"][0]["status"], "validating")
        self.assertEqual(preview["before"]["status"], "validating")
        self.assertEqual(preview["after"]["status"], "replicable")
        self.assertEqual(confirm_status, 200)
        self.assertEqual(confirmed["status"], "replicable")
        self.assertEqual(after["modes"][0]["status"], "replicable")
        self.assertEqual(mode_change, (mode_review["review_event_id"], preview["pre_write_hash"], "replicable"))

    def test_formal_run_fails_if_the_same_mode_version_drifts_while_queued(self) -> None:
        write_sqlite(
            [
                {
                    "trade_date": "2026-01-05", "trade_time": "09:35:00", "stock_code": "000001",
                    "stock_name": "样本一", "side": "BUY", "quantity": "100", "price": "10",
                    "amount": "1000", "net_amount": "-1000", "commission": "0", "stamp_tax": "0",
                    "transfer_fee": "0", "other_fee": "0",
                },
                {
                    "trade_date": "2026-01-10", "trade_time": "14:50:00", "stock_code": "000001",
                    "stock_name": "样本一", "side": "SELL", "quantity": "100", "price": "12",
                    "amount": "1200", "net_amount": "1200", "commission": "0", "stamp_tax": "0",
                    "transfer_fee": "0", "other_fee": "0",
                },
            ],
            self.state / "account_ledger.sqlite",
        )
        application = self.server.application
        task = application.create_task({"mode_id": "mode-a", "mode_version": "1.0"})
        proposition_id = task["proposition_ids"][0]
        application.confirm_proposition(proposition_id, {})
        preview = application.run_preview(
            {
                "task_id": task["task_id"], "proposition_id": proposition_id,
                "validator_id": "historical-cycle-replay", "run_kind": "formal",
                "parameters": {
                    "date_from": "2026-01-01", "date_to": "2026-08-01",
                    "inclusion_rules": ["完整周期"], "exclusion_rules": [],
                    "control_definition": "同期完整周期",
                },
            }
        )
        run = application.create_run({"preview_id": preview["preview_id"]})
        candidate = application.store.list_candidates(run["run_id"])[0]
        application.qualify_candidate(
            run["run_id"], candidate["candidate_id"],
            {"qualification": "included", "reason": "符合预注册条件"},
        )
        application.queue_run(run["run_id"], {})
        changed = trading_modes()
        changed["modes"][0]["trigger_conditions"] = ["同版本定义被改变"]
        (self.state / "trading_modes.json").write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

        application.process_next_run()
        current = application.store.get_run(run["run_id"])

        self.assertEqual(current["status"], "failed")
        self.assertEqual(current["failure_reason"], "mode_definition_drift")
        self.assertEqual(application.snapshot()["evidence"], [])


if __name__ == "__main__":
    unittest.main()
