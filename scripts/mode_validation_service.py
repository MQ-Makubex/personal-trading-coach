#!/usr/bin/env python3
"""Loopback-only HTTP service for the local mode-validation workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from mode_validation_projection import build_mode_validation_projection
from mode_validation_state import (
    ModeValidationConflict,
    ModeValidationError,
    ModeValidationStore,
    audit_evidence,
    content_hash,
    draft_propositions,
    mode_definition_snapshot,
)
from mode_validation_validators import (
    historical_cycle_outcomes,
    preview_forward_events,
    preview_historical_cycles,
    validate_validator_request,
    validator_catalog,
    write_run_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
MAX_REQUEST_BYTES = 256 * 1024
MAX_REJECT_DRAIN_BYTES = MAX_REQUEST_BYTES + 64 * 1024
ID_PATTERN = r"[A-Za-z0-9_-]+"
PROPOSITION_CONFIRM = re.compile(r"^/api/mode-validation/propositions/(%s)/confirm$" % ID_PATTERN)
RUN_CANDIDATE_QUALIFY = re.compile(
    r"^/api/mode-validation/runs/(%s)/candidates/(%s)/qualify$" % (ID_PATTERN, ID_PATTERN)
)
RUN_ACTION = re.compile(r"^/api/mode-validation/runs/(%s)/(execute|cancel|invalidate)$" % ID_PATTERN)


class WorkbenchApplication:
    def __init__(
        self,
        state_dir: Path,
        reports_dir: Path,
        session_ttl: float,
        start_worker: bool,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.reports_dir = Path(reports_dir)
        self.store = ModeValidationStore(self.state_dir / "mode_validation.sqlite")
        self.trading_modes_path = self.state_dir / "trading_modes.json"
        self.ledger_path = self.state_dir / "account_ledger.sqlite"
        self.decision_events_path = self.state_dir / "decision_events.md"
        self.session_ttl = float(session_ttl)
        self.tokens: dict[str, float] = {}
        self.previews: dict[str, dict[str, Any]] = {}
        self.mode_change_previews: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()
        self.server: ThreadingHTTPServer | None = None
        self.start_worker = start_worker
        self.worker_stop = threading.Event()
        self.worker_thread: threading.Thread | None = None

    def expected_origin(self) -> str:
        if self.server is None:
            raise RuntimeError("server_not_attached")
        return "http://127.0.0.1:%d" % int(self.server.server_address[1])

    def origin_allowed(self, origin: str | None) -> bool:
        return isinstance(origin, str) and secrets.compare_digest(origin, self.expected_origin())

    def open_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.tokens.clear()
            self.tokens[token] = time.monotonic()
        return token

    def require_session(self, token: str | None) -> tuple[bool, str]:
        if not token:
            return False, "session_required"
        now = time.monotonic()
        with self.lock:
            seen = self.tokens.get(token)
            if seen is None:
                return False, "session_required"
            if now - seen > self.session_ttl:
                self.tokens.pop(token, None)
                return False, "session_expired"
            self.tokens[token] = now
        return True, ""

    def close_session(self, token: str) -> None:
        with self.lock:
            self.tokens.pop(token, None)

    def trading_state(self) -> dict[str, Any]:
        try:
            value = json.loads(self.trading_modes_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ModeValidationError("trading_modes_unavailable") from exc
        if not isinstance(value, dict) or not isinstance(value.get("modes"), list):
            raise ModeValidationError("trading_modes_invalid")
        return value

    def find_mode(self, mode_id: str, mode_version: str) -> dict[str, Any]:
        for mode in self.trading_state().get("modes", []):
            if (
                isinstance(mode, dict)
                and str(mode.get("id")) == mode_id
                and str(mode.get("version")) == mode_version
            ):
                return mode
        raise ModeValidationError("mode_not_found")

    def snapshot(self) -> dict[str, Any]:
        self.store.expire_candidate_qualifications()
        return build_mode_validation_projection(
            self.state_dir / "mode_validation.sqlite",
            self.trading_state(),
            include_local_failures=True,
        )

    def create_task(self, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"mode_id", "mode_version"})
        mode = self.find_mode(require_text(command["mode_id"], "mode_id"), require_text(command["mode_version"], "mode_version"))
        goal = {
            "goal": "验证%s v%s是否值得继续积累证据" % (mode.get("name"), mode.get("version")),
            "allowed_paths": ["historical-cycle-replay", "forward-decision-observation"],
            "independent_evidence_required": True,
            "completion": "所有必需命题完成发布审计和人工评审",
            "non_goals": ["实时交易建议", "自动创建个人模式", "自动得出模式结论"],
        }
        task_id = self.store.create_task(mode, goal)
        proposition_ids = []
        for draft in draft_propositions(mode):
            proposition_ids.append(
                self.store.create_proposition(
                    task_id,
                    draft["title"],
                    draft["statement"],
                    draft["acceptance_criteria"],
                    draft["falsifiers"],
                    bool(draft["required"]),
                )
            )
        return {"task_id": task_id, "proposition_ids": proposition_ids}

    def confirm_proposition(self, proposition_id: str, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, set())
        self.store.confirm_proposition(proposition_id)
        return {"proposition_id": proposition_id, "workflow_status": "collecting"}

    def run_preview(self, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"task_id", "proposition_id", "validator_id", "run_kind", "parameters"})
        task_id = require_text(command["task_id"], "task_id")
        proposition_id = require_text(command["proposition_id"], "proposition_id")
        task = self.store.get_task(task_id)
        proposition = self.store.get_proposition(proposition_id)
        if proposition["task_id"] != task_id or proposition["workflow_status"] == "draft":
            raise ModeValidationError("proposition_not_confirmed")
        validator_id = require_text(command["validator_id"], "validator_id")
        run_kind = require_text(command["run_kind"], "run_kind")
        parameters = validate_validator_request(validator_id, command["parameters"], run_kind)
        mode = self.find_mode(str(task["mode_id"]), str(task["mode_version"]))
        current_hash = content_hash(mode_definition_snapshot(mode))
        if run_kind == "formal" and current_hash != task["mode_snapshot_hash"]:
            raise ModeValidationConflict("mode_definition_drift")
        if validator_id == "historical-cycle-replay":
            if not self.ledger_path.is_file():
                raise ModeValidationError("account_ledger_unavailable")
            candidates = preview_historical_cycles(self.ledger_path, mode, parameters)
            data_fingerprint = file_hash(self.ledger_path)
        else:
            if not self.decision_events_path.is_file():
                raise ModeValidationError("decision_events_unavailable")
            candidates = preview_forward_events(
                self.decision_events_path,
                str(proposition.get("confirmed_at") or ""),
                parameters,
            )
            data_fingerprint = file_hash(self.decision_events_path)
        preview_id = "preview_%s" % secrets.token_hex(16)
        record = {
            "preview_id": preview_id,
            "task_id": task_id,
            "proposition_id": proposition_id,
            "validator_id": validator_id,
            "validator_version": "1",
            "run_kind": run_kind,
            "protocol": parameters,
            "protocol_hash": content_hash(parameters),
            "mode_snapshot_hash": task["mode_snapshot_hash"],
            "data_fingerprint": data_fingerprint,
            "candidates": candidates,
            "expires_at": time.monotonic() + 300,
        }
        with self.lock:
            self.previews[preview_id] = record
        return {
            key: value
            for key, value in record.items()
            if key not in {"expires_at"}
        }

    def create_run(self, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"preview_id"})
        preview_id = require_text(command["preview_id"], "preview_id")
        with self.lock:
            preview = self.previews.pop(preview_id, None)
        if preview is None or time.monotonic() > preview["expires_at"]:
            raise ModeValidationConflict("preview_expired")
        task = self.store.get_task(preview["task_id"])
        if task["mode_snapshot_hash"] != preview["mode_snapshot_hash"]:
            raise ModeValidationConflict("preview_stale")
        run_id = self.store.create_run(
            preview["task_id"],
            preview["proposition_id"],
            preview["validator_id"],
            preview["run_kind"],
            preview["protocol"],
            {"validator_version": preview["validator_version"]},
            preview["data_fingerprint"],
            preview["candidates"],
        )
        return {"run_id": run_id, "status": "awaiting_qualification", "candidate_count": len(preview["candidates"])}

    def qualify_candidate(self, run_id: str, candidate_id: str, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"qualification", "reason"})
        candidate = next(
            (row for row in self.store.list_candidates(run_id) if row["candidate_id"] == candidate_id),
            None,
        )
        if candidate is None:
            raise ModeValidationError("candidate_id")
        self.store.qualify_candidate(
            candidate_id,
            require_text(command["qualification"], "qualification"),
            str(command.get("reason") or ""),
        )
        return {"candidate_id": candidate_id, "qualification": command["qualification"]}

    def append_review(self, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"task_id", "scope", "verdict", "note", "proposition_id", "evidence_ids"})
        review_id = self.store.append_review(
            require_text(command["task_id"], "task_id"),
            require_text(command["scope"], "scope"),
            require_text(command["verdict"], "verdict"),
            require_text(command["note"], "note"),
            command.get("proposition_id"),
            command.get("evidence_ids"),
        )
        return {"review_event_id": review_id}

    def preview_mode_change(self, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"task_id", "review_event_id", "target_status"})
        task_id = require_text(command["task_id"], "task_id")
        review_event_id = require_text(command["review_event_id"], "review_event_id")
        target_status = require_text(command["target_status"], "target_status")
        if target_status not in {"validating", "replicable", "avoid"}:
            raise ModeValidationError("target_status")
        task = self.store.get_task(task_id)
        review = next(
            (row for row in self.store.list_reviews(task_id) if row["review_event_id"] == review_event_id),
            None,
        )
        expected_verdict = {
            "validating": "continue_validating",
            "replicable": "replicable",
            "avoid": "avoid",
        }[target_status]
        if not review or review["scope"] != "mode" or review["verdict"] != expected_verdict:
            raise ModeValidationError("mode_review_mismatch")
        original_bytes = self.trading_modes_path.read_bytes()
        pre_write_hash = hashlib.sha256(original_bytes).hexdigest()
        state = json.loads(original_bytes.decode("utf-8"))
        modes = state.get("modes", [])
        target_index = next(
            (
                index
                for index, mode in enumerate(modes)
                if isinstance(mode, dict)
                and str(mode.get("id")) == str(task["mode_id"])
                and str(mode.get("version")) == str(task["mode_version"])
            ),
            None,
        )
        if target_index is None:
            raise ModeValidationError("mode_not_found")
        before = dict(modes[target_index])
        after = dict(before)
        after["status"] = target_status
        state["modes"][target_index] = after
        new_bytes = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        preview_id = "mode_change_preview_%s" % secrets.token_hex(16)
        record = {
            "preview_id": preview_id,
            "task_id": task_id,
            "review_event_id": review_event_id,
            "target_status": target_status,
            "before": before,
            "after": after,
            "pre_write_hash": pre_write_hash,
            "post_write_hash": hashlib.sha256(new_bytes).hexdigest(),
            "new_bytes": new_bytes,
            "original_bytes": original_bytes,
            "expires_at": time.monotonic() + 180,
        }
        with self.lock:
            self.mode_change_previews[preview_id] = record
        return {
            key: value
            for key, value in record.items()
            if key not in {"new_bytes", "original_bytes", "expires_at"}
        }

    def confirm_mode_change(self, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"preview_id", "pre_write_hash"})
        preview_id = require_text(command["preview_id"], "preview_id")
        supplied_hash = require_text(command["pre_write_hash"], "pre_write_hash")
        with self.lock:
            preview = self.mode_change_previews.pop(preview_id, None)
        if preview is None or time.monotonic() > preview["expires_at"]:
            raise ModeValidationConflict("preview_expired")
        current_bytes = self.trading_modes_path.read_bytes()
        current_hash = hashlib.sha256(current_bytes).hexdigest()
        if supplied_hash != preview["pre_write_hash"] or current_hash != preview["pre_write_hash"]:
            raise ModeValidationConflict("pre_write_hash_mismatch")
        atomic_write(self.trading_modes_path, preview["new_bytes"])
        try:
            mode_change_id = self.store.record_mode_change(
                preview["task_id"],
                preview["review_event_id"],
                preview["pre_write_hash"],
                preview["post_write_hash"],
                preview["target_status"],
            )
        except Exception:
            atomic_write(self.trading_modes_path, preview["original_bytes"])
            raise
        return {
            "mode_change_id": mode_change_id,
            "status": preview["target_status"],
            "pre_write_hash": preview["pre_write_hash"],
            "post_write_hash": preview["post_write_hash"],
        }

    def queue_run(self, run_id: str, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, set())
        self.store.queue_run(run_id)
        return {"run_id": run_id, "status": "queued"}

    def cancel_run(self, run_id: str, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, set())
        status = self.store.cancel_run(run_id)
        return {"run_id": run_id, "status": status}

    def invalidate_run(self, run_id: str, command: dict[str, Any]) -> dict[str, Any]:
        require_fields(command, {"reason"})
        self.store.invalidate_run(run_id, require_text(command["reason"], "reason"))
        return {"run_id": run_id, "status": "invalidated"}

    def process_next_run(self) -> str | None:
        run = self.store.claim_next_queued_run()
        if run is None:
            return None
        run_id = str(run["run_id"])
        try:
            if self.store.stop_requested(run_id):
                self.store.finish_cancelled_run(run_id)
                return run_id
            task = self.store.get_task(str(run["task_id"]))
            current_mode = self.find_mode(str(task["mode_id"]), str(task["mode_version"]))
            current_mode_hash = content_hash(mode_definition_snapshot(current_mode))
            if run["run_kind"] == "formal" and current_mode_hash != task["mode_snapshot_hash"]:
                self.store.fail_run(run_id, "mode_definition_drift")
                return run_id
            candidates = self.store.list_candidates(run_id)
            if any(row["qualification"] == "pending" for row in candidates):
                raise ModeValidationError("qualification_pending")
            validator_id = str(run["validator_id"])
            limitations: list[str] = []
            if validator_id == "historical-cycle-replay":
                outcomes = historical_cycle_outcomes(self.ledger_path)
                self.store.reveal_candidate_outcomes(run_id, outcomes)
                candidates = self.store.list_candidates(run_id)
                included = [row for row in candidates if row["qualification"] == "included"]
                values = [
                    json.loads(row["outcome_json"])
                    for row in included
                    if row.get("outcome_json")
                ]
                positive = sum(float(item.get("realized_pnl_after_fees") or 0) > 0 for item in values)
                negative = sum(float(item.get("realized_pnl_after_fees") or 0) < 0 for item in values)
                result = {
                    "included_sample_count": len(included),
                    "revealed_outcome_count": len(values),
                    "positive_count": positive,
                    "negative_count": negative,
                    "qualification_missing_count": sum(
                        row["qualification"] == "qualification_missing" for row in candidates
                    ),
                }
                independent_segment = bool(included) and all(
                    bool(json.loads(row["masked_context_json"]).get("independent_segment"))
                    for row in included
                )
                if not included:
                    limitations.append("sample_empty")
                if any(row["qualification"] == "qualification_missing" for row in candidates):
                    limitations.append("qualification_missing")
                direction = "support" if positive > negative else "oppose" if negative > positive else "indeterminate"
                summary = "历史回放纳入 %d 个样本，其中正向 %d 个、反向 %d 个。" % (
                    len(included), positive, negative
                )
            elif validator_id == "forward-decision-observation":
                included = [row for row in candidates if row["qualification"] == "included"]
                result = {
                    "candidate_count": len(candidates),
                    "included_count": len(included),
                    "qualification_missing_count": sum(
                        row["qualification"] == "qualification_missing" for row in candidates
                    ),
                }
                independent_segment = bool(included) and all(
                    bool(json.loads(row["masked_context_json"]).get("independent_segment"))
                    for row in included
                )
                limitations.append("forward_outcomes_pending")
                if result["qualification_missing_count"]:
                    limitations.append("qualification_missing")
                direction = "indeterminate"
                summary = "前向观察已登记 %d 个候选，当前纳入 %d 个，等待后续结果。" % (
                    len(candidates), len(included)
                )
            else:
                raise ModeValidationError("validator_id")

            audit_outcome, audit_reasons = audit_evidence(
                {
                    "run_status": "succeeded",
                    "mode_hash_matches": True,
                    "sources_exist": True,
                    "proposition_exists": True,
                    "falsifier_exists": True,
                    "metrics": result,
                    "artifact_hash_matches": True,
                    "run_kind": run["run_kind"],
                    "presented_as_formal": run["run_kind"] == "formal",
                    "independent_segment": independent_segment,
                    "limitations": limitations,
                }
            )
            relative_directory = "reports/mode_validation/%s/%s/%s" % (
                task["mode_id"], task["mode_version"], run_id
            )
            artifact = write_run_artifacts(
                self.reports_dir,
                str(task["mode_id"]),
                str(task["mode_version"]),
                run_id,
                run_card={
                    "run_id": run_id,
                    "task_id": run["task_id"],
                    "proposition_id": run["proposition_id"],
                    "validator_id": validator_id,
                    "run_kind": run["run_kind"],
                    "mode_snapshot_hash": run["mode_snapshot_hash"],
                    "protocol": json.loads(run["protocol_json"]),
                    "protocol_hash": run["protocol_hash"],
                    "data_fingerprint": run["data_fingerprint"],
                },
                candidate_manifest={
                    "candidates": [
                        {
                            "candidate_id": row["candidate_id"],
                            "source_ref": row["source_ref"],
                            "qualification": row["qualification"],
                            "qualification_reason": row["qualification_reason"],
                        }
                        for row in candidates
                    ]
                },
                result=result,
                audit={"outcome": audit_outcome, "reasons": audit_reasons},
            )
            self.store.finish_run(
                run_id,
                result,
                audit_reasons,
                relative_directory,
                artifact["artifact_hash"],
            )
            self.store.record_evidence(
                run_id,
                str(run["proposition_id"]),
                direction,
                summary,
                result,
                ["%s/result.json" % relative_directory],
                independent_segment,
                {
                    "sources_exist": True,
                    "artifact_hash_matches": True,
                    "limitations": limitations,
                    "presented_as_formal": run["run_kind"] == "formal",
                },
            )
        except ModeValidationConflict:
            raise
        except Exception as exc:
            current = self.store.get_run(run_id)
            if current["status"] == "running":
                self.store.fail_run(run_id, "validator_failed:%s" % type(exc).__name__)
        return run_id

    def worker_loop(self) -> None:
        while not self.worker_stop.wait(0.25):
            self.process_next_run()

    def start_queue_worker(self) -> None:
        self.store.fail_interrupted_runs()
        if not self.start_worker:
            return
        self.worker_thread = threading.Thread(target=self.worker_loop, daemon=True, name="mode-validation-worker")
        self.worker_thread.start()

    def stop_queue_worker(self) -> None:
        self.worker_stop.set()
        if self.worker_thread is not None:
            self.worker_thread.join(timeout=2)


def require_fields(command: Any, fields: set[str]) -> dict[str, Any]:
    if not isinstance(command, dict):
        raise ModeValidationError("json_object_required")
    keys = set(command)
    if keys != fields:
        missing = sorted(fields - keys)
        extra = sorted(keys - fields)
        raise ModeValidationError("missing_field:%s" % missing[0] if missing else "unexpected_field:%s" % extra[0])
    return command


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModeValidationError(field)
    return value.strip()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    temporary = path.with_name(".%s.%s.tmp" % (path.name, secrets.token_hex(8)))
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


class ModeValidationRequestHandler(SimpleHTTPRequestHandler):
    server_version = "ModeValidationWorkbench/1"

    @property
    def application(self) -> WorkbenchApplication:
        return self.server.application  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": code, "message": message})

    def _reject_oversized_body(self, length: int) -> None:
        self._error(413, "request_too_large", "JSON 请求不能超过 256 KiB。")
        self.wfile.flush()
        self.close_connection = True
        remaining = min(length, MAX_REJECT_DRAIN_BYTES)
        try:
            self.connection.settimeout(0.2)
            while remaining:
                chunk = self.rfile.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
        except OSError:
            pass

    def _host_allowed(self) -> bool:
        host = str(self.headers.get("Host") or "")
        port = int(self.server.server_address[1])
        return host in {"127.0.0.1:%d" % port, "[::1]:%d" % port}

    def _origin_allowed(self) -> bool:
        return self.application.origin_allowed(self.headers.get("Origin"))

    def _read_json(self) -> dict[str, Any] | None:
        value = self.headers.get("Content-Length")
        try:
            length = int(value or "0")
        except ValueError:
            self._error(400, "invalid_content_length", "请求长度无效。")
            return None
        if length > MAX_REQUEST_BYTES:
            self._reject_oversized_body(length)
            return None
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            self._error(400, "invalid_json", "请求必须是有效 JSON。")
            return None
        if not isinstance(parsed, dict):
            self._error(400, "invalid_json", "请求必须是 JSON 对象。")
            return None
        return parsed

    def _authorize_write(self) -> tuple[bool, str]:
        if not self._host_allowed():
            return False, "host_forbidden"
        if not self._origin_allowed():
            return False, "origin_forbidden"
        return self.application.require_session(self.headers.get("X-Workbench-Token"))

    def do_GET(self) -> None:
        if self.path == "/api/mode-validation/snapshot":
            if not self._host_allowed():
                self._error(403, "host_forbidden", "只允许回环地址访问。")
                return
            try:
                self._json(200, self.application.snapshot())
            except ModeValidationError:
                self._error(400, "state_unavailable", "模式验证状态不可用。")
            return
        if self.path == "/api/mode-validation/validators":
            self._json(200, {"validators": validator_catalog()})
            return
        super().do_GET()

    def do_POST(self) -> None:
        body = self._read_json()
        if body is None:
            return
        if not self._host_allowed():
            self._error(403, "host_forbidden", "只允许回环地址访问。")
            return
        if not self._origin_allowed():
            self._error(403, "origin_forbidden", "写入来源必须是当前回环工作台。")
            return

        if self.path == "/api/mode-validation/session":
            try:
                require_fields(body, set())
            except ModeValidationError:
                self._error(400, "invalid_request", "会话请求字段无效。")
                return
            self._json(201, {"token": self.application.open_session(), "expires_in": self.application.session_ttl})
            return

        authorized, reason = self.application.require_session(self.headers.get("X-Workbench-Token"))
        if not authorized:
            message = "本机会话已过期。" if reason == "session_expired" else "写入需要有效的本机会话。"
            self._error(403, reason, message)
            return
        token = str(self.headers.get("X-Workbench-Token") or "")
        if self.path == "/api/mode-validation/session/heartbeat":
            try:
                require_fields(body, set())
            except ModeValidationError:
                self._error(400, "invalid_request", "心跳请求字段无效。")
                return
            self._json(200, {"status": "active"})
            return
        if self.path == "/api/mode-validation/session/close":
            self.application.close_session(token)
            self._json(200, {"status": "closed"})
            return

        try:
            if self.path == "/api/mode-validation/tasks":
                self._json(201, self.application.create_task(body))
                return
            match = PROPOSITION_CONFIRM.match(self.path)
            if match:
                self._json(200, self.application.confirm_proposition(match.group(1), body))
                return
            if self.path == "/api/mode-validation/runs/preview":
                self._json(200, self.application.run_preview(body))
                return
            if self.path == "/api/mode-validation/runs":
                self._json(201, self.application.create_run(body))
                return
            match = RUN_CANDIDATE_QUALIFY.match(self.path)
            if match:
                self._json(200, self.application.qualify_candidate(match.group(1), match.group(2), body))
                return
            match = RUN_ACTION.match(self.path)
            if match:
                run_id, action = match.groups()
                if action == "execute":
                    self._json(200, self.application.queue_run(run_id, body))
                elif action == "cancel":
                    self._json(200, self.application.cancel_run(run_id, body))
                else:
                    self._json(200, self.application.invalidate_run(run_id, body))
                return
            if self.path == "/api/mode-validation/reviews":
                self._json(201, self.application.append_review(body))
                return
            if self.path == "/api/mode-validation/mode-change/preview":
                self._json(200, self.application.preview_mode_change(body))
                return
            if self.path == "/api/mode-validation/mode-change/confirm":
                self._json(200, self.application.confirm_mode_change(body))
                return
            self._error(404, "route_not_found", "接口不存在。")
        except ModeValidationConflict:
            self._error(409, "state_conflict", "状态已经变化，请刷新后重新预览。")
        except ModeValidationError:
            self._error(400, "invalid_request", "请求不符合模式验证合同。")
        except Exception:
            self._error(500, "internal_error", "本地工作台处理失败。")


class ModeValidationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_close(self) -> None:
        application = getattr(self, "application", None)
        if application is not None:
            application.stop_queue_worker()
        super().server_close()


def create_server(
    host: str,
    port: int,
    site_dir: Path,
    state_dir: Path,
    reports_dir: Path,
    session_ttl: float = 45.0,
    start_worker: bool = True,
) -> ModeValidationHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("mode-validation service must bind to 127.0.0.1")
    site = Path(site_dir).resolve()

    class BoundHandler(ModeValidationRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(site), **kwargs)

    application = WorkbenchApplication(Path(state_dir), Path(reports_dir), session_ttl, start_worker)
    server = ModeValidationHTTPServer((host, port), BoundHandler)
    server.application = application  # type: ignore[attr-defined]
    application.server = server
    application.start_queue_worker()
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description="启动仅回环可写的模式验证工作台。")
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--site", type=Path, default=ROOT / "reports" / "personal_site")
    parser.add_argument("--state", type=Path, default=ROOT / "state")
    parser.add_argument("--reports", type=Path, default=ROOT / "reports" / "mode_validation")
    parser.add_argument("--source-reports", type=Path, default=ROOT / "reports")
    args = parser.parse_args()
    from build_personal_site import write_site

    write_site(
        sqlite_path=args.state / "account_ledger.sqlite",
        reports_dir=args.source_reports,
        output_dir=args.site,
        state_dir=args.state,
    )
    server = create_server(args.host, args.port, args.site, args.state, args.reports)
    print("mode_validation_url=http://127.0.0.1:%d/mode-validation.html" % server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
