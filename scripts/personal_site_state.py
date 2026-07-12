#!/usr/bin/env python3
"""Load validated private state used by the personal trading site."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GATE_STATUSES = {"pending", "locked", "observe", "eligible"}
MODE_STATUSES = {"validating", "review", "replicable", "avoid"}
EXECUTION_RESULTS = {"planned", "violated", "insufficient"}
EVIDENCE_DIRECTIONS = {"support", "oppose", "indeterminate"}
EVIDENCE_TYPES = {"formal", "historical_reference"}

MESSAGE_STATUSES = {"draft", "active", "archived"}
MESSAGE_LEVELS = {"red_card", "reminder"}
MESSAGE_SCOPES = {"global", "stock", "mode"}


class StateValidationError(ValueError):
    """Raised when private state does not match the supported schema."""


def default_trading_modes() -> dict[str, Any]:
    return {
        "version": 1,
        "coach_gate": {
            "status": "pending",
            "target_date": None,
            "reasons": [],
            "next_check": "",
            "source_path": "",
        },
        "mode_eligibility": [],
        "modes": [],
        "error": None,
    }


def default_discipline_feed() -> dict[str, Any]:
    return {"version": 1, "messages": [], "error": None}


def _is_project_relative(value: str) -> bool:
    candidate = Path(value)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _repair(default: dict[str, Any], reason: str) -> dict[str, Any]:
    result = deepcopy(default)
    result["error"] = f"状态数据待修复：{reason}"
    return result


def _require_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StateValidationError(field)
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise StateValidationError(field)
    return value


def _require_string(value: Any, field: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise StateValidationError(field)
    return value


def _require_string_list(value: Any, field: str) -> list[str]:
    items = _require_list(value, field)
    return [_require_string(item, field) for item in items]


def _require_enum(value: Any, field: str, allowed: set[str]) -> str:
    item = _require_string(value, field)
    if item not in allowed:
        raise StateValidationError(field)
    return item


def _require_relative_path(value: Any, field: str) -> str:
    path = _require_string(value, field, allow_empty=True)
    if not _is_project_relative(path):
        raise StateValidationError(field)
    return path


def _require_version(value: Any) -> int:
    if type(value) is not int or value != 1:
        raise StateValidationError("version")
    return value


def _parse_datetime(value: str, field: str, allow_empty: bool = False) -> datetime | None:
    if not value:
        if allow_empty:
            return None
        raise StateValidationError(field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StateValidationError(field) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _validate_gate(value: Any) -> dict[str, Any]:
    gate = _require_mapping(value, "coach_gate")
    target_date = gate.get("target_date")
    if target_date is not None:
        _require_string(target_date, "coach_gate.target_date")
    return {
        "status": _require_enum(gate.get("status"), "coach_gate.status", GATE_STATUSES),
        "target_date": target_date,
        "reasons": _require_string_list(gate.get("reasons"), "coach_gate.reasons"),
        "next_check": _require_string(gate.get("next_check"), "coach_gate.next_check", allow_empty=True),
        "source_path": _require_relative_path(gate.get("source_path"), "coach_gate.source_path"),
    }


def _validate_mode_eligibility(value: Any) -> list[dict[str, Any]]:
    entries = []
    for item in _require_list(value, "mode_eligibility"):
        eligibility = _require_mapping(item, "mode_eligibility")
        target_date = eligibility.get("target_date")
        if target_date is not None:
            _require_string(target_date, "mode_eligibility.target_date")
        entries.append(
            {
                "mode_id": _require_string(eligibility.get("mode_id"), "mode_eligibility.mode_id"),
                "status": _require_enum(eligibility.get("status"), "mode_eligibility.status", GATE_STATUSES),
                "target_date": target_date,
                "reasons": _require_string_list(eligibility.get("reasons"), "mode_eligibility.reasons"),
                "source_path": _require_relative_path(eligibility.get("source_path"), "mode_eligibility.source_path"),
            }
        )
    mode_ids = [entry["mode_id"] for entry in entries]
    if len(mode_ids) != len(set(mode_ids)):
        raise StateValidationError("mode_eligibility")
    return entries


def _validate_sample(value: Any, cycles_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sample = _require_mapping(value, "sample")
    source_paths = _require_string_list(sample.get("source_paths"), "sample.source_paths")
    if not all(_is_project_relative(path) for path in source_paths):
        raise StateValidationError("sample.source_paths")
    cycle_id = _require_string(sample.get("cycle_id"), "sample.cycle_id")
    cycle = cycles_by_id.get(cycle_id)
    cycle_found = isinstance(cycle, dict)
    return {
        "cycle_id": cycle_id,
        "evidence_type": _require_enum(sample.get("evidence_type"), "sample.evidence_type", EVIDENCE_TYPES),
        "execution_result": _require_enum(
            sample.get("execution_result"), "sample.execution_result", EXECUTION_RESULTS
        ),
        "evidence_direction": _require_enum(
            sample.get("evidence_direction"), "sample.evidence_direction", EVIDENCE_DIRECTIONS
        ),
        "note": _require_string(sample.get("note"), "sample.note"),
        "source_paths": source_paths,
        "cycle_found": cycle_found,
        "cycle": deepcopy(cycle) if cycle_found else None,
    }


def _validate_mode(value: Any, cycles_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    mode = _require_mapping(value, "mode")
    samples = [_validate_sample(sample, cycles_by_id) for sample in _require_list(mode.get("samples"), "mode.samples")]
    cycle_ids = [sample["cycle_id"] for sample in samples]
    if len(cycle_ids) != len(set(cycle_ids)):
        raise StateValidationError("mode.samples")

    valid_formal = [
        sample
        for sample in samples
        if sample["evidence_type"] == "formal"
        and sample["execution_result"] == "planned"
        and sample["evidence_direction"] in {"support", "oppose"}
        and sample["cycle_found"]
    ]
    return {
        "id": _require_string(mode.get("id"), "mode.id"),
        "name": _require_string(mode.get("name"), "mode.name"),
        "status": _require_enum(mode.get("status"), "mode.status", MODE_STATUSES),
        "version": _require_string(mode.get("version"), "mode.version"),
        "applicable_environment": _require_string_list(
            mode.get("applicable_environment"), "mode.applicable_environment"
        ),
        "trigger_conditions": _require_string_list(mode.get("trigger_conditions"), "mode.trigger_conditions"),
        "execution_boundaries": _require_string_list(mode.get("execution_boundaries"), "mode.execution_boundaries"),
        "invalidation_conditions": _require_string_list(
            mode.get("invalidation_conditions"), "mode.invalidation_conditions"
        ),
        "max_risk": _require_string(mode.get("max_risk"), "mode.max_risk"),
        "next_validation_requirement": _require_string(
            mode.get("next_validation_requirement"), "mode.next_validation_requirement"
        ),
        "samples": samples,
        "valid_formal_sample_count": len(valid_formal),
        "historical_reference_count": sum(sample["evidence_type"] == "historical_reference" for sample in samples),
        "review_ready": len(valid_formal) >= 3,
    }


def load_trading_modes(path: Path, cycles_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Load valid trading mode state without allowing it to stop site generation."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_trading_modes()
    except OSError:
        return _repair(default_trading_modes(), "读取失败")
    except (json.JSONDecodeError, TypeError, ValueError):
        return _repair(default_trading_modes(), "JSON 格式无效")

    try:
        payload = _require_mapping(raw, "root")
        cycle_index = cycles_by_id if isinstance(cycles_by_id, dict) else {}
        modes = [_validate_mode(mode, cycle_index) for mode in _require_list(payload.get("modes"), "modes")]
        mode_ids = [mode["id"] for mode in modes]
        if len(mode_ids) != len(set(mode_ids)):
            raise StateValidationError("modes")
        return {
            "version": _require_version(payload.get("version")),
            "coach_gate": _validate_gate(payload.get("coach_gate")),
            "mode_eligibility": _validate_mode_eligibility(payload.get("mode_eligibility")),
            "modes": modes,
            "error": None,
        }
    except (TypeError, ValueError):
        return _repair(default_trading_modes(), "字段格式无效")


def _validate_message(value: Any) -> tuple[dict[str, Any], datetime, datetime | None, datetime | None]:
    message = _require_mapping(value, "message")
    created_at_value = _require_string(message.get("created_at"), "message.created_at")
    created_at = _parse_datetime(created_at_value, "message.created_at")
    effective_at_value = _require_string(message.get("effective_at"), "message.effective_at", allow_empty=True)
    expires_at_value = _require_string(message.get("expires_at"), "message.expires_at", allow_empty=True)
    effective_at = _parse_datetime(effective_at_value, "message.effective_at", allow_empty=True)
    expires_at = _parse_datetime(expires_at_value, "message.expires_at", allow_empty=True)
    return (
        {
            "id": _require_string(message.get("id"), "message.id"),
            "status": _require_enum(message.get("status"), "message.status", MESSAGE_STATUSES),
            "level": _require_enum(message.get("level"), "message.level", MESSAGE_LEVELS),
            "scope": _require_enum(message.get("scope"), "message.scope", MESSAGE_SCOPES),
            "stock_code": _require_string(message.get("stock_code"), "message.stock_code", allow_empty=True),
            "mode_id": _require_string(message.get("mode_id"), "message.mode_id", allow_empty=True),
            "message": _require_string(message.get("message"), "message.message"),
            "source_path": _require_relative_path(message.get("source_path"), "message.source_path"),
            "effective_at": effective_at_value,
            "expires_at": expires_at_value,
            "created_at": created_at_value,
        },
        created_at,
        effective_at,
        expires_at,
    )


def load_discipline_feed(path: Path, now: datetime | None = None) -> dict[str, Any]:
    """Load active discipline messages without allowing invalid state to stop a build."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default_discipline_feed()
    except OSError:
        return _repair(default_discipline_feed(), "读取失败")
    except (json.JSONDecodeError, TypeError, ValueError):
        return _repair(default_discipline_feed(), "JSON 格式无效")

    try:
        payload = _require_mapping(raw, "root")
        _require_version(payload.get("version"))
        rows = [_validate_message(message) for message in _require_list(payload.get("messages"), "messages")]
        ids = [message[0]["id"] for message in rows]
        if len(ids) != len(set(ids)):
            raise StateValidationError("messages")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        active = [
            row
            for row in rows
            if row[0]["status"] == "active"
            and (row[2] is None or row[2] <= current)
            and (row[3] is None or current < row[3])
        ]
        active.sort(key=lambda row: (0 if row[0]["level"] == "red_card" else 1, -row[1].timestamp()))
        return {"version": 1, "messages": [row[0] for row in active], "error": None}
    except (TypeError, ValueError):
        return _repair(default_discipline_feed(), "字段格式无效")
