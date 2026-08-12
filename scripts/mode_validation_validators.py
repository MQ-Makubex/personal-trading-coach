#!/usr/bin/env python3
"""Allowlisted validators for the personal mode-validation workbench."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from ledger_analytics import broker_like_cycles, display_names_by_code, load_cash_adjustments, load_trades
from mode_validation_state import ModeValidationError, canonical_json, content_hash


SHANGHAI = timezone(timedelta(hours=8))
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UPDATE_HEADING = re.compile(r"^##\s+(?:Update\s*-\s*)?(20\d{2}-\d{2}-\d{2})\s*$", re.IGNORECASE)
EVENT_HEADING = re.compile(r"^###\s+(.+?)\s*$")


@dataclass(frozen=True)
class ValidatorSpec:
    validator_id: str
    name: str
    version: str
    run_kinds: tuple[str, ...]
    fields: tuple[str, ...]


VALIDATORS = {
    "historical-cycle-replay": ValidatorSpec(
        validator_id="historical-cycle-replay",
        name="历史交易周期回放",
        version="1",
        run_kinds=("exploratory", "formal"),
        fields=("date_from", "date_to", "inclusion_rules", "exclusion_rules", "control_definition"),
    ),
    "forward-decision-observation": ValidatorSpec(
        validator_id="forward-decision-observation",
        name="前向决策观察",
        version="1",
        run_kinds=("formal",),
        fields=(
            "window_start",
            "window_end",
            "event_timing",
            "qualification_deadline",
            "inclusion_rules",
            "exclusion_rules",
        ),
    ),
}


def validator_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": spec.validator_id,
            "name": spec.name,
            "version": spec.version,
            "run_kinds": list(spec.run_kinds),
            "parameter_fields": list(spec.fields),
            "enabled": True,
        }
        for spec in (VALIDATORS["historical-cycle-replay"], VALIDATORS["forward-decision-observation"])
    ]


def _validate_date(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        raise ModeValidationError(field)
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ModeValidationError(field) from exc


def _validate_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ModeValidationError(field)
    return [item.strip() for item in value]


def _validate_deadline(value: Any, event_timing: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"anchor", "lead_minutes"}:
        raise ModeValidationError("qualification_deadline")
    expected_anchor = "next_open" if event_timing == "after_close" else "same_close"
    if value.get("anchor") != expected_anchor:
        raise ModeValidationError("qualification_deadline.anchor")
    lead_minutes = value.get("lead_minutes")
    if type(lead_minutes) is not int or lead_minutes < 0 or lead_minutes > 720:
        raise ModeValidationError("qualification_deadline.lead_minutes")
    return {"anchor": expected_anchor, "lead_minutes": lead_minutes}


def validate_validator_request(validator_id: str, parameters: dict[str, Any], run_kind: str) -> dict[str, Any]:
    spec = VALIDATORS.get(validator_id)
    if spec is None:
        raise ModeValidationError("validator_id")
    if run_kind not in spec.run_kinds:
        raise ModeValidationError("run_kind")
    if not isinstance(parameters, dict):
        raise ModeValidationError("parameters")
    extra = set(parameters) - set(spec.fields)
    if extra:
        raise ModeValidationError("unexpected_parameter:%s" % sorted(extra)[0])
    missing = set(spec.fields) - set(parameters)
    if missing:
        raise ModeValidationError("missing_parameter:%s" % sorted(missing)[0])

    if validator_id == "historical-cycle-replay":
        normalized = {
            "date_from": _validate_date(parameters["date_from"], "date_from"),
            "date_to": _validate_date(parameters["date_to"], "date_to"),
            "inclusion_rules": _validate_string_list(parameters["inclusion_rules"], "inclusion_rules"),
            "exclusion_rules": _validate_string_list(parameters["exclusion_rules"], "exclusion_rules"),
            "control_definition": str(parameters["control_definition"]).strip(),
        }
        if not normalized["control_definition"] or normalized["date_from"] > normalized["date_to"]:
            raise ModeValidationError("control_definition" if not normalized["control_definition"] else "date_range")
        return normalized

    event_timing = parameters.get("event_timing")
    if event_timing not in {"after_close", "intraday"}:
        raise ModeValidationError("event_timing")
    normalized = {
        "window_start": _validate_date(parameters["window_start"], "window_start"),
        "window_end": _validate_date(parameters["window_end"], "window_end"),
        "event_timing": event_timing,
        "qualification_deadline": _validate_deadline(parameters["qualification_deadline"], event_timing),
        "inclusion_rules": _validate_string_list(parameters["inclusion_rules"], "inclusion_rules"),
        "exclusion_rules": _validate_string_list(parameters["exclusion_rules"], "exclusion_rules"),
    }
    if normalized["window_start"] > normalized["window_end"]:
        raise ModeValidationError("window_range")
    return normalized


def validate_forward_protocol_change(
    existing: dict[str, Any], proposed: dict[str, Any], candidate_count: int
) -> None:
    if candidate_count <= 0:
        return
    current = _validate_deadline(existing.get("qualification_deadline"), str(existing.get("event_timing")))
    replacement = _validate_deadline(proposed.get("qualification_deadline"), str(proposed.get("event_timing")))
    if current["anchor"] != replacement["anchor"]:
        raise ModeValidationError("deadline_extension")
    if replacement["lead_minutes"] < current["lead_minutes"]:
        raise ModeValidationError("deadline_extension")


def _closed_cycles(ledger_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(str(ledger_path)) as connection:
        connection.row_factory = sqlite3.Row
        trades = load_trades(connection)
        adjustments = load_cash_adjustments(connection)
    names = display_names_by_code(trades, adjustments)
    return [cycle for cycle in broker_like_cycles(trades, names, adjustments) if cycle.get("status") == "closed"]


def preview_historical_cycles(
    ledger_path: Path, mode: dict[str, Any], protocol: dict[str, Any]
) -> list[dict[str, Any]]:
    date_from = _validate_date(protocol.get("date_from"), "date_from")
    date_to = _validate_date(protocol.get("date_to"), "date_to")
    if date_from > date_to:
        raise ModeValidationError("date_range")
    existing = {
        str(sample.get("cycle_id"))
        for sample in mode.get("samples", [])
        if isinstance(sample, dict) and sample.get("cycle_id")
    }
    candidates = []
    for cycle in _closed_cycles(Path(ledger_path)):
        observed_at = str(cycle.get("first_buy_date") or "")
        if not (date_from <= observed_at <= date_to):
            continue
        cycle_id = str(cycle.get("cycle_id") or "")
        candidates.append(
            {
                "source_ref": "ledger-cycle:%s" % cycle_id,
                "observed_at": "%sT%s+08:00"
                % (observed_at, str(cycle.get("first_buy_time") or "00:00:00")),
                "masked_context": {
                    "cycle_id": cycle_id,
                    "stock_code": str(cycle.get("stock_code") or ""),
                    "stock_name": str(cycle.get("stock_name") or ""),
                    "first_action_date": observed_at,
                    "first_action_time": str(cycle.get("first_buy_time") or ""),
                    "independent_segment": cycle_id not in existing,
                },
                "qualification_deadline": None,
            }
        )
    return candidates


def historical_cycle_outcomes(ledger_path: Path) -> dict[str, dict[str, Any]]:
    """Return execution-only outcomes keyed by the opaque candidate source reference."""

    outcomes = {}
    for cycle in _closed_cycles(Path(ledger_path)):
        cycle_id = str(cycle.get("cycle_id") or "")
        outcomes["ledger-cycle:%s" % cycle_id] = {
            "realized_pnl_after_fees": cycle.get("realized_pnl_after_fees"),
            "return_pct": cycle.get("return_pct"),
            "holding_days": cycle.get("holding_days"),
            "close_date": cycle.get("close_date"),
        }
    return outcomes


def qualification_deadline(observed_date: str, event_timing: str, lead_minutes: int = 0) -> str:
    event_date = date.fromisoformat(_validate_date(observed_date, "observed_date"))
    if type(lead_minutes) is not int or lead_minutes < 0:
        raise ModeValidationError("lead_minutes")
    if event_timing == "intraday":
        anchor = datetime.combine(event_date, time(15, 0), tzinfo=SHANGHAI)
    elif event_timing == "after_close":
        next_day = event_date + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        anchor = datetime.combine(next_day, time(9, 30), tzinfo=SHANGHAI)
    else:
        raise ModeValidationError("event_timing")
    return (anchor - timedelta(minutes=lead_minutes)).isoformat(timespec="seconds")


def _confirmed_local_date(value: str) -> date:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ModeValidationError("confirmed_at") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(SHANGHAI).date()


def preview_forward_events(
    decision_events_path: Path, confirmed_at: str, protocol: dict[str, Any]
) -> list[dict[str, Any]]:
    window_start = date.fromisoformat(_validate_date(protocol.get("window_start"), "window_start"))
    window_end = date.fromisoformat(_validate_date(protocol.get("window_end"), "window_end"))
    confirmed_date = _confirmed_local_date(confirmed_at)
    event_timing = str(protocol.get("event_timing"))
    if event_timing not in {"after_close", "intraday"}:
        raise ModeValidationError("event_timing")
    deadline_spec = protocol.get("qualification_deadline") or {
        "anchor": "next_open" if event_timing == "after_close" else "same_close",
        "lead_minutes": 0,
    }
    deadline = _validate_deadline(deadline_spec, event_timing)

    current_date: date | None = None
    candidates = []
    lines = Path(decision_events_path).read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        update = UPDATE_HEADING.match(line.strip())
        if update:
            current_date = date.fromisoformat(update.group(1))
            continue
        event = EVENT_HEADING.match(line.strip())
        if not event or current_date is None:
            continue
        if current_date < confirmed_date or current_date < window_start or current_date > window_end:
            continue
        title = event.group(1).strip()
        observed_time = "15:00:00" if event_timing == "after_close" else "12:00:00"
        candidates.append(
            {
                "source_ref": "state/decision_events.md#L%d" % line_number,
                "observed_at": "%sT%s+08:00" % (current_date.isoformat(), observed_time),
                "masked_context": {
                    "event_date": current_date.isoformat(),
                    "title": title,
                    "event_timing": event_timing,
                    "independent_segment": current_date > confirmed_date,
                },
                "qualification_deadline": qualification_deadline(
                    current_date.isoformat(), event_timing, deadline["lead_minutes"]
                ),
            }
        )
    return candidates


def _safe_segment(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", value) or value in {".", ".."}:
        raise ModeValidationError(field)
    return value


def _write_json_new(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        handle.write("\n")


def write_run_artifacts(
    reports_root: Path,
    mode_id: str,
    mode_version: str,
    run_id: str,
    run_card: dict[str, Any],
    candidate_manifest: dict[str, Any],
    result: dict[str, Any],
    audit: dict[str, Any],
) -> dict[str, Any]:
    directory = (
        Path(reports_root)
        / _safe_segment(mode_id, "mode_id")
        / _safe_segment(mode_version, "mode_version")
        / _safe_segment(run_id, "run_id")
    )
    directory.mkdir(parents=True, exist_ok=False)
    values = {
        "run_card.json": run_card,
        "candidate_manifest.json": candidate_manifest,
        "result.json": result,
        "publication_audit.json": audit,
    }
    files = []
    hashes = {}
    for name, value in values.items():
        path = directory / name
        _write_json_new(path, value)
        files.append(path)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "directory": directory,
        "files": files,
        "file_hashes": hashes,
        "artifact_hash": content_hash(hashes),
    }
