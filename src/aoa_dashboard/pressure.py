"""Structured P-infinity pressure intake for the dashboard read model."""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from .cursor import (
    KNOWN_ACCESS_SCOPES,
    KNOWN_CURRENTNESS,
    content_digest,
)


PRESSURE_RECORD_SCHEMA_VERSION = "aoa_dashboard_pressure_record_v1"
PRESSURE_INBOX_SCHEMA_VERSION = "aoa_dashboard_pressure_inbox_v1"
KNOWN_TRIGGER_STRENGTHS = frozenset({"notice", "required_branch", "master_decision", "preauthorized_reflex"})
KNOWN_PRESSURE_AUTHORITIES = frozenset({"dashboard_derived", "source_owner", "master_decision"})
KNOWN_INDEPENDENCE_STATES = frozenset({"present", "absent", "unknown", "not_attested"})
KNOWN_SURFACE_RESULTS = frozenset({"fit", "no_fit", "partial", "reused", "unknown"})
KNOWN_OUTCOMES = frozenset(
    {"unresolved", "absorbed", "new_branch", "new_required_obligation", "stronger_owner", "residual", "deferred", "invalid"}
)

PRESSURE_CLAIM_LIMIT = (
    "Pressure Inbox is a dashboard-owned routing read model. It records evidence and a bounded next route; "
    "it does not form actors, grant authority, execute actions, issue proof, or accept work."
)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown(value: Any) -> bool:
    return not _non_empty(value) or str(value).strip().lower() in {"unknown", "unresolved", "unspecified", "missing"}


def _sha256(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _pressure_ref_errors(value: Any, prefix: str = "pressure_ref") -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{prefix} is missing or not an object"]
    for field in ("id", "kind", "ref"):
        if not _non_empty(value.get(field)):
            errors.append(f"{prefix}.{field} is missing")
    if not _sha256(value.get("sha256")):
        errors.append(f"{prefix}.sha256 is malformed")
    if value.get("currentness") not in KNOWN_CURRENTNESS:
        errors.append(f"{prefix}.currentness is missing or unknown")
    if value.get("access_scope") not in KNOWN_ACCESS_SCOPES:
        errors.append(f"{prefix}.access_scope is unknown")
    if value.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
        errors.append(f"{prefix}.authority is unknown")
    return errors


def validate_pressure_record(record: Any, *, expected_goal_id: str | None = None) -> list[str]:
    """Validate without defaulting missing owner/evidence/authority fields."""

    errors: list[str] = []
    if not isinstance(record, dict):
        return ["pressure record is not an object"]
    if record.get("schema_version") != PRESSURE_RECORD_SCHEMA_VERSION:
        errors.append("pressure record schema_version is unsupported")
    if expected_goal_id is not None and record.get("goal_id") != expected_goal_id:
        errors.append("pressure record goal_id mismatch")
    errors.extend(_pressure_ref_errors(record.get("pressure_ref")))

    evidence = record.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("pressure evidence is missing")
    else:
        for index, item in enumerate(evidence):
            prefix = f"evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} is not an object")
                continue
            for field in ("ref", "owner", "kind", "currentness", "authority", "claim_limit"):
                if not _non_empty(item.get(field)):
                    errors.append(f"{prefix}.{field} is missing")
            if item.get("currentness") not in KNOWN_CURRENTNESS:
                errors.append(f"{prefix}.currentness is unknown")
            if item.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
                errors.append(f"{prefix}.authority is unknown")
            if not _sha256(item.get("sha256")):
                errors.append(f"{prefix}.sha256 is malformed")
            if item.get("access_scope") is not None and item.get("access_scope") not in KNOWN_ACCESS_SCOPES:
                errors.append(f"{prefix}.access_scope is unknown")

    if not _non_empty(record.get("affected_goal_criterion")):
        errors.append("affected_goal_criterion is missing")
    if not _non_empty(record.get("consequence_of_omission")):
        errors.append("consequence_of_omission is missing")

    owner = record.get("natural_owner")
    if not isinstance(owner, dict):
        errors.append("natural_owner is missing")
    else:
        for field in ("owner", "owner_ref", "authority", "access_scope"):
            if not _non_empty(owner.get(field)):
                errors.append(f"natural_owner.{field} is missing")
        if _unknown(owner.get("owner")):
            errors.append("natural_owner.owner is unknown")
        if owner.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
            errors.append("natural_owner.authority is unknown")
        if owner.get("access_scope") not in KNOWN_ACCESS_SCOPES:
            errors.append("natural_owner.access_scope is unknown")

    surfaces = record.get("checked_existing_surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append("checked_existing_surfaces is missing")
    else:
        for index, item in enumerate(surfaces):
            prefix = f"checked_existing_surfaces[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} is not an object")
                continue
            for field in ("surface", "owner", "result", "ref", "claim_limit"):
                if not _non_empty(item.get(field)):
                    errors.append(f"{prefix}.{field} is missing")
            if item.get("result") not in KNOWN_SURFACE_RESULTS:
                errors.append(f"{prefix}.result is unknown")

    independence = record.get("independence_signals")
    if not isinstance(independence, dict):
        errors.append("independence_signals is missing")
    else:
        if independence.get("status") not in KNOWN_INDEPENDENCE_STATES:
            errors.append("independence_signals.status is unknown")
        if not isinstance(independence.get("signals"), list):
            errors.append("independence_signals.signals is missing")
        if not _non_empty(independence.get("claim_limit")):
            errors.append("independence_signals.claim_limit is missing")

    if record.get("recommended_trigger_strength") not in KNOWN_TRIGGER_STRENGTHS:
        errors.append("recommended_trigger_strength is missing or unknown")
    if not _non_empty(record.get("stop_line")) or _unknown(record.get("stop_line")):
        errors.append("stop_line is missing")
    if not _non_empty(record.get("wake_condition")) or _unknown(record.get("wake_condition")):
        errors.append("wake_condition is missing")

    route = record.get("next_route")
    if not isinstance(route, dict):
        errors.append("next_route is missing")
    else:
        for field in ("owner", "owner_ref", "route", "reason", "authority", "access_scope", "effect", "claim_limit"):
            if not _non_empty(route.get(field)):
                errors.append(f"next_route.{field} is missing")
        if _unknown(route.get("owner")) or _unknown(route.get("route")):
            errors.append("next_route owner/route is unknown")
        if route.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
            errors.append("next_route.authority is unknown")
        if route.get("access_scope") not in KNOWN_ACCESS_SCOPES:
            errors.append("next_route.access_scope is unknown")
        if route.get("effect") != "none":
            errors.append("next_route.effect must be none")
        if not isinstance(route.get("critical"), bool):
            errors.append("next_route.critical is missing")

    outcome = record.get("outcome")
    if not isinstance(outcome, dict):
        errors.append("outcome is missing")
    else:
        if outcome.get("state") not in KNOWN_OUTCOMES:
            errors.append("outcome.state is unknown")
        if not _non_empty(outcome.get("claim_limit")):
            errors.append("outcome.claim_limit is missing")

    if not _non_empty(record.get("claim_limit")):
        errors.append("pressure record claim_limit is missing")
    return errors


def pressure_digest(record: dict[str, Any]) -> str:
    value = copy.deepcopy(record)
    value.pop("record_digest", None)
    return content_digest(value)


def _legacy_ref(correlation_source: dict[str, Any]) -> dict[str, Any]:
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    master_filter = metadata.get("master_filter") if isinstance(metadata.get("master_filter"), dict) else {}
    raw_ref = master_filter.get("ref") if isinstance(master_filter.get("ref"), dict) else {}
    return {
        "id": "legacy:master-filter:pressure",
        "kind": "legacy_master_filter_pressure",
        "ref": raw_ref.get("ref") or "master-filter:unresolved",
        "sha256": raw_ref.get("sha256"),
        "currentness": raw_ref.get("freshness") or "unknown",
        "access_scope": "owner_bounded",
        "authority": "dashboard_derived",
    }


def migrate_legacy_pressure_candidates(
    config: dict[str, Any],
    correlation_source: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expose old master-filter obligation strings as explicitly incomplete candidates."""

    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    obligations = metadata.get("new_obligations") if isinstance(metadata.get("new_obligations"), list) else []
    candidates: list[dict[str, Any]] = []
    for index, obligation in enumerate(item for item in obligations if isinstance(item, str) and item.strip()):
        pressure_ref = _legacy_ref(correlation_source)
        pressure_ref["id"] = f"legacy:master-filter:pressure:{index}:{content_digest(obligation)[:12]}"
        candidates.append(
            {
                "pressure_ref": pressure_ref,
                "legacy_obligation": obligation,
                "missing_fields": [
                    "affected_goal_criterion",
                    "consequence_of_omission",
                    "natural_owner",
                    "checked_existing_surfaces",
                    "independence_signals",
                    "recommended_trigger_strength",
                    "stop_line",
                    "wake_condition",
                    "next_route",
                    "outcome",
                ],
                "outcome": "deferred",
                "migration": "legacy_master_filter_requires_structured_pressure_fields",
                "claim_limit": "Legacy obligation text is retained as a candidate only; missing routing fields fail closed.",
            }
        )
    return candidates


def _redacted_invalid(record: Any, errors: list[str], *, migration: str | None = None) -> dict[str, Any]:
    pressure_ref = record.get("pressure_ref") if isinstance(record, dict) else None
    result: dict[str, Any] = {
        "pressure_ref": pressure_ref if isinstance(pressure_ref, dict) else {"id": "unresolved"},
        "errors": errors,
        "outcome": "invalid",
        "claim_limit": "Malformed pressure is retained as an invalid input and is not routed or acted upon.",
    }
    if migration:
        result["migration"] = migration
    return result


def build_pressure_inbox(
    *,
    goal_id: str,
    records: list[dict[str, Any]] | None,
    legacy_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, non-executing Pressure Inbox."""

    errors: list[str] = []
    valid: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []
    if not isinstance(records, list):
        records = []
        errors.append("pressure_inbox records is not a list")
    for index, record in enumerate(records):
        item_errors = validate_pressure_record(record, expected_goal_id=goal_id)
        if item_errors:
            invalid_records.append(_redacted_invalid(record, item_errors))
            continue
        item = copy.deepcopy(record)
        item["record_digest"] = pressure_digest(item)
        valid.append(item)

    by_ref: dict[str, list[dict[str, Any]]] = {}
    for item in valid:
        by_ref.setdefault(item["pressure_ref"]["id"], []).append(item)
    retained: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for pressure_ref, values in sorted(by_ref.items()):
        if len(values) == 1:
            retained.append(values[0])
            continue
        digests = {item["record_digest"] for item in values}
        retained.extend(sorted(values, key=lambda item: item["record_digest"]))
        if len(digests) == 1:
            duplicates.append(
                {
                    "pressure_ref": pressure_ref,
                    "record_digest": next(iter(digests)),
                    "duplicate_count": len(values) - 1,
                    "winner": None,
                    "claim_limit": "Exact duplicate pressure observations are retained as one read-model item with no authority change.",
                }
            )
            retained = retained[: -len(values)] + [values[0]]
        else:
            conflicts.append(
                {
                    "pressure_ref": pressure_ref,
                    "record_digests": sorted(digests),
                    "record_count": len(values),
                    "resolution": "unresolved",
                    "winner": None,
                    "claim_limit": "Conflicting pressure records remain visible; dashboard does not select the natural owner or route winner.",
                }
            )

    legacy = []
    for candidate in legacy_candidates or []:
        if not isinstance(candidate, dict):
            legacy.append(_redacted_invalid(candidate, ["legacy candidate is not an object"], migration="legacy_master_filter"))
            continue
        legacy.append(
            {
                "pressure_ref": candidate.get("pressure_ref", {"id": "unresolved"}),
                "legacy_obligation": candidate.get("legacy_obligation"),
                "missing_fields": candidate.get("missing_fields", []),
                "outcome": "deferred",
                "migration": candidate.get("migration", "legacy_master_filter"),
                "claim_limit": candidate.get("claim_limit", PRESSURE_CLAIM_LIMIT),
            }
        )

    if errors or invalid_records:
        status = "invalid"
    elif conflicts:
        status = "conflicted"
    elif legacy:
        status = "deferred"
    elif retained:
        status = "current"
    else:
        status = "missing"

    retained.sort(key=lambda item: item["pressure_ref"]["id"])
    critical_routes = [
        {
            "pressure_ref": item["pressure_ref"],
            "next_route": item["next_route"],
            "outcome": item["outcome"],
            "claim_limit": PRESSURE_CLAIM_LIMIT,
        }
        for item in retained
        if isinstance(item.get("next_route"), dict) and item["next_route"].get("critical") is True
    ]
    outcome_counts = Counter(
        item.get("outcome", {}).get("state", "unknown")
        for item in retained
        if isinstance(item.get("outcome"), dict)
    )
    model: dict[str, Any] = {
        "schema_version": PRESSURE_INBOX_SCHEMA_VERSION,
        "goal_id": goal_id,
        "status": status,
        "items": retained,
        "critical_next_routes": critical_routes,
        "conflicts": conflicts,
        "duplicates": duplicates,
        "invalid_records": invalid_records,
        "legacy_candidates": legacy,
        "outcomes": dict(sorted(outcome_counts.items())),
        "access_policy": {
            "visibility": "loopback_only",
            "redaction": "metadata_only",
            "unknown_access": "fail_closed",
            "authority": "read_only",
            "claim_limit": "Access visibility and action authority are not inferred from a route string.",
        },
        "retention": {
            "provenance_preserved": True,
            "winner_selection": "none",
            "conflict_count": len(conflicts),
            "duplicate_count": len(duplicates),
            "claim_limit": PRESSURE_CLAIM_LIMIT,
        },
        "errors": errors,
        "claim_limit": PRESSURE_CLAIM_LIMIT,
    }
    model["read_model_digest"] = content_digest(model)
    return model


validate_pressure = validate_pressure_record
build_pressure_read_model = build_pressure_inbox
