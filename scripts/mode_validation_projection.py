#!/usr/bin/env python3
"""Build the fail-closed, static projection for the mode-validation page."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mode_validation_state import ModeValidationStore, content_hash, mode_definition_snapshot
from mode_validation_validators import validator_catalog
from personal_site_state import StateValidationError, canonical_project_relative_path


RISK_KINDS = (
    ("invalidated_dependency", "依赖已作废"),
    ("audit_failure", "证据审计失败"),
    ("needs_rereview", "需要重新评审"),
    ("awaiting_first_review", "等待首次评审"),
    ("collecting_evidence", "正在收集证据"),
)


def _json(value: Any, fallback: Any) -> Any:
    if not isinstance(value, str):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _source_ref(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.startswith("ledger-cycle:") and "/" not in text and "\\" not in text:
        return text
    try:
        normalized = canonical_project_relative_path(text)
    except StateValidationError:
        return None
    return normalized or None


def _empty_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "tasks": [],
        "propositions": [],
        "runs": [],
        "candidates": [],
        "evidence": [],
        "audits": [],
        "reviews": [],
    }


def _current_review_ids(reviews: list[dict[str, Any]]) -> set[str]:
    superseded = {
        str(row.get("supersedes_event_id"))
        for row in reviews
        if row.get("supersedes_event_id")
    }
    return {
        str(row.get("review_event_id"))
        for row in reviews
        if row.get("review_event_id") and str(row.get("review_event_id")) not in superseded
    }


def _project_tasks(
    rows: list[dict[str, Any]], current_modes: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        key = (str(row.get("mode_id") or ""), str(row.get("mode_version") or ""))
        current_mode = current_modes.get(key)
        current_hash = content_hash(mode_definition_snapshot(current_mode)) if current_mode else None
        projected.append(
            {
                "task_id": row.get("task_id"),
                "mode_id": key[0],
                "mode_version": key[1],
                "status": row.get("status"),
                "mode_snapshot_hash": row.get("mode_snapshot_hash"),
                "mode_snapshot": _json(row.get("mode_snapshot_json"), {}),
                "research_goal": _json(row.get("research_goal_json"), {}),
                "mode_drift": current_hash is None or current_hash != row.get("mode_snapshot_hash"),
                "created_at": row.get("created_at"),
                "superseded_by_task_id": row.get("superseded_by_task_id"),
            }
        )
    return sorted(projected, key=lambda item: (str(item["created_at"]), str(item["task_id"])), reverse=True)


def _project_propositions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "proposition_id": row.get("proposition_id"),
            "task_id": row.get("task_id"),
            "title": row.get("title"),
            "statement": row.get("statement"),
            "acceptance_criteria": _json(row.get("acceptance_criteria_json"), []),
            "falsifiers": _json(row.get("falsifiers_json"), []),
            "workflow_status": row.get("workflow_status"),
            "required": bool(row.get("required")),
            "confirmed_at": row.get("confirmed_at"),
            "created_at": row.get("created_at"),
        }
        for row in rows
    ]


def _project_runs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        artifact = _source_ref(row.get("artifact_relative_path"))
        projected.append(
            {
                "run_id": row.get("run_id"),
                "task_id": row.get("task_id"),
                "proposition_id": row.get("proposition_id"),
                "validator_id": row.get("validator_id"),
                "run_kind": row.get("run_kind"),
                "status": row.get("status"),
                "protocol": _json(row.get("protocol_json"), {}),
                "protocol_hash": row.get("protocol_hash"),
                "data_fingerprint": row.get("data_fingerprint"),
                "result": _json(row.get("result_json"), None),
                "artifact_relative_path": artifact,
                "artifact_hash": row.get("artifact_hash"),
                "warnings": _json(row.get("warning_json"), []),
                "failure_reason": row.get("failure_reason"),
                "created_at": row.get("created_at"),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
            }
        )
    return projected


def _project_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": row.get("candidate_id"),
            "run_id": row.get("run_id"),
            "source_ref": _source_ref(row.get("source_ref")),
            "observed_at": row.get("observed_at"),
            "masked_context": _json(row.get("masked_context_json"), {}),
            "qualification": row.get("qualification"),
            "qualification_reason": row.get("qualification_reason"),
            "qualification_deadline": row.get("qualification_deadline"),
            "qualified_at": row.get("qualified_at"),
        }
        for row in rows
    ]


def _project_evidence(
    evidence_rows: list[dict[str, Any]], audit_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    audits = {str(row.get("evidence_id")): row for row in audit_rows}
    projected = []
    for row in evidence_rows:
        audit = audits.get(str(row.get("evidence_id")))
        if not audit or audit.get("outcome") not in {"pass", "pass_with_warning"}:
            continue
        source_refs = []
        for value in _json(row.get("source_refs_json"), []):
            normalized = _source_ref(value)
            if normalized:
                source_refs.append(normalized)
        outcome = str(audit.get("outcome"))
        projected.append(
            {
                "evidence_id": row.get("evidence_id"),
                "run_id": row.get("run_id"),
                "proposition_id": row.get("proposition_id"),
                "direction": row.get("direction"),
                "summary": row.get("summary"),
                "metrics": _json(row.get("metrics_json"), {}),
                "source_refs": source_refs,
                "independent_segment": bool(row.get("independent_segment")),
                "audit_outcome": outcome,
                "audit_reasons": _json(audit.get("reasons_json"), []),
                "satisfies_required_criterion": outcome == "pass",
                "created_at": row.get("created_at"),
            }
        )
    return projected


def _project_reviews(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_ids = _current_review_ids(rows)
    return [
        {
            "review_event_id": row.get("review_event_id"),
            "task_id": row.get("task_id"),
            "proposition_id": row.get("proposition_id"),
            "scope": row.get("scope"),
            "verdict": row.get("verdict"),
            "note": row.get("note"),
            "evidence_ids": _json(row.get("evidence_ids_json"), []),
            "supersedes_event_id": row.get("supersedes_event_id"),
            "created_at": row.get("created_at"),
            "is_current": str(row.get("review_event_id")) in current_ids,
            "needs_rereview": bool(row.get("needs_rereview")),
        }
        for row in rows
    ]


def _risk_queue(
    rows: dict[str, list[dict[str, Any]]],
    propositions: list[dict[str, Any]],
    published_evidence: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    invalidated = [
        {"id": row.get("run_id"), "task_id": row.get("task_id"), "label": "验证运行依赖已作废"}
        for row in rows["runs"]
        if row.get("status") == "invalidated"
    ]
    audit_failures = [
        {"id": row.get("audit_id"), "evidence_id": row.get("evidence_id"), "label": "证据未通过发布审计"}
        for row in rows["audits"]
        if row.get("outcome") == "fail"
    ]
    rereview = [
        {"id": row.get("review_event_id"), "task_id": row.get("task_id"), "label": "当前结论引用了已失效证据"}
        for row in reviews
        if row.get("is_current") and row.get("needs_rereview")
    ]
    reviewed_propositions = {
        str(row.get("proposition_id"))
        for row in reviews
        if row.get("is_current") and row.get("scope") == "proposition"
    }
    evidence_propositions = {str(row.get("proposition_id")) for row in published_evidence}
    awaiting = [
        {"id": row.get("proposition_id"), "task_id": row.get("task_id"), "label": str(row.get("title") or "等待人工评审")}
        for row in propositions
        if row.get("confirmed_at")
        and str(row.get("proposition_id")) not in reviewed_propositions
        and (
            row.get("workflow_status") == "awaiting_review"
            or str(row.get("proposition_id")) in evidence_propositions
        )
    ]
    collecting = [
        {"id": row.get("proposition_id"), "task_id": row.get("task_id"), "label": str(row.get("title") or "正在收集证据")}
        for row in propositions
        if row.get("workflow_status") == "collecting"
        and str(row.get("proposition_id")) not in evidence_propositions
    ]
    items_by_kind = {
        "invalidated_dependency": invalidated,
        "audit_failure": audit_failures,
        "needs_rereview": rereview,
        "awaiting_first_review": awaiting,
        "collecting_evidence": collecting,
    }
    return [
        {"kind": kind, "label": label, "count": len(items_by_kind[kind]), "items": items_by_kind[kind]}
        for kind, label in RISK_KINDS
    ]


def build_mode_validation_projection(
    database_path: Path,
    trading_state: dict[str, Any],
    include_local_failures: bool = False,
) -> dict[str, Any]:
    """Join local validation state into a sanitized projection safe for static publication."""

    modes = [row for row in trading_state.get("modes", []) if isinstance(row, dict)]
    current_modes = {
        (str(row.get("id") or ""), str(row.get("version") or "")): row
        for row in modes
    }
    database = Path(database_path)
    rows = ModeValidationStore(database).snapshot_rows() if database.is_file() else _empty_rows()
    tasks = _project_tasks(rows["tasks"], current_modes)
    active_by_mode = {
        (row["mode_id"], row["mode_version"]): row["task_id"]
        for row in tasks
        if row["status"] == "active"
    }
    projected_modes = [
        {
            "id": row.get("id"),
            "name": row.get("name"),
            "version": row.get("version"),
            "status": row.get("status"),
            "active_task_id": active_by_mode.get((str(row.get("id") or ""), str(row.get("version") or ""))),
        }
        for row in modes
    ]
    propositions = _project_propositions(rows["propositions"])
    evidence = _project_evidence(rows["evidence"], rows["audits"])
    reviews = _project_reviews(rows["reviews"])
    projection = {
        "surface": "local" if include_local_failures else "read_only",
        "modes": projected_modes,
        "tasks": tasks,
        "risk_queue": _risk_queue(rows, propositions, evidence, reviews),
        "propositions": propositions,
        "evidence": evidence,
        "runs": _project_runs(rows["runs"]),
        "candidates": _project_candidates(rows["candidates"]),
        "reviews": reviews,
        "validators": validator_catalog(),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if include_local_failures:
        projection["local_audit_failures"] = [
            {
                "audit_id": row.get("audit_id"),
                "evidence_id": row.get("evidence_id"),
                "reasons": _json(row.get("reasons_json"), []),
                "audited_at": row.get("audited_at"),
            }
            for row in rows["audits"]
            if row.get("outcome") == "fail"
        ]
    return projection
