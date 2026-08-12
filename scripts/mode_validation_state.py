#!/usr/bin/env python3
"""Durable, fail-closed state for personal trading mode validation."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


TASK_STATUSES = {"active", "superseded", "closed"}
PROPOSITION_STATUSES = {"draft", "collecting", "awaiting_review", "closed", "superseded"}
RUN_KINDS = {"exploratory", "formal"}
RUN_STATUSES = {
    "awaiting_qualification",
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "invalidated",
}
QUALIFICATIONS = {"pending", "included", "excluded", "qualification_missing"}
EVIDENCE_DIRECTIONS = {"support", "oppose", "indeterminate"}
AUDIT_OUTCOMES = {"pass", "pass_with_warning", "fail"}
PROPOSITION_VERDICTS = {"supported", "opposed", "mixed", "insufficient"}
MODE_VERDICTS = {"continue_validating", "replicable", "avoid", "revise_new_version"}


class ModeValidationError(ValueError):
    """Raised when a mode-validation command violates a domain rule."""


class ModeValidationConflict(ModeValidationError):
    """Raised when immutable or concurrent state no longer matches."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return "%s_%s" % (prefix, uuid.uuid4().hex)


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically and reject non-finite numbers."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


MODE_SNAPSHOT_FIELDS = (
    "id",
    "name",
    "version",
    "applicable_environment",
    "trigger_conditions",
    "execution_boundaries",
    "invalidation_conditions",
    "max_risk",
    "next_validation_requirement",
)


def mode_definition_snapshot(mode: dict[str, Any]) -> dict[str, Any]:
    """Return only the user-owned mode contract fields that formal evidence freezes."""

    return {field: mode.get(field) for field in MODE_SNAPSHOT_FIELDS}


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModeValidationError(field)
    return value.strip()


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ModeValidationError(field)
    return value


def _require_enum(value: Any, field: str, allowed: set[str]) -> str:
    text = _require_text(value, field)
    if text not in allowed:
        raise ModeValidationError(field)
    return text


def _json_list(value: Any, field: str, require_items: bool = False) -> str:
    items = _require_list(value, field)
    if require_items and not items:
        raise ModeValidationError(field)
    return canonical_json(items)


def _finite(value: Any) -> bool:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_finite(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite(item) for key, item in value.items())
    return False


def audit_evidence(context: dict[str, Any]) -> tuple[str, list[str]]:
    """Return a deterministic publication outcome with failures taking precedence."""

    failures: list[str] = []
    if context.get("run_status") == "invalidated":
        failures.append("run_invalidated")
    elif context.get("run_status") != "succeeded":
        failures.append("run_not_succeeded")
    if not context.get("mode_hash_matches", False):
        failures.append("mode_hash_mismatch")
    if not context.get("sources_exist", False):
        failures.append("source_missing")
    if not context.get("proposition_exists", False):
        failures.append("proposition_missing")
    if not context.get("falsifier_exists", False):
        failures.append("falsifier_missing")
    if not _finite(context.get("metrics", {})):
        failures.append("non_finite_metric")
    if not context.get("artifact_hash_matches", False):
        failures.append("artifact_hash_mismatch")
    if context.get("run_kind") == "exploratory" and context.get("presented_as_formal", False):
        failures.append("exploratory_as_formal")
    if failures:
        return "fail", failures

    warnings: list[str] = []
    if not context.get("independent_segment", False):
        warnings.append("independent_segment_missing")
    for limitation in context.get("limitations", []):
        if isinstance(limitation, str) and limitation and limitation not in warnings:
            warnings.append(limitation)
    return ("pass_with_warning", warnings) if warnings else ("pass", [])


def draft_propositions(mode: dict[str, Any]) -> list[dict[str, Any]]:
    """Create four editable proposition drafts from the current mode definition."""

    definitions = (
        ("environment", "适用环境成立", mode.get("applicable_environment", []), "environment_match"),
        ("trigger", "触发条件具有区分度", mode.get("trigger_conditions", []), "trigger_match"),
        ("boundary", "执行边界能够约束风险", mode.get("execution_boundaries", []), "boundary_followed"),
        ("invalidation", "失效条件能够及时停止模式", mode.get("invalidation_conditions", []), "invalidation_respected"),
    )
    drafts = []
    for category, title, source, metric in definitions:
        source_items = [str(item) for item in source] if isinstance(source, list) else []
        statement = "%s：%s" % (title, "；".join(source_items) or "需要人工补充")
        drafts.append(
            {
                "category": category,
                "title": title,
                "statement": statement,
                "acceptance_criteria": [{"metric": metric, "operator": "==", "value": True}],
                "falsifiers": [{"metric": metric, "operator": "==", "value": False}],
                "workflow_status": "draft",
                "required": True,
            }
        )
    return drafts


SCHEMA = """
create table if not exists validation_tasks (
  task_id text primary key,
  mode_id text not null,
  mode_version text not null,
  status text not null check (status in ('active','superseded','closed')),
  mode_snapshot_json text not null,
  mode_snapshot_hash text not null,
  research_goal_json text not null,
  created_at text not null,
  superseded_by_task_id text
);
create unique index if not exists one_active_task_per_mode_version
  on validation_tasks(mode_id, mode_version) where status = 'active';

create table if not exists propositions (
  proposition_id text primary key,
  task_id text not null references validation_tasks(task_id),
  title text not null,
  statement text not null,
  acceptance_criteria_json text not null,
  falsifiers_json text not null,
  workflow_status text not null check (workflow_status in ('draft','collecting','awaiting_review','closed','superseded')),
  required integer not null check (required in (0,1)),
  confirmed_at text,
  created_at text not null
);

create table if not exists validation_runs (
  run_id text primary key,
  task_id text not null references validation_tasks(task_id),
  proposition_id text not null references propositions(proposition_id),
  validator_id text not null,
  run_kind text not null check (run_kind in ('exploratory','formal')),
  status text not null check (status in ('awaiting_qualification','queued','running','succeeded','failed','cancelled','invalidated')),
  mode_snapshot_hash text not null,
  protocol_json text not null,
  protocol_hash text not null,
  config_json text not null,
  data_fingerprint text not null,
  result_json text,
  artifact_relative_path text,
  artifact_hash text,
  warning_json text not null default '[]',
  failure_reason text,
  stop_requested integer not null default 0 check (stop_requested in (0,1)),
  created_at text not null,
  started_at text,
  finished_at text
);

create trigger if not exists validation_runs_immutable_contract
before update of task_id, proposition_id, validator_id, run_kind, mode_snapshot_hash,
  protocol_json, protocol_hash, config_json, data_fingerprint, created_at
on validation_runs
begin
  select raise(abort, 'immutable run contract');
end;

create table if not exists run_candidates (
  candidate_id text primary key,
  run_id text not null references validation_runs(run_id),
  source_ref text not null,
  observed_at text not null,
  masked_context_json text not null,
  qualification text not null check (qualification in ('pending','included','excluded','qualification_missing')),
  qualification_reason text,
  qualification_deadline text,
  qualified_at text,
  outcome_json text,
  outcome_revealed_at text,
  unique(run_id, source_ref)
);

create table if not exists evidence (
  evidence_id text primary key,
  run_id text not null references validation_runs(run_id),
  proposition_id text not null references propositions(proposition_id),
  direction text not null check (direction in ('support','oppose','indeterminate')),
  summary text not null,
  metrics_json text not null,
  source_refs_json text not null,
  independent_segment integer not null check (independent_segment in (0,1)),
  created_at text not null
);

create table if not exists publication_audits (
  audit_id text primary key,
  evidence_id text not null unique references evidence(evidence_id),
  outcome text not null check (outcome in ('pass','pass_with_warning','fail')),
  reasons_json text not null,
  audited_at text not null
);

create table if not exists review_events (
  review_event_id text primary key,
  task_id text not null references validation_tasks(task_id),
  proposition_id text references propositions(proposition_id),
  scope text not null check (scope in ('proposition','mode')),
  verdict text not null,
  note text not null,
  evidence_ids_json text not null,
  supersedes_event_id text references review_events(review_event_id),
  created_at text not null
);

create table if not exists mode_change_writes (
  mode_change_id text primary key,
  task_id text not null references validation_tasks(task_id),
  review_event_id text not null unique references review_events(review_event_id),
  pre_write_hash text not null,
  post_write_hash text not null,
  target_status text not null check (target_status in ('validating','replicable','avoid')),
  written_at text not null
);
"""


class ModeValidationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        connection.execute("pragma journal_mode = wal")
        return connection

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("begin immediate")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_task(self, mode: dict[str, Any], research_goal: dict[str, Any]) -> str:
        mode_id = _require_text(mode.get("id"), "mode.id")
        mode_version = _require_text(mode.get("version"), "mode.version")
        task_id = new_id("task")
        created_at = utc_now()
        snapshot = mode_definition_snapshot(mode)
        snapshot_json = canonical_json(snapshot)
        snapshot_hash = content_hash(snapshot)
        goal_json = canonical_json(research_goal)
        with self._write() as connection:
            previous = connection.execute(
                "select task_id from validation_tasks where mode_id = ? and mode_version = ? and status = 'active'",
                (mode_id, mode_version),
            ).fetchone()
            if previous:
                connection.execute(
                    "update validation_tasks set status = 'superseded', superseded_by_task_id = ? where task_id = ?",
                    (task_id, previous["task_id"]),
                )
            connection.execute(
                """
                insert into validation_tasks (
                  task_id, mode_id, mode_version, status, mode_snapshot_json,
                  mode_snapshot_hash, research_goal_json, created_at
                ) values (?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (task_id, mode_id, mode_version, snapshot_json, snapshot_hash, goal_json, created_at),
            )
        return task_id

    def list_tasks(self, mode_id: str | None = None, mode_version: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if mode_id is not None:
            clauses.append("mode_id = ?")
            params.append(mode_id)
        if mode_version is not None:
            clauses.append("mode_version = ?")
            params.append(mode_version)
        where = " where " + " and ".join(clauses) if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "select * from validation_tasks%s order by created_at desc, rowid desc" % where,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_task(self, task_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
        owns_connection = connection is None
        active = connection or self._connect()
        try:
            row = active.execute("select * from validation_tasks where task_id = ?", (task_id,)).fetchone()
            if not row:
                raise ModeValidationError("task_id")
            return dict(row)
        finally:
            if owns_connection:
                active.close()

    def create_proposition(
        self,
        task_id: str,
        title: str,
        statement: str,
        acceptance_criteria: list[Any],
        falsifiers: list[Any],
        required: bool,
    ) -> str:
        proposition_id = new_id("prop")
        with self._write() as connection:
            self.get_task(task_id, connection)
            connection.execute(
                """
                insert into propositions (
                  proposition_id, task_id, title, statement, acceptance_criteria_json,
                  falsifiers_json, workflow_status, required, created_at
                ) values (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    proposition_id,
                    task_id,
                    _require_text(title, "title"),
                    _require_text(statement, "statement"),
                    _json_list(acceptance_criteria, "acceptance_criteria"),
                    _json_list(falsifiers, "falsifiers"),
                    1 if required else 0,
                    utc_now(),
                ),
            )
        return proposition_id

    def get_proposition(
        self, proposition_id: str, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        owns_connection = connection is None
        active = connection or self._connect()
        try:
            row = active.execute("select * from propositions where proposition_id = ?", (proposition_id,)).fetchone()
            if not row:
                raise ModeValidationError("proposition_id")
            return dict(row)
        finally:
            if owns_connection:
                active.close()

    def confirm_proposition(self, proposition_id: str) -> None:
        with self._write() as connection:
            proposition = self.get_proposition(proposition_id, connection)
            criteria = json.loads(proposition["acceptance_criteria_json"])
            falsifiers = json.loads(proposition["falsifiers_json"])
            if not criteria or not all(isinstance(item, dict) and item for item in criteria):
                raise ModeValidationError("acceptance_criteria")
            if not falsifiers or not all(isinstance(item, dict) and item for item in falsifiers):
                raise ModeValidationError("falsifier")
            if proposition["workflow_status"] != "draft":
                raise ModeValidationConflict("proposition_not_draft")
            connection.execute(
                "update propositions set workflow_status = 'collecting', confirmed_at = ? where proposition_id = ?",
                (utc_now(), proposition_id),
            )

    def create_run(
        self,
        task_id: str,
        proposition_id: str,
        validator_id: str,
        run_kind: str,
        protocol: dict[str, Any],
        config: dict[str, Any],
        data_fingerprint: str,
        candidates: list[dict[str, Any]],
    ) -> str:
        kind = _require_enum(run_kind, "run_kind", RUN_KINDS)
        candidate_rows = _require_list(candidates, "candidates")
        run_id = new_id("run")
        with self._write() as connection:
            task = self.get_task(task_id, connection)
            proposition = self.get_proposition(proposition_id, connection)
            if proposition["task_id"] != task_id or proposition["workflow_status"] == "draft":
                raise ModeValidationError("proposition")
            status = "awaiting_qualification"
            protocol_json = canonical_json(protocol)
            connection.execute(
                """
                insert into validation_runs (
                  run_id, task_id, proposition_id, validator_id, run_kind, status,
                  mode_snapshot_hash, protocol_json, protocol_hash, config_json,
                  data_fingerprint, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    task_id,
                    proposition_id,
                    _require_text(validator_id, "validator_id"),
                    kind,
                    status,
                    task["mode_snapshot_hash"],
                    protocol_json,
                    content_hash(protocol),
                    canonical_json(config),
                    _require_text(data_fingerprint, "data_fingerprint"),
                    utc_now(),
                ),
            )
            for candidate in candidate_rows:
                source_ref = _require_text(candidate.get("source_ref"), "candidate.source_ref")
                connection.execute(
                    """
                    insert into run_candidates (
                      candidate_id, run_id, source_ref, observed_at, masked_context_json,
                      qualification, qualification_deadline
                    ) values (?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    (
                        new_id("candidate"),
                        run_id,
                        source_ref,
                        _require_text(candidate.get("observed_at"), "candidate.observed_at"),
                        canonical_json(candidate.get("masked_context", {})),
                        candidate.get("qualification_deadline"),
                    ),
                )
        return run_id

    def _get_run(self, run_id: str, connection: sqlite3.Connection) -> dict[str, Any]:
        row = connection.execute("select * from validation_runs where run_id = ?", (run_id,)).fetchone()
        if not row:
            raise ModeValidationError("run_id")
        return dict(row)

    def get_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            return self._get_run(run_id, connection)

    def list_candidates(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from run_candidates where run_id = ? order by observed_at, rowid",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _transition(self, connection: sqlite3.Connection, run_id: str, allowed: set[str], status: str) -> None:
        run = self._get_run(run_id, connection)
        if run["status"] not in allowed:
            raise ModeValidationConflict("run_status")
        connection.execute("update validation_runs set status = ? where run_id = ?", (status, run_id))

    def mark_run_running(self, run_id: str) -> None:
        with self._write() as connection:
            self._transition(connection, run_id, {"queued"}, "running")
            connection.execute("update validation_runs set started_at = ? where run_id = ?", (utc_now(), run_id))

    def claim_next_queued_run(self) -> dict[str, Any] | None:
        with self._write() as connection:
            running = connection.execute(
                "select count(*) from validation_runs where status = 'running'"
            ).fetchone()[0]
            if running:
                return None
            row = connection.execute(
                "select run_id from validation_runs where status = 'queued' order by created_at, rowid limit 1"
            ).fetchone()
            if not row:
                return None
            run_id = str(row["run_id"])
            self._transition(connection, run_id, {"queued"}, "running")
            connection.execute(
                "update validation_runs set started_at = ?, stop_requested = 0 where run_id = ?",
                (utc_now(), run_id),
            )
            return self._get_run(run_id, connection)

    def fail_interrupted_runs(self) -> list[str]:
        with self._write() as connection:
            rows = connection.execute(
                "select run_id from validation_runs where status = 'running' order by rowid"
            ).fetchall()
            run_ids = [str(row["run_id"]) for row in rows]
            if run_ids:
                connection.execute(
                    """
                    update validation_runs
                       set status = 'failed', failure_reason = 'service_interrupted', finished_at = ?
                     where status = 'running'
                    """,
                    (utc_now(),),
                )
            return run_ids

    def fail_run(self, run_id: str, reason: str) -> None:
        with self._write() as connection:
            self._transition(connection, run_id, {"running"}, "failed")
            connection.execute(
                "update validation_runs set failure_reason = ?, finished_at = ? where run_id = ?",
                (_require_text(reason, "reason"), utc_now(), run_id),
            )

    def cancel_run(self, run_id: str) -> str:
        with self._write() as connection:
            run = self._get_run(run_id, connection)
            if run["status"] in {"awaiting_qualification", "queued"}:
                connection.execute(
                    "update validation_runs set status = 'cancelled', failure_reason = 'user_cancelled', finished_at = ? where run_id = ?",
                    (utc_now(), run_id),
                )
                return "cancelled"
            if run["status"] == "running":
                connection.execute(
                    "update validation_runs set stop_requested = 1 where run_id = ?",
                    (run_id,),
                )
                return "stop_requested"
            raise ModeValidationConflict("run_status")

    def stop_requested(self, run_id: str) -> bool:
        return bool(self.get_run(run_id).get("stop_requested"))

    def finish_cancelled_run(self, run_id: str) -> None:
        with self._write() as connection:
            run = self._get_run(run_id, connection)
            if run["status"] != "running" or not run["stop_requested"]:
                raise ModeValidationConflict("run_status")
            connection.execute(
                "update validation_runs set status = 'cancelled', failure_reason = 'safe_stop', finished_at = ? where run_id = ?",
                (utc_now(), run_id),
            )

    def queue_run(self, run_id: str) -> None:
        with self._write() as connection:
            run = self._get_run(run_id, connection)
            if run["status"] != "awaiting_qualification":
                raise ModeValidationConflict("run_status")
            pending = connection.execute(
                "select count(*) from run_candidates where run_id = ? and qualification = 'pending'",
                (run_id,),
            ).fetchone()[0]
            if pending:
                raise ModeValidationConflict("candidate_qualification_pending")
            self._transition(connection, run_id, {"awaiting_qualification"}, "queued")

    def finish_run(
        self,
        run_id: str,
        result: dict[str, Any],
        warnings: list[str],
        artifact_relative_path: str | None = None,
        artifact_hash: str | None = None,
    ) -> None:
        if not _finite(result):
            raise ModeValidationError("result")
        with self._write() as connection:
            self._transition(connection, run_id, {"running"}, "succeeded")
            connection.execute(
                """
                update validation_runs
                   set result_json = ?, warning_json = ?, artifact_relative_path = ?, artifact_hash = ?, finished_at = ?
                 where run_id = ?
                """,
                (canonical_json(result), canonical_json(warnings), artifact_relative_path, artifact_hash, utc_now(), run_id),
            )

    def qualify_candidate(self, candidate_id: str, qualification: str, reason: str = "") -> None:
        value = _require_enum(qualification, "qualification", QUALIFICATIONS - {"pending"})
        if value in {"excluded", "qualification_missing"} and not reason.strip():
            raise ModeValidationError("qualification_reason")
        with self._write() as connection:
            row = connection.execute("select * from run_candidates where candidate_id = ?", (candidate_id,)).fetchone()
            if not row:
                raise ModeValidationConflict("candidate")
            if row["qualification"] == "qualification_missing":
                if not reason.strip():
                    raise ModeValidationError("qualification_reason")
                connection.execute(
                    """
                    update run_candidates
                       set qualification_reason = ?, qualified_at = ?
                     where candidate_id = ?
                    """,
                    (
                        "deadline_missed;late_backfill=%s:%s" % (value, reason.strip()),
                        utc_now(),
                        candidate_id,
                    ),
                )
                return
            if row["qualification"] != "pending":
                raise ModeValidationConflict("candidate")
            connection.execute(
                "update run_candidates set qualification = ?, qualification_reason = ?, qualified_at = ? where candidate_id = ?",
                (value, reason.strip() or None, utc_now(), candidate_id),
            )

    def reveal_candidate_outcomes(self, run_id: str, outcomes_by_source: dict[str, Any]) -> None:
        if not isinstance(outcomes_by_source, dict) or not _finite(outcomes_by_source):
            raise ModeValidationError("outcomes")
        with self._write() as connection:
            run = self._get_run(run_id, connection)
            candidates = connection.execute(
                "select * from run_candidates where run_id = ? order by rowid",
                (run_id,),
            ).fetchall()
            if any(row["qualification"] == "pending" for row in candidates):
                raise ModeValidationError("qualification_pending")
            if run["status"] != "running":
                raise ModeValidationConflict("run_status")
            if any(row["outcome_revealed_at"] is not None for row in candidates):
                raise ModeValidationError("outcome_already_revealed")
            revealed_at = utc_now()
            for row in candidates:
                outcome = outcomes_by_source.get(str(row["source_ref"]))
                if outcome is None:
                    continue
                connection.execute(
                    "update run_candidates set outcome_json = ?, outcome_revealed_at = ? where candidate_id = ?",
                    (canonical_json(outcome), revealed_at, row["candidate_id"]),
                )

    def expire_candidate_qualifications(self, now: str | None = None) -> list[str]:
        value = now or utc_now()
        try:
            current = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ModeValidationError("now") from exc
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        expired: list[str] = []
        with self._write() as connection:
            rows = connection.execute(
                """
                select candidate_id, qualification_deadline from run_candidates
                 where qualification = 'pending' and qualification_deadline is not null
                """
            ).fetchall()
            for row in rows:
                try:
                    deadline = datetime.fromisoformat(str(row["qualification_deadline"]).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if current <= deadline:
                    continue
                candidate_id = str(row["candidate_id"])
                connection.execute(
                    """
                    update run_candidates
                       set qualification = 'qualification_missing',
                           qualification_reason = 'deadline_missed', qualified_at = ?
                     where candidate_id = ? and qualification = 'pending'
                    """,
                    (value, candidate_id),
                )
                expired.append(candidate_id)
        return expired

    def record_evidence(
        self,
        run_id: str,
        proposition_id: str,
        direction: str,
        summary: str,
        metrics: dict[str, Any],
        source_refs: list[str],
        independent_segment: bool,
        audit_context: dict[str, Any],
    ) -> str:
        evidence_id = new_id("evidence")
        with self._write() as connection:
            run = self._get_run(run_id, connection)
            proposition = self.get_proposition(proposition_id, connection)
            context = {
                "run_status": run["status"],
                "mode_hash_matches": run["mode_snapshot_hash"]
                == self.get_task(run["task_id"], connection)["mode_snapshot_hash"],
                "sources_exist": audit_context.get("sources_exist", False),
                "proposition_exists": proposition["task_id"] == run["task_id"],
                "falsifier_exists": bool(json.loads(proposition["falsifiers_json"])),
                "metrics": metrics,
                "artifact_hash_matches": audit_context.get("artifact_hash_matches", False),
                "run_kind": run["run_kind"],
                "presented_as_formal": audit_context.get("presented_as_formal", run["run_kind"] == "formal"),
                "independent_segment": independent_segment,
                "limitations": audit_context.get("limitations", []),
            }
            outcome, reasons = audit_evidence(context)
            connection.execute(
                """
                insert into evidence (
                  evidence_id, run_id, proposition_id, direction, summary, metrics_json,
                  source_refs_json, independent_segment, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    run_id,
                    proposition_id,
                    _require_enum(direction, "direction", EVIDENCE_DIRECTIONS),
                    _require_text(summary, "summary"),
                    canonical_json(metrics),
                    canonical_json(source_refs),
                    1 if independent_segment else 0,
                    utc_now(),
                ),
            )
            connection.execute(
                "insert into publication_audits values (?, ?, ?, ?, ?)",
                (new_id("audit"), evidence_id, outcome, canonical_json(reasons), utc_now()),
            )
        return evidence_id

    def append_review(
        self,
        task_id: str,
        scope: str,
        verdict: str,
        note: str,
        proposition_id: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> str:
        if scope not in {"proposition", "mode"}:
            raise ModeValidationError("scope")
        allowed = PROPOSITION_VERDICTS if scope == "proposition" else MODE_VERDICTS
        verdict = _require_enum(verdict, "verdict", allowed)
        if scope == "proposition" and not proposition_id:
            raise ModeValidationError("proposition_id")
        if scope == "mode" and proposition_id is not None:
            raise ModeValidationError("proposition_id")
        review_id = new_id("review")
        evidence_values = evidence_ids or []
        with self._write() as connection:
            self.get_task(task_id, connection)
            if proposition_id:
                proposition = self.get_proposition(proposition_id, connection)
                if proposition["task_id"] != task_id:
                    raise ModeValidationError("proposition_id")
            if scope == "mode":
                required_rows = connection.execute(
                    """
                    select proposition_id from propositions
                     where task_id = ? and required = 1 and workflow_status != 'superseded'
                    """,
                    (task_id,),
                ).fetchall()
                reviewed = {
                    str(row["proposition_id"])
                    for row in connection.execute(
                        """
                        select distinct proposition_id from review_events
                         where task_id = ? and scope = 'proposition' and proposition_id is not null
                        """,
                        (task_id,),
                    ).fetchall()
                }
                if any(str(row["proposition_id"]) not in reviewed for row in required_rows):
                    raise ModeValidationError("required_propositions_unreviewed")
                for required in required_rows:
                    latest = connection.execute(
                        """
                        select evidence_ids_json from review_events
                         where task_id = ? and scope = 'proposition' and proposition_id = ?
                         order by created_at desc, rowid desc limit 1
                        """,
                        (task_id, required["proposition_id"]),
                    ).fetchone()
                    evidence_values = json.loads(latest["evidence_ids_json"]) if latest else []
                    for evidence_id in evidence_values:
                        dependency = connection.execute(
                            """
                            select r.status as run_status, a.outcome as audit_outcome
                              from evidence e
                              join validation_runs r on r.run_id = e.run_id
                              join publication_audits a on a.evidence_id = e.evidence_id
                             where e.evidence_id = ?
                            """,
                            (evidence_id,),
                        ).fetchone()
                        if not dependency or dependency["run_status"] == "invalidated" or dependency["audit_outcome"] == "fail":
                            raise ModeValidationError("required_propositions_need_rereview")
            prior = connection.execute(
                """
                select review_event_id from review_events
                 where task_id = ? and scope = ? and proposition_id is ?
                 order by created_at desc, rowid desc limit 1
                """,
                (task_id, scope, proposition_id),
            ).fetchone()
            if evidence_values:
                placeholders = ",".join("?" for _ in evidence_values)
                evidence_rows = connection.execute(
                    """
                    select e.evidence_id, e.proposition_id, p.task_id, a.outcome
                      from evidence e
                      join propositions p on p.proposition_id = e.proposition_id
                      join publication_audits a on a.evidence_id = e.evidence_id
                     where e.evidence_id in (%s)
                    """ % placeholders,
                    tuple(evidence_values),
                ).fetchall()
                if len(evidence_rows) != len(set(evidence_values)):
                    raise ModeValidationError("evidence_ids")
                if any(
                    row["task_id"] != task_id
                    or row["outcome"] == "fail"
                    or (scope == "proposition" and row["proposition_id"] != proposition_id)
                    for row in evidence_rows
                ):
                    raise ModeValidationError("evidence_not_publishable")
            connection.execute(
                """
                insert into review_events (
                  review_event_id, task_id, proposition_id, scope, verdict, note,
                  evidence_ids_json, supersedes_event_id, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    task_id,
                    proposition_id,
                    scope,
                    verdict,
                    _require_text(note, "note"),
                    canonical_json(evidence_values),
                    prior["review_event_id"] if prior else None,
                    utc_now(),
                ),
            )
            if proposition_id:
                connection.execute(
                    "update propositions set workflow_status = 'closed' where proposition_id = ?",
                    (proposition_id,),
                )
        return review_id

    def list_reviews(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "select * from review_events where task_id = ? order by created_at desc, rowid desc",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def current_review(
        self, task_id: str, scope: str, proposition_id: str | None = None
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                select * from review_events
                 where task_id = ? and scope = ? and proposition_id is ?
                 order by created_at desc, rowid desc limit 1
                """,
                (task_id, scope, proposition_id),
            ).fetchone()
        return dict(row) if row else None

    def invalidate_run(self, run_id: str, reason: str) -> None:
        with self._write() as connection:
            self._transition(connection, run_id, {"awaiting_qualification", "queued", "running", "succeeded"}, "invalidated")
            connection.execute(
                "update validation_runs set failure_reason = ?, finished_at = ? where run_id = ?",
                (_require_text(reason, "reason"), utc_now(), run_id),
            )
            proposition_rows = connection.execute(
                "select distinct proposition_id from evidence where run_id = ?",
                (run_id,),
            ).fetchall()
            for row in proposition_rows:
                connection.execute(
                    "update propositions set workflow_status = 'awaiting_review' where proposition_id = ?",
                    (row["proposition_id"],),
                )

    def record_mode_change(
        self,
        task_id: str,
        review_event_id: str,
        pre_write_hash: str,
        post_write_hash: str,
        target_status: str,
    ) -> str:
        status = _require_enum(target_status, "target_status", {"validating", "replicable", "avoid"})
        mode_change_id = new_id("mode_change")
        with self._write() as connection:
            task = self.get_task(task_id, connection)
            review = connection.execute(
                "select * from review_events where review_event_id = ?",
                (review_event_id,),
            ).fetchone()
            if not review or review["task_id"] != task["task_id"] or review["scope"] != "mode":
                raise ModeValidationError("review_event_id")
            connection.execute(
                """
                insert into mode_change_writes (
                  mode_change_id, task_id, review_event_id, pre_write_hash,
                  post_write_hash, target_status, written_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mode_change_id,
                    task_id,
                    review_event_id,
                    _require_text(pre_write_hash, "pre_write_hash"),
                    _require_text(post_write_hash, "post_write_hash"),
                    status,
                    utc_now(),
                ),
            )
        return mode_change_id

    def snapshot_rows(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            tables = {}
            for key, table in (
                ("tasks", "validation_tasks"),
                ("propositions", "propositions"),
                ("runs", "validation_runs"),
                ("candidates", "run_candidates"),
                ("evidence", "evidence"),
                ("audits", "publication_audits"),
                ("reviews", "review_events"),
            ):
                tables[key] = [dict(row) for row in connection.execute("select * from %s" % table).fetchall()]

        run_status = {row["run_id"]: row["status"] for row in tables["runs"]}
        evidence_run = {row["evidence_id"]: row["run_id"] for row in tables["evidence"]}
        audit_outcome = {row["evidence_id"]: row["outcome"] for row in tables["audits"]}
        for review in tables["reviews"]:
            evidence_ids = json.loads(review["evidence_ids_json"])
            review["needs_rereview"] = any(
                run_status.get(evidence_run.get(evidence_id, "")) == "invalidated"
                or audit_outcome.get(evidence_id) == "fail"
                for evidence_id in evidence_ids
            )
        return tables
