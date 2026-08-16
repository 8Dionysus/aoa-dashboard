"""Structured P-infinity pressure intake for the dashboard read model."""

from __future__ import annotations

import copy
from collections import Counter
from typing import Any

from .cursor import (
    KNOWN_ACCESS_SCOPES,
    KNOWN_CURRENTNESS,
    content_digest,
    redacted_legacy_obligation,
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

_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "goal_id",
        "pressure_ref",
        "evidence",
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
        "record_digest",
        "claim_limit",
    }
)
_TYPED_REF_FIELDS = frozenset(
    {
        "id",
        "ref",
        "owner",
        "kind",
        "sha256",
        "currentness",
        "access_scope",
        "authority",
        "claim_limit",
        "observed_at",
    }
)
_SURFACE_FIELDS = frozenset({"surface", "owner", "result", "ref", "access_scope", "authority", "claim_limit", "observed_at"})


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


def _typed_ref_errors(value: Any, prefix: str, *, require_id: bool) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{prefix} is missing or not an object"]
    for field in sorted(set(value) - _TYPED_REF_FIELDS):
        errors.append(f"{prefix}.{field} is not an admitted metadata field")
    required = ("id", "ref", "owner", "kind", "currentness", "access_scope", "authority", "claim_limit")
    if not require_id:
        required = tuple(field for field in required if field != "id")
    for field in required:
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
    if "observed_at" in value and value["observed_at"] is not None and not isinstance(value["observed_at"], str):
        errors.append(f"{prefix}.observed_at is malformed")
    return errors


def _pressure_ref_errors(value: Any, prefix: str = "pressure_ref") -> list[str]:
    return _typed_ref_errors(value, prefix, require_id=True)


def validate_pressure_record(record: Any, *, expected_goal_id: str | None = None) -> list[str]:
    """Validate without defaulting missing owner/evidence/authority fields."""

    errors: list[str] = []
    if not isinstance(record, dict):
        return ["pressure record is not an object"]
    for field in sorted(set(record) - _RECORD_FIELDS):
        errors.append(f"pressure record.{field} is not an admitted metadata field")
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
            errors.extend(_typed_ref_errors(item, f"evidence[{index}]", require_id=False))

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
            for field in sorted(set(item) - _SURFACE_FIELDS):
                errors.append(f"{prefix}.{field} is not an admitted metadata field")
            for field in ("surface", "owner", "result", "ref", "access_scope", "authority", "claim_limit"):
                if not _non_empty(item.get(field)):
                    errors.append(f"{prefix}.{field} is missing")
            if item.get("result") not in KNOWN_SURFACE_RESULTS:
                errors.append(f"{prefix}.result is unknown")
            if item.get("access_scope") not in KNOWN_ACCESS_SCOPES:
                errors.append(f"{prefix}.access_scope is unknown")
            if item.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
                errors.append(f"{prefix}.authority is unknown")

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


def _stable_pressure(value: Any, *, typed_ref: bool = False) -> Any:
    """Remove only declared read-time timestamps from typed pressure refs."""

    if isinstance(value, dict):
        is_typed_ref = typed_ref or {"ref", "kind", "currentness", "claim_limit"}.issubset(value)
        return {
            key: _stable_pressure(item, typed_ref=is_typed_ref)
            for key, item in sorted(value.items())
            if not (is_typed_ref and key == "observed_at")
        }
    if isinstance(value, list):
        return [_stable_pressure(item) for item in value]
    return value


def pressure_digest(record: dict[str, Any]) -> str:
    value = copy.deepcopy(record)
    value.pop("record_digest", None)
    return content_digest(_stable_pressure(value))


def _legacy_ref(correlation_source: dict[str, Any]) -> tuple[dict[str, Any], list[str], str | None]:
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    master_filter = metadata.get("master_filter") if isinstance(metadata.get("master_filter"), dict) else {}
    raw_ref = master_filter.get("ref") if isinstance(master_filter.get("ref"), dict) else {}
    currentness = raw_ref.get("currentness") or raw_ref.get("freshness") or "unknown"
    pressure_ref = {
        "id": "legacy:master-filter:pressure",
        "kind": raw_ref.get("kind") or "legacy_master_filter_pressure",
        "ref": raw_ref.get("ref") or "master-filter:unresolved",
        "sha256": raw_ref.get("sha256"),
        "currentness": currentness,
        "owner": raw_ref.get("owner") or "unknown",
        "access_scope": raw_ref.get("access_scope") or "unknown",
        "authority": raw_ref.get("authority") or "unknown",
        "claim_limit": raw_ref.get("claim_limit") or "Legacy source claim limit is unavailable.",
    }
    if "observed_at" in raw_ref:
        pressure_ref["observed_at"] = raw_ref["observed_at"]
    required = ("ref", "sha256", "owner", "authority", "currentness", "access_scope", "claim_limit")
    missing = [field for field in required if field not in raw_ref or raw_ref.get(field) in (None, "")]
    legacy_freshness = raw_ref.get("freshness") if "freshness" in raw_ref else None
    return pressure_ref, missing, legacy_freshness


def migrate_legacy_pressure_candidates(
    config: dict[str, Any],
    correlation_source: dict[str, Any],
) -> list[dict[str, Any]]:
    """Expose old master-filter obligation strings as redacted, incomplete candidates."""

    del config
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    obligations = metadata.get("new_obligations") if isinstance(metadata.get("new_obligations"), list) else []
    candidates: list[dict[str, Any]] = []
    for index, obligation in enumerate(item for item in obligations if isinstance(item, str) and item.strip()):
        pressure_ref, source_missing, legacy_freshness = _legacy_ref(correlation_source)
        redacted = redacted_legacy_obligation(obligation)
        digest = redacted["sha256"]
        pressure_ref["id"] = f"legacy:master-filter:pressure:{index}:{digest[:12]}"
        candidate: dict[str, Any] = {
            "pressure_ref": pressure_ref,
            "source_evidence_ref": copy.deepcopy(pressure_ref),
            "legacy_obligation_digest": digest,
            "legacy_obligation_redacted": redacted["redacted"],
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
            "source_missing_fields": source_missing,
            "outcome": "deferred",
            "migration": "legacy_master_filter_requires_structured_pressure_fields",
            "claim_limit": "Legacy source text is redacted and retained as a deferred candidate only; missing routing fields fail closed.",
        }
        if legacy_freshness is not None:
            candidate["legacy_freshness"] = legacy_freshness
        candidates.append(candidate)
    return candidates


def _safe_ref_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"id": "unresolved"}
    return {key: copy.deepcopy(value[key]) for key in sorted(set(value) & _TYPED_REF_FIELDS) if isinstance(value[key], (str, type(None)))}


def _redacted_invalid(record: Any, errors: list[str], *, migration: str | None = None) -> dict[str, Any]:
    pressure_ref = record.get("pressure_ref") if isinstance(record, dict) else None
    result: dict[str, Any] = {
        "pressure_ref": _safe_ref_summary(pressure_ref),
        "errors": errors,
        "outcome": "invalid",
        "claim_limit": "Malformed pressure is retained as an invalid input and is not routed or acted upon.",
    }
    if migration:
        result["migration"] = migration
    return result


def _legacy_projection(candidate: dict[str, Any]) -> dict[str, Any]:
    raw_obligation = candidate.get("legacy_obligation")
    digest = candidate.get("legacy_obligation_digest")
    if not _sha256(digest):
        digest = redacted_legacy_obligation(raw_obligation)["sha256"]
    redacted = f"[redacted legacy obligation; sha256={digest}]" if digest else "[redacted legacy obligation; digest unavailable]"
    result: dict[str, Any] = {
        "pressure_ref": _safe_ref_summary(candidate.get("pressure_ref")),
        "source_evidence_ref": _safe_ref_summary(candidate.get("source_evidence_ref") or candidate.get("pressure_ref")),
        "legacy_obligation_digest": digest,
        "legacy_obligation_redacted": redacted,
        "missing_fields": [item for item in candidate.get("missing_fields", []) if isinstance(item, str)],
        "source_missing_fields": [item for item in candidate.get("source_missing_fields", []) if isinstance(item, str)],
        "outcome": "deferred",
        "migration": candidate.get("migration", "legacy_master_filter"),
        "claim_limit": candidate.get("claim_limit", PRESSURE_CLAIM_LIMIT),
    }
    if isinstance(candidate.get("legacy_freshness"), str):
        result["legacy_freshness"] = candidate["legacy_freshness"]
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
    for record in records:
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
        legacy.append(_legacy_projection(candidate))

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
            "redaction": "legacy_text_digest_only",
            "raw_legacy_text": "never_emitted",
            "unknown_access": "fail_closed",
            "authority": "read_only",
            "claim_limit": "Access visibility and action authority are not inferred from a route string.",
        },
        "retention": {
            "provenance_preserved": True,
            "winner_selection": "none",
            "conflict_count": len(conflicts),
            "duplicate_count": len(duplicates),
            "legacy_raw_text": "not_retained",
            "claim_limit": PRESSURE_CLAIM_LIMIT,
        },
        "errors": errors,
        "claim_limit": PRESSURE_CLAIM_LIMIT,
    }
    model["read_model_digest"] = content_digest(_stable_pressure(model))
    return model


validate_pressure = validate_pressure_record
build_pressure_read_model = build_pressure_inbox
