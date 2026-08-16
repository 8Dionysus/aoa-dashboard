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
from .source_binding import (
    MAX_DIAGNOSTIC_ITEMS,
    has_forbidden_key,
    is_known_owner,
    is_known_claim_policy,
    is_safe_diagnostic,
    is_sha256,
    safe_diagnostic,
    sanitize_diagnostic_list,
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
        "claim_policy",
        "claim_limit",
    }
)
_TYPED_REF_FIELDS = frozenset(
    {
        "id",
        "label",
        "ref",
        "owner",
        "kind",
        "sha256",
        "currentness",
        "freshness",
        "access_scope",
        "authority",
        "claim_policy",
        "expected_sha256",
        "snapshot_role",
        "missing_fields",
        "degradation",
        "claim_limit",
        "observed_at",
    }
)
_SURFACE_FIELDS = frozenset(
    {"surface", "owner", "result", "ref", "access_scope", "authority", "claim_policy", "claim_limit", "observed_at"}
)
_NATURAL_OWNER_FIELDS = frozenset({"owner", "owner_ref", "authority", "access_scope", "claim_policy"})
_INDEPENDENCE_FIELDS = frozenset({"status", "signals", "claim_policy", "claim_limit"})
_ROUTE_FIELDS = frozenset(
    {"owner", "owner_ref", "route", "reason", "critical", "authority", "access_scope", "effect", "claim_policy", "claim_limit"}
)
_OUTCOME_FIELDS = frozenset({"state", "owner", "claim_policy", "claim_limit"})
_FORBIDDEN_NESTED_KEY_PARTS = ("raw", "body", "private", "secret", "token", "password", "prompt")
_DIAGNOSTIC_LIST_FIELDS = frozenset({"degradation", "missing_fields", "signals", "errors", "source_missing_fields"})
_DIAGNOSTIC_SCALAR_FIELDS = frozenset({"snapshot_role"})


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _unknown(value: Any) -> bool:
    return not _non_empty(value) or str(value).strip().lower() in {"unknown", "unresolved", "unspecified", "missing"}


def _sha256(value: Any) -> bool:
    return value is None or is_sha256(value)


def _non_string_key_errors(value: Any, prefix: str = "pressure record") -> list[str]:
    """Reject malformed object keys before any sort/set/walk operation."""

    if isinstance(value, dict):
        errors: list[str] = []
        for key, item in value.items():
            if not isinstance(key, str):
                errors.append(f"{prefix} contains a non-string object key")
                continue
            errors.extend(_non_string_key_errors(item, f"{prefix}.{key}"))
        return errors
    if isinstance(value, list):
        errors = []
        for index, item in enumerate(value):
            errors.extend(_non_string_key_errors(item, f"{prefix}[{index}]"))
        return errors
    return []


def _safe_diagnostic_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [safe_diagnostic(item) for item in value[:MAX_DIAGNOSTIC_ITEMS]]


def _diagnostic_errors(value: Any, prefix: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{prefix} is malformed"]
    errors: list[str] = []
    if len(value) > MAX_DIAGNOSTIC_ITEMS:
        errors.append(f"{prefix} exceeds the bounded item count")
    for index, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"{prefix}[{index}] is not a string")
        elif not is_safe_diagnostic(item):
            errors.append(f"{prefix}[{index}] is not a bounded diagnostic code")
    return errors


def _sanitize_pressure_diagnostics(value: Any, *, field_name: str | None = None) -> Any:
    """Digest arbitrary diagnostic values before validation or retention."""

    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            return value
        return {
            key: _sanitize_pressure_diagnostics(item, field_name=key)
            for key, item in value.items()
        }
    if isinstance(value, list):
        if field_name in _DIAGNOSTIC_LIST_FIELDS:
            return sanitize_diagnostic_list(value)
        return [_sanitize_pressure_diagnostics(item, field_name=field_name) for item in value]
    if field_name in _DIAGNOSTIC_SCALAR_FIELDS and isinstance(value, str):
        return safe_diagnostic(value)
    return value


def _object_field_errors(value: Any, prefix: str, allowed: frozenset[str]) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix} is missing or not an object"]
    if any(not isinstance(field, str) for field in value):
        return [f"{prefix} contains a non-string object key"]
    errors: list[str] = []
    for field in sorted(value):
        if has_forbidden_key(field, _FORBIDDEN_NESTED_KEY_PARTS):
            errors.append(f"{prefix}.{field} is forbidden")
        elif field not in allowed:
            errors.append(f"{prefix}.{field} is not an admitted metadata field")
    return errors


def _typed_ref_errors(value: Any, prefix: str, *, require_id: bool) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"{prefix} is missing or not an object"]
    if any(not isinstance(field, str) for field in value):
        return [f"{prefix} contains a non-string object key"]
    for field in sorted(set(value) - _TYPED_REF_FIELDS):
        if has_forbidden_key(field, _FORBIDDEN_NESTED_KEY_PARTS):
            errors.append(f"{prefix}.{field} is forbidden")
        else:
            errors.append(f"{prefix}.{field} is not an admitted metadata field")
    required = ("id", "ref", "owner", "kind", "currentness", "access_scope", "authority", "claim_policy", "snapshot_role", "claim_limit")
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
    if not is_known_owner(value.get("owner")):
        errors.append(f"{prefix}.owner is unknown")
    if not is_known_claim_policy(value.get("claim_policy")):
        errors.append(f"{prefix}.claim_policy is unknown")
    if not is_safe_diagnostic(value.get("snapshot_role")):
        errors.append(f"{prefix}.snapshot_role is missing or unbounded")
    if value.get("freshness") is not None:
        if value.get("freshness") not in KNOWN_CURRENTNESS:
            errors.append(f"{prefix}.freshness is unknown")
        elif value.get("freshness") != value.get("currentness"):
            errors.append(f"{prefix}.freshness contradicts currentness")
    if value.get("expected_sha256") is not None and not _sha256(value.get("expected_sha256")):
        errors.append(f"{prefix}.expected_sha256 is malformed")
    for field in ("missing_fields", "degradation"):
        if field in value:
            errors.extend(_diagnostic_errors(value[field], f"{prefix}.{field}"))
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
    key_errors = _non_string_key_errors(record)
    if key_errors:
        return ["pressure record contains a non-string object key"]
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
        errors.extend(_object_field_errors(owner, "natural_owner", _NATURAL_OWNER_FIELDS))
        for field in ("owner", "owner_ref", "authority", "access_scope", "claim_policy"):
            if not _non_empty(owner.get(field)):
                errors.append(f"natural_owner.{field} is missing")
        if _unknown(owner.get("owner")) or not is_known_owner(owner.get("owner")):
            errors.append("natural_owner.owner is unknown")
        if owner.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
            errors.append("natural_owner.authority is unknown")
        if owner.get("access_scope") not in KNOWN_ACCESS_SCOPES:
            errors.append("natural_owner.access_scope is unknown")
        if not is_known_claim_policy(owner.get("claim_policy")):
            errors.append("natural_owner.claim_policy is unknown")

    surfaces = record.get("checked_existing_surfaces")
    if not isinstance(surfaces, list) or not surfaces:
        errors.append("checked_existing_surfaces is missing")
    else:
        for index, item in enumerate(surfaces):
            prefix = f"checked_existing_surfaces[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} is not an object")
                continue
            errors.extend(_object_field_errors(item, prefix, _SURFACE_FIELDS))
            for field in ("surface", "owner", "result", "ref", "access_scope", "authority", "claim_policy", "claim_limit"):
                if not _non_empty(item.get(field)):
                    errors.append(f"{prefix}.{field} is missing")
            if item.get("result") not in KNOWN_SURFACE_RESULTS:
                errors.append(f"{prefix}.result is unknown")
            if not is_known_owner(item.get("owner")):
                errors.append(f"{prefix}.owner is unknown")
            if item.get("access_scope") not in KNOWN_ACCESS_SCOPES:
                errors.append(f"{prefix}.access_scope is unknown")
            if item.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
                errors.append(f"{prefix}.authority is unknown")
            if not is_known_claim_policy(item.get("claim_policy")):
                errors.append(f"{prefix}.claim_policy is unknown")

    independence = record.get("independence_signals")
    if not isinstance(independence, dict):
        errors.append("independence_signals is missing")
    else:
        errors.extend(_object_field_errors(independence, "independence_signals", _INDEPENDENCE_FIELDS))
        if independence.get("status") not in KNOWN_INDEPENDENCE_STATES:
            errors.append("independence_signals.status is unknown")
        if not isinstance(independence.get("signals"), list):
            errors.append("independence_signals.signals is missing")
        else:
            errors.extend(_diagnostic_errors(independence["signals"], "independence_signals.signals"))
        if not is_known_claim_policy(independence.get("claim_policy")):
            errors.append("independence_signals.claim_policy is unknown")
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
        errors.extend(_object_field_errors(route, "next_route", _ROUTE_FIELDS))
        for field in ("owner", "owner_ref", "route", "reason", "authority", "access_scope", "effect", "claim_policy", "claim_limit"):
            if not _non_empty(route.get(field)):
                errors.append(f"next_route.{field} is missing")
        if _unknown(route.get("owner")) or not is_known_owner(route.get("owner")) or _unknown(route.get("route")):
            errors.append("next_route owner/route is unknown")
        if route.get("authority") not in KNOWN_PRESSURE_AUTHORITIES:
            errors.append("next_route.authority is unknown")
        if route.get("access_scope") not in KNOWN_ACCESS_SCOPES:
            errors.append("next_route.access_scope is unknown")
        if route.get("effect") != "none":
            errors.append("next_route.effect must be none")
        if not isinstance(route.get("critical"), bool):
            errors.append("next_route.critical is missing")
        if not is_known_claim_policy(route.get("claim_policy")):
            errors.append("next_route.claim_policy is unknown")

    outcome = record.get("outcome")
    if not isinstance(outcome, dict):
        errors.append("outcome is missing")
    else:
        errors.extend(_object_field_errors(outcome, "outcome", _OUTCOME_FIELDS))
        if outcome.get("state") not in KNOWN_OUTCOMES:
            errors.append("outcome.state is unknown")
        if not is_known_owner(outcome.get("owner")):
            errors.append("outcome.owner is unknown")
        if not is_known_claim_policy(outcome.get("claim_policy")):
            errors.append("outcome.claim_policy is unknown")
        if not _non_empty(outcome.get("claim_limit")):
            errors.append("outcome.claim_limit is missing")

    if not _non_empty(record.get("claim_limit")):
        errors.append("pressure record claim_limit is missing")
    if not is_known_claim_policy(record.get("claim_policy")):
        errors.append("pressure record claim_policy is unknown")
    return errors


def _stable_pressure(value: Any, *, path: tuple[str, ...] = (), source_ref: bool = False) -> Any:
    """Strip timestamps only along explicitly declared pressure source-ref paths."""

    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            return {"diagnostic": "non_string_object_key"}
        result: dict[str, Any] = {}
        for key, item in sorted(value.items()):
            if source_ref and key == "observed_at":
                continue
            child_source_ref = source_ref or (not path and key in {"pressure_ref", "evidence", "source_evidence_ref"})
            result[key] = _stable_pressure(item, path=path + (key,), source_ref=child_source_ref)
        return result
    if isinstance(value, list):
        return [_stable_pressure(item, path=path, source_ref=source_ref) for item in value]
    return value


def pressure_digest(record: dict[str, Any]) -> str:
    value = copy.deepcopy(record)
    value.pop("record_digest", None)
    return content_digest(_stable_pressure(value))


def _legacy_ref(correlation_source: dict[str, Any]) -> tuple[dict[str, Any], list[str], str | None]:
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    master_filter = metadata.get("master_filter") if isinstance(metadata.get("master_filter"), dict) else {}
    raw_ref = copy.deepcopy(master_filter.get("ref")) if isinstance(master_filter.get("ref"), dict) else {}
    pressure_ref = copy.deepcopy(raw_ref)
    pressure_ref["id"] = "legacy:master-filter:pressure"
    required = (
        "ref",
        "sha256",
        "owner",
        "authority",
        "currentness",
        "access_scope",
        "claim_policy",
        "snapshot_role",
        "claim_limit",
    )
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
    admitted_obligations = [
        item
        for item in obligations
        if (isinstance(item, str) and item.strip()) or (isinstance(item, dict) and isinstance(item.get("sha256"), str) and _sha256(item.get("sha256")))
    ]
    for index, obligation in enumerate(admitted_obligations):
        pressure_ref, source_missing, legacy_freshness = _legacy_ref(correlation_source)
        redacted = redacted_legacy_obligation(obligation)
        digest = redacted["sha256"]
        pressure_ref["id"] = f"legacy:master-filter:pressure:{index}:{digest[:12]}"
        candidate: dict[str, Any] = {
            "pressure_ref": pressure_ref,
            "source_evidence_ref": copy.deepcopy(
                correlation_source.get("metadata", {}).get("master_filter", {}).get("ref", {})
            ),
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
    safe: dict[str, Any] = {}
    for key in sorted(_TYPED_REF_FIELDS):
        if key not in value:
            continue
        item = value[key]
        if key in {"missing_fields", "degradation"}:
            safe[key] = _safe_diagnostic_list(item)
        elif key == "snapshot_role":
            safe[key] = safe_diagnostic(item)
        elif isinstance(item, (str, type(None))):
            safe[key] = copy.deepcopy(item)
    return safe or {"id": "unresolved"}


def _redacted_invalid(record: Any, errors: list[str], *, migration: str | None = None) -> dict[str, Any]:
    pressure_ref = record.get("pressure_ref") if isinstance(record, dict) else None
    result: dict[str, Any] = {
        "pressure_ref": _safe_ref_summary(pressure_ref),
        "errors": _safe_diagnostic_list(errors),
        "outcome": "invalid",
        "claim_limit": "Malformed pressure is retained as an invalid input and is not routed or acted upon.",
    }
    if migration:
        result["migration"] = safe_diagnostic(migration)
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
        "missing_fields": _safe_diagnostic_list(candidate.get("missing_fields", [])),
        "source_missing_fields": _safe_diagnostic_list(candidate.get("source_missing_fields", [])),
        "outcome": "deferred",
        "migration": safe_diagnostic(candidate.get("migration", "legacy_master_filter")),
        "claim_limit": candidate.get("claim_limit", PRESSURE_CLAIM_LIMIT),
    }
    if isinstance(candidate.get("legacy_freshness"), str):
        result["legacy_freshness"] = (
            candidate["legacy_freshness"]
            if candidate["legacy_freshness"] in KNOWN_CURRENTNESS
            else safe_diagnostic(candidate["legacy_freshness"])
        )
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
        errors.append("pressure_inbox_records_not_a_list")
    for record in records:
        safe_record = _sanitize_pressure_diagnostics(record)
        item_errors = validate_pressure_record(safe_record, expected_goal_id=goal_id)
        if item_errors:
            invalid_records.append(_redacted_invalid(record, item_errors))
            continue
        item = copy.deepcopy(safe_record)
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
            legacy.append(_redacted_invalid(candidate, ["legacy_candidate_invalid"], migration="legacy_master_filter"))
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
        "errors": _safe_diagnostic_list(errors),
        "claim_limit": PRESSURE_CLAIM_LIMIT,
    }
    model["read_model_digest"] = content_digest(_stable_pressure(model))
    return model


validate_pressure = validate_pressure_record
build_pressure_read_model = build_pressure_inbox
