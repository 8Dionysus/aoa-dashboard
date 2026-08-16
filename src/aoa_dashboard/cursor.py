"""Versioned, deterministic retention for the Goal-local correlation read model.

The task-local handoff and wake files remain owned by their source routes.  This
module only turns already-adapted, admitted metadata observations into a
rebuildable dashboard projection.  It deliberately never selects a winning
observation when two observations disagree.

The materializer has a deliberately narrow guarantee: one ledger pair is
single-writer locked and recoverable.  The JSONL log may lead the checkpoint
after an interrupted call; the next locked invocation rebuilds from the log.
There is no two-file atomicity claim.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .source_binding import (
    KNOWN_CURRENTNESS,
    has_forbidden_key,
    is_known_claim_policy,
    is_known_owner,
    is_sha256,
)


OBSERVATION_SCHEMA_VERSION = "aoa_dashboard_correlation_observation_v1"
CURSOR_SCHEMA_VERSION = "aoa_dashboard_correlation_cursor_v1"
CHECKPOINT_SCHEMA_VERSION = "aoa_dashboard_correlation_checkpoint_v1"
PROJECTION_SCHEMA_VERSION = "aoa_dashboard_goal_local_correlation_projection_v1"
MIGRATION_SCHEMA_VERSION = "aoa_dashboard_correlation_migration_v1"

KNOWN_ACCESS_SCOPES = frozenset({"dashboard_local", "owner_bounded", "public_metadata"})
ACCESS_SCOPE_RANK = {"public_metadata": 0, "dashboard_local": 1, "owner_bounded": 2}
KNOWN_AUTHORITIES = frozenset(
    {
        "dashboard_derived",
        "source_owner",
        "master_filter",
        "master_decision",
        "aoa-dashboard:derived",
        "aoa-dashboard:derived_task_local_correlation",
    }
)
SHA256_LENGTH = 64

CLAIM_LIMIT = (
    "This is a dashboard-owned, metadata-only correlation projection. It does not establish "
    "actor meaning, runtime health, proof, owner acceptance, semantic continuation, or human acceptance."
)
CONFLICT_CLAIM_LIMIT = (
    "Conflicting observations are retained with their provenance and no winner. "
    "The dashboard cannot resolve an owner conflict."
)

_OBSERVATION_FIELDS = {
    "schema_version",
    "observation_id",
    "record_id",
    "entity_key",
    "kind",
    "goal_id",
    "master_thread_id",
    "observed_at",
    "payload",
    "payload_digest",
    "provenance",
}
_PROVENANCE_FIELDS = {
    "source_refs",
    "source_digest",
    "currentness",
    "access_scope",
    "authority",
    "claim_limit",
    "duplicate_count",
    "duplicate_source_refs",
    "admission_errors",
}
_SOURCE_REF_FIELDS = {
    "label",
    "kind",
    "ref",
    "sha256",
    "currentness",
    "freshness",
    "owner",
    "access_scope",
    "authority",
    "claim_limit",
    "degradation",
    "observed_at",
    "claim_policy",
    "expected_sha256",
    "snapshot_role",
    "missing_fields",
}
_CURSOR_FIELDS = frozenset(
    {
        "schema_version",
        "projection_schema_version",
        "stream_id",
        "goal_id",
        "master_thread_id",
        "position",
        "record_ids",
        "observation_digests",
        "source_watermarks",
        "source_collisions",
        "input_digest",
        "cursor_digest",
        "claim_limit",
    }
)
_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "projection_schema_version",
        "checkpoint_id",
        "goal_id",
        "master_thread_id",
        "cursor",
        "projection_digest",
        "retained_observation_ids",
        "conflict_ids",
        "rebuild_mode",
        "claim_limit",
    }
)

# This is the explicit metadata admission boundary.  A publisher may not
# invent a new observation kind or smuggle an arbitrary nested payload through
# the cursor.  The nested key set mirrors the existing typed correlation
# envelope and the small fallback/test metadata shapes.
_PAYLOAD_ROOT_FIELDS = {
    "correlation_envelope": frozenset(
        {
            "schema_version",
            "correlation_id",
            "state",
            "goal",
            "return_observation",
            "wake_observation",
            "accepted_turn",
            "master_filter",
            "dag_disposition",
            "lifecycle",
            "authority",
            "claim_limits",
        }
    ),
    "master_filter": frozenset(
        {
            "schema_version",
            "reviewed_at",
            "goal_ref",
            "return_ids",
            "goal_dag",
            "new_required_obligations",
            "rejected_or_deferred_claims",
            "claim_limit",
        }
    ),
    "correlation_surface": frozenset({"state", "freshness", "degradation", "observation"}),
    "test_observation": frozenset({"state", "owner_fact", "goal"}),
}
_PAYLOAD_NESTED_FIELDS = frozenset(
    {
        "schema_version",
        "correlation_id",
        "state",
        "goal_id",
        "master_thread_id",
        "anchor_ref",
        "claim_limit",
        "return_id",
        "source_schema_version",
        "responsibility_state",
        "ref",
        "filter_disposition",
        "errors",
        "outcome",
        "delivery_route",
        "handoff_delivery",
        "handoff_message_submitted",
        "observed_at",
        "accepted_turn_id",
        "basis_ref",
        "disposition",
        "handoff_sha256",
        "wake_receipt_ref",
        "reviewed_at",
        "nodes",
        "relevant_node_ids",
        "returned",
        "wake_requested",
        "master_filtered",
        "reentered",
        "observation",
        "evidence_refs",
        "id",
        "next",
        "label",
        "kind",
        "sha256",
        "freshness",
        "currentness",
        "owner",
        "access_scope",
        "authority",
        "degradation",
        "return_ids",
        "new_required_obligations",
        "rejected_or_deferred_claims",
        "owner_fact",
        "redacted",
        "claim_policy",
        "expected_sha256",
        "snapshot_role",
        "missing_fields",
    }
)
_FORBIDDEN_METADATA_KEY_PARTS = (
    "raw",
    "body",
    "secret",
    "token",
    "password",
    "prompt",
    "private",
    "payload",
)
_VOLATILE_PAYLOAD_PATHS = frozenset(
    {
        ("wake_observation", "observed_at"),
        ("accepted_turn", "observed_at"),
    }
)

_LEDGER_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LEDGER_LOCAL_LOCKS_GUARD = threading.Lock()


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by every cursor digest."""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonically serializable: {exc}") from exc


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


LEGACY_OBLIGATION_CLAIM_LIMIT = (
    "Legacy obligation text remains source-owned. The dashboard exposes only a digest-linked redaction "
    "until an allowed owner scope supplies a structured pressure record."
)


def redacted_legacy_obligation(value: Any) -> dict[str, Any]:
    """Return the only legacy obligation representation admitted to the read model."""

    digest = value.get("sha256") if isinstance(value, dict) and _is_sha256(value.get("sha256")) else None
    if digest is None and isinstance(value, str):
        digest = content_digest(value)
    if digest is None:
        redacted = "[redacted legacy obligation; digest unavailable]"
    else:
        redacted = f"[redacted legacy obligation; sha256={digest}]"
    return {"sha256": digest, "redacted": redacted, "claim_limit": LEGACY_OBLIGATION_CLAIM_LIMIT}


def redact_legacy_metadata(value: Any) -> Any:
    """Redact legacy obligation strings in an API/read-model metadata copy."""

    if isinstance(value, dict):
        return {
            key: (
                [
                    redacted_legacy_obligation(item)
                    for item in item_value
                ]
                if key in {"new_obligations", "new_required_obligations"} and isinstance(item_value, list)
                else redact_legacy_metadata(item_value)
            )
            for key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_legacy_metadata(item) for item in value]
    return value


def _is_non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: Any) -> bool:
    return is_sha256(value)


def _stable_payload(value: Any, *, path: tuple[str, ...] = (), source_ref: bool = False) -> Any:
    """Canonicalize only declared volatile read-time fields.

    Observation-level ``observed_at`` and typed source-ref ``observed_at`` are
    provenance displayed to operators but are not stable input identity.  The
    two nested envelope paths are the only payload timestamps declared
    volatile here.  Meaningful timestamps such as ``reviewed_at`` remain in
    every digest.
    """

    if isinstance(value, dict):
        is_observation = value.get("schema_version") == OBSERVATION_SCHEMA_VERSION and path in {(), ("observations",)}
        result: dict[str, Any] = {}
        for key, item in value.items():
            if is_observation and key == "observed_at":
                continue
            if source_ref and key == "observed_at":
                continue
            if path + (key,) in _VOLATILE_PAYLOAD_PATHS:
                continue
            child_source_ref = source_ref or (
                key == "source_refs" and path in {("provenance",), ("observations", "provenance")}
            )
            result[key] = _stable_payload(item, path=path + (key,), source_ref=child_source_ref)
        return result
    if isinstance(value, list):
        return [_stable_payload(item, path=path, source_ref=source_ref) for item in value]
    return value


def _metadata_shape_errors(value: Any, kind: str) -> list[str]:
    errors: list[str] = []
    allowed_root = _PAYLOAD_ROOT_FIELDS.get(kind)
    if allowed_root is None:
        return [f"observation kind is not admitted metadata: {kind}"]
    if not isinstance(value, dict):
        return ["metadata payload is not an object"]

    def walk(node: dict[str, Any], allowed: frozenset[str], path: str) -> None:
        for key, item in node.items():
            if not isinstance(key, str):
                errors.append(f"metadata key at {path or '<root>'} is not a string")
                continue
            if has_forbidden_key(key, _FORBIDDEN_METADATA_KEY_PARTS):
                errors.append(f"metadata key is not allowed: {path + '.' if path else ''}{key}")
                continue
            if key not in allowed:
                errors.append(f"metadata key is not admitted: {path + '.' if path else ''}{key}")
                continue
            if isinstance(item, dict):
                walk(item, _PAYLOAD_NESTED_FIELDS, path + ("." if path else "") + key)
            elif isinstance(item, list):
                for index, child in enumerate(item):
                    if isinstance(child, dict):
                        walk(child, _PAYLOAD_NESTED_FIELDS, f"{path}.{key}[{index}]")
                    elif not isinstance(child, (str, int, float, bool)) and child is not None:
                        errors.append(f"metadata list value is not scalar: {path}.{key}[{index}]")
            elif not isinstance(item, (str, int, float, bool)) and item is not None:
                errors.append(f"metadata value is not scalar/object/list: {path}.{key}")

    walk(value, allowed_root, "")
    return errors


def _admit_metadata_payload(kind: str, payload: Any) -> dict[str, Any]:
    errors = _metadata_shape_errors(payload, kind)
    if errors:
        raise ValueError("payload is not admitted metadata-only shape: " + "; ".join(errors[:8]))
    return copy.deepcopy(payload)


def _normalise_ref(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if any(key not in _SOURCE_REF_FIELDS for key in raw):
        return None
    ref = raw.get("ref") or raw.get("path")
    kind = raw.get("kind")
    label = raw.get("label")
    if not _is_non_empty(ref) or not _is_non_empty(kind) or not _is_non_empty(label):
        return None
    digest = raw.get("sha256")
    if digest is not None and not _is_sha256(digest):
        return None
    if "currentness" not in raw and "freshness" not in raw:
        return None
    currentness = raw.get("currentness") or raw.get("freshness")
    if currentness not in KNOWN_CURRENTNESS:
        return None
    if "freshness" in raw and raw.get("freshness") != currentness:
        return None
    owner = raw.get("owner")
    claim_policy = raw.get("claim_policy")
    if not is_known_owner(owner) or not is_known_claim_policy(claim_policy):
        return None
    access_scope = raw.get("access_scope")
    authority = raw.get("authority")
    claim_limit = raw.get("claim_limit")
    if access_scope not in KNOWN_ACCESS_SCOPES or authority not in KNOWN_AUTHORITIES:
        return None
    if not _is_non_empty(claim_limit):
        return None
    expected_digest = raw.get("expected_sha256")
    if expected_digest is not None and not _is_sha256(expected_digest):
        return None
    snapshot_role = raw.get("snapshot_role")
    if not _is_non_empty(snapshot_role):
        return None
    observed_at = raw.get("observed_at")
    if observed_at is not None and not isinstance(observed_at, str):
        return None
    degradation = raw.get("degradation")
    if degradation is not None and (not isinstance(degradation, list) or any(not isinstance(item, str) for item in degradation)):
        return None
    result: dict[str, Any] = {
        "label": str(label),
        "kind": str(kind),
        "ref": str(ref),
        "sha256": digest,
        "currentness": currentness,
        "owner": str(owner),
        "access_scope": access_scope,
        "authority": authority,
        "claim_policy": claim_policy,
        "claim_limit": claim_limit,
        "snapshot_role": snapshot_role,
    }
    if expected_digest is not None:
        result["expected_sha256"] = expected_digest
    if "freshness" in raw:
        result["freshness"] = raw["freshness"]
    if degradation is not None:
        result["degradation"] = list(degradation)
    if observed_at is not None:
        result["observed_at"] = observed_at
    missing_fields = raw.get("missing_fields")
    if missing_fields is not None:
        if not isinstance(missing_fields, list) or any(not isinstance(item, str) for item in missing_fields):
            return None
        result["missing_fields"] = list(missing_fields)
    return result


def _stable_source_ref(ref: dict[str, Any]) -> dict[str, Any]:
    return {key: ref.get(key) for key in _SOURCE_REF_FIELDS if key != "observed_at" and key in ref}


def _source_identity_key(ref: dict[str, Any]) -> str:
    return content_digest(_stable_source_ref(ref))


def _collect_refs(
    value: Any,
    result: list[dict[str, Any]],
    seen: set[str],
    admission_errors: list[str] | None = None,
) -> None:
    if isinstance(value, dict):
        if "ref" in value and "kind" in value:
            normalised = _normalise_ref(value)
            if normalised is not None:
                key = _source_identity_key(normalised)
                if key not in seen:
                    seen.add(key)
                    result.append(normalised)
            elif admission_errors is not None:
                admission_errors.append("source_ref_not_admitted_with_explicit_access_and_authority")
        for item in value.values():
            _collect_refs(item, result, seen, admission_errors)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, result, seen, admission_errors)


def _currentness(refs: Iterable[dict[str, Any]]) -> str:
    values = {str(item.get("currentness", "unknown")) for item in refs}
    if "invalid" in values:
        return "invalid"
    if "missing" in values and values <= {"missing"}:
        return "missing"
    if "stale" in values:
        return "stale"
    if "deferred" in values:
        return "deferred"
    if "unknown" in values:
        return "unknown"
    return "current_at_read"


def _source_digest(refs: list[dict[str, Any]]) -> str:
    stable_refs = [_stable_source_ref(item) for item in refs]
    stable_refs.sort(key=canonical_json)
    return content_digest(stable_refs)


def _observation_identity(observation: dict[str, Any]) -> dict[str, Any]:
    provenance = observation["provenance"]
    return {
        "goal_id": observation["goal_id"],
        "master_thread_id": observation["master_thread_id"],
        "observation_id": observation["observation_id"],
        "entity_key": observation["entity_key"],
        "kind": observation["kind"],
        "payload_digest": observation["payload_digest"],
        "source_digest": provenance["source_digest"],
        "currentness": provenance["currentness"],
        "access_scope": provenance["access_scope"],
        "authority": provenance["authority"],
        "claim_limit": provenance["claim_limit"],
    }


def _record_id(observation: dict[str, Any]) -> str:
    return f"{observation['observation_id']}#{content_digest(_observation_identity(observation))}"


def make_observation(
    *,
    goal_id: str,
    master_thread_id: str,
    observation_id: str,
    entity_key: str,
    kind: str,
    payload: dict[str, Any],
    source_refs: list[dict[str, Any]],
    currentness: str | None = None,
    access_scope: str = "owner_bounded",
    authority: str = "dashboard_derived",
    observed_at: str | None = None,
    admission_errors: list[str] | None = None,
) -> dict[str, Any]:
    """Build a fully attributed, metadata-only observation."""

    if not all(_is_non_empty(value) for value in (goal_id, master_thread_id, observation_id, entity_key, kind)):
        raise ValueError("observation identity fields are required")
    admitted_payload = _admit_metadata_payload(kind, payload)
    refs: list[dict[str, Any]] = []
    for raw in source_refs:
        normalised = _normalise_ref(raw)
        if normalised is None:
            raise ValueError("observation source refs require explicit owner, access_scope, authority, and claim_limit")
        refs.append(normalised)
    if not refs:
        raise ValueError("observation requires at least one source ref")
    if access_scope not in KNOWN_ACCESS_SCOPES:
        raise ValueError(f"unknown access scope: {access_scope}")
    if authority not in KNOWN_AUTHORITIES:
        raise ValueError(f"unknown authority: {authority}")
    if observed_at is not None and not isinstance(observed_at, str):
        raise ValueError("observation observed_at must be a string or null")
    provenance: dict[str, Any] = {
        "source_refs": refs,
        "source_digest": _source_digest(refs),
        "currentness": currentness or _currentness(refs),
        "access_scope": access_scope,
        "authority": authority,
        "claim_limit": CLAIM_LIMIT,
    }
    if admission_errors:
        provenance["admission_errors"] = list(admission_errors)
    result: dict[str, Any] = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_id,
        "record_id": "",
        "entity_key": entity_key,
        "kind": kind,
        "goal_id": goal_id,
        "master_thread_id": master_thread_id,
        "observed_at": observed_at,
        "payload": admitted_payload,
        "payload_digest": content_digest(_stable_payload(admitted_payload)),
        "provenance": provenance,
    }
    result["record_id"] = _record_id(result)
    return result


def _base_refs(correlation_source: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    refs: list[dict[str, Any]] = []
    errors: list[str] = []
    _collect_refs(correlation_source.get("evidence_refs", []), refs, set(), errors)
    return refs, errors


def observations_from_correlation(
    correlation_source: dict[str, Any],
    *,
    goal_id: str,
    master_thread_id: str,
) -> list[dict[str, Any]]:
    """Adapt the existing correlation envelope through the metadata boundary.

    The compatibility bridge reads existing facts and does not change the wake
    adapter.  Unadmitted publisher fields become a safe invalid observation;
    their values never enter a digest, retained payload, or UI response.
    """

    if not isinstance(correlation_source, dict):
        return []
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    base_refs, base_errors = _base_refs(correlation_source)
    observations: list[dict[str, Any]] = []
    adapter_errors = list(base_errors)
    raw_envelopes = metadata.get("envelopes") if isinstance(metadata.get("envelopes"), list) else []
    for index, envelope in enumerate(raw_envelopes):
        if adapter_errors:
            break
        if not isinstance(envelope, dict):
            adapter_errors.append("correlation_envelope_not_object")
            continue
        refs = copy.deepcopy(base_refs)
        local_errors: list[str] = []
        local_refs: list[dict[str, Any]] = []
        _collect_refs(envelope, local_refs, {_source_identity_key(item) for item in refs}, local_errors)
        refs.extend(local_refs)
        if local_errors:
            adapter_errors.extend(local_errors)
            continue
        return_observation = envelope.get("return_observation") if isinstance(envelope.get("return_observation"), dict) else {}
        return_id = return_observation.get("return_id") or envelope.get("correlation_id") or f"index-{index}"
        observed_at = (
            (envelope.get("wake_observation") or {}).get("observed_at")
            if isinstance(envelope.get("wake_observation"), dict)
            else None
        )
        try:
            observations.append(
                make_observation(
                    goal_id=goal_id,
                    master_thread_id=master_thread_id,
                    observation_id=f"envelope:{return_id}",
                    entity_key=f"return:{return_id}",
                    kind="correlation_envelope",
                    payload=redact_legacy_metadata(envelope),
                    source_refs=refs,
                    currentness=_currentness(refs),
                    observed_at=observed_at,
                )
            )
        except ValueError:
            adapter_errors.extend(["correlation_envelope_metadata_admission_rejected", *local_errors])

    master_filter = metadata.get("master_filter") if isinstance(metadata.get("master_filter"), dict) else {}
    filter_ref = master_filter.get("ref") if isinstance(master_filter.get("ref"), dict) else None
    if filter_ref is not None and not adapter_errors:
        refs = copy.deepcopy(base_refs)
        local_errors: list[str] = []
        normalised = _normalise_ref(filter_ref)
        if normalised is not None:
            refs.append(normalised)
        else:
            local_errors.append("legacy_master_filter_ref_not_admitted_with_explicit_access_and_authority")
        payload = {
            "schema_version": master_filter.get("schema_version"),
            "reviewed_at": master_filter.get("reviewed_at"),
            "goal_ref": master_filter.get("goal_ref"),
            "return_ids": master_filter.get("return_ids", []),
            "goal_dag": master_filter.get("goal_dag", []),
            "new_required_obligations": [
                redacted_legacy_obligation(item)
                for item in master_filter.get("new_required_obligations", [])
                if (isinstance(item, str) and item.strip()) or (isinstance(item, dict) and "redacted" in item)
            ],
            "rejected_or_deferred_claims": master_filter.get("rejected_or_deferred_claims", []),
        }
        try:
            observations.append(
                make_observation(
                    goal_id=goal_id,
                    master_thread_id=master_thread_id,
                    observation_id="master-filter",
                    entity_key="master-filter",
                    kind="master_filter",
                    payload=payload,
                    source_refs=refs,
                    currentness=filter_ref.get("currentness") or filter_ref.get("freshness") or "unknown",
                    observed_at=master_filter.get("reviewed_at"),
                )
            )
        except ValueError:
            adapter_errors.extend(["legacy_master_filter_metadata_admission_rejected", *local_errors])

    if not observations or adapter_errors:
        payload = {
            "state": correlation_source.get("state", "missing"),
            "freshness": correlation_source.get("freshness", "unknown"),
            "degradation": ["metadata_admission_rejected"] if adapter_errors else correlation_source.get("degradation", []),
            "observation": "Correlation metadata was unavailable or failed the explicit dashboard admission boundary.",
        }
        fallback_refs = base_refs or [
            {
                "label": "correlation source",
                "kind": "derived_correlation_source",
                "ref": "correlation:unresolved",
                "sha256": None,
                "currentness": "invalid" if adapter_errors else "unknown",
                "owner": "aoa-dashboard",
                "access_scope": "dashboard_local",
                "authority": "dashboard_derived",
                "claim_policy": "dashboard_derived_read_model",
                "snapshot_role": "derived_binding",
                "claim_limit": CLAIM_LIMIT,
            }
        ]
        try:
            observations.append(
                make_observation(
                    goal_id=goal_id,
                    master_thread_id=master_thread_id,
                    observation_id="correlation-surface",
                    entity_key="correlation-surface",
                    kind="correlation_surface",
                    payload=payload,
                    source_refs=fallback_refs,
                    currentness="invalid" if adapter_errors else correlation_source.get("freshness") or "unknown",
                )
            )
        except ValueError:
            return []
    return observations


def validate_observation(
    observation: Any,
    *,
    expected_goal_id: str | None = None,
    expected_master_thread_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(observation, dict):
        return ["observation is not an object"]
    unknown_fields = sorted(set(observation) - _OBSERVATION_FIELDS)
    if unknown_fields:
        errors.append("observation has unknown fields: " + ",".join(unknown_fields))
    if observation.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        errors.append("observation schema_version is unsupported")
    for field in ("observation_id", "record_id", "entity_key", "kind", "goal_id", "master_thread_id"):
        if not _is_non_empty(observation.get(field)):
            errors.append(f"observation {field} is missing")
    if expected_goal_id is not None and observation.get("goal_id") != expected_goal_id:
        errors.append("observation goal_id mismatch")
    if expected_master_thread_id is not None and observation.get("master_thread_id") != expected_master_thread_id:
        errors.append("observation master_thread_id mismatch")
    if observation.get("observed_at") is not None and not isinstance(observation.get("observed_at"), str):
        errors.append("observation observed_at is malformed")
    payload = observation.get("payload")
    if not isinstance(payload, dict):
        errors.append("observation payload is not an object")
    else:
        errors.extend(_metadata_shape_errors(payload, str(observation.get("kind", ""))))
        try:
            expected_payload_digest = content_digest(_stable_payload(payload))
            if observation.get("payload_digest") != expected_payload_digest:
                errors.append("observation payload_digest does not match payload")
        except ValueError as exc:
            errors.append(f"observation payload is not canonical: {exc}")

    provenance = observation.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("observation provenance is missing")
        return errors
    unknown_provenance = sorted(set(provenance) - _PROVENANCE_FIELDS)
    if unknown_provenance:
        errors.append("observation provenance has unknown fields: " + ",".join(unknown_provenance))
    refs = provenance.get("source_refs")
    normalised_refs: list[dict[str, Any]] = []
    if not isinstance(refs, list) or not refs:
        errors.append("observation provenance has no source_refs")
    else:
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                errors.append(f"observation source ref {index} is not an object")
                continue
            normalised = _normalise_ref(ref)
            if normalised is None:
                errors.append(f"observation source ref {index} is malformed or lacks explicit access/authority")
            else:
                normalised_refs.append(normalised)
    source_digest = provenance.get("source_digest")
    if not _is_sha256(source_digest):
        errors.append("observation provenance source_digest is missing or malformed")
    elif normalised_refs and source_digest != _source_digest(normalised_refs):
        errors.append("observation provenance source_digest does not match refs")
    currentness = provenance.get("currentness")
    if currentness not in KNOWN_CURRENTNESS:
        errors.append("observation provenance currentness is unknown")
    access_scope = provenance.get("access_scope")
    if access_scope not in KNOWN_ACCESS_SCOPES:
        errors.append("observation provenance access scope is unknown")
    authority = provenance.get("authority")
    if authority not in KNOWN_AUTHORITIES:
        errors.append("observation provenance authority is unknown")
    if not _is_non_empty(provenance.get("claim_limit")):
        errors.append("observation provenance claim_limit is missing")
    if provenance.get("admission_errors"):
        errors.append("observation metadata admission was not clean")
    if isinstance(provenance.get("duplicate_count"), int) and provenance.get("duplicate_count", 0) < 0:
        errors.append("observation duplicate_count is negative")
    expected_record_id: str | None = None
    if not errors and normalised_refs:
        expected_record_id = _record_id(observation)
    if expected_record_id is not None and observation.get("record_id") != expected_record_id:
        errors.append("observation record_id does not match complete identity and provenance")
    return errors


def _normalise_records(observations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: dict[str, dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for observation in sorted(observations, key=lambda item: (_record_id(item), item["entity_key"], canonical_json(item))):
        key = _record_id(observation)
        if key not in records:
            item = copy.deepcopy(observation)
            item["record_id"] = key
            item["provenance"].setdefault("duplicate_count", 0)
            item["provenance"].setdefault("duplicate_source_refs", [])
            records[key] = item
            continue
        existing = records[key]
        existing["provenance"]["duplicate_count"] = int(existing["provenance"].get("duplicate_count", 0)) + 1
        refs = existing["provenance"].setdefault("duplicate_source_refs", [])
        for ref in observation["provenance"].get("source_refs", []):
            if ref not in existing["provenance"].get("source_refs", []) and ref not in refs:
                refs.append(copy.deepcopy(ref))
        duplicates.append(
            {
                "record_id": existing["record_id"],
                "observation_id": observation["observation_id"],
                "entity_key": observation["entity_key"],
                "payload_digest": observation["payload_digest"],
                "source_digest": observation["provenance"]["source_digest"],
                "source_refs": copy.deepcopy(observation["provenance"].get("source_refs", [])),
                "claim_limit": "Exact replay/duplicate retained as provenance; it does not create a second winner.",
            }
        )
    return list(records.values()), duplicates


def _conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_entity: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_entity.setdefault(record["entity_key"], []).append(record)
    by_observation_id: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_observation_id.setdefault(record["observation_id"], []).append(record)
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    groups.extend((f"entity:{key}", values) for key, values in by_entity.items() if len(values) > 1)
    groups.extend((f"observation:{key}", values) for key, values in by_observation_id.items() if len(values) > 1)
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for conflict_key, values in sorted(groups, key=lambda item: item[0]):
        record_ids = tuple(sorted(item["record_id"] for item in values))
        identity = record_ids
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            {
                "conflict_id": f"conflict:{content_digest({'key': conflict_key, 'records': record_ids})[:24]}",
                "conflict_key": conflict_key,
                "entity_key": values[0]["entity_key"],
                "record_ids": list(record_ids),
                "observation_ids": sorted({item["observation_id"] for item in values}),
                "payload_digests": sorted({item["payload_digest"] for item in values}),
                "observations": [
                    {
                        "record_id": item["record_id"],
                        "observation_id": item["observation_id"],
                        "entity_key": item["entity_key"],
                        "payload_digest": item["payload_digest"],
                        "source_digest": item["provenance"]["source_digest"],
                        "source_refs": copy.deepcopy(item["provenance"].get("source_refs", [])),
                    }
                    for item in sorted(values, key=lambda item: item["record_id"])
                ],
                "resolution": "unresolved",
                "winner": None,
                "claim_limit": CONFLICT_CLAIM_LIMIT,
            }
        )
    return result


def _source_watermarks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for record in records:
        for ref in record["provenance"].get("source_refs", []):
            identity_key = _source_identity_key(ref)
            stable = _stable_source_ref(ref)
            values[identity_key] = {"identity_key": identity_key, **stable}
    return [values[key] for key in sorted(values)]


def _source_collisions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_ref: dict[str, list[dict[str, Any]]] = {}
    for watermark in _source_watermarks(records):
        by_ref.setdefault(watermark["ref"], []).append(watermark)
    result: list[dict[str, Any]] = []
    for ref, values in sorted(by_ref.items()):
        if len(values) < 2:
            continue
        scopes = [ACCESS_SCOPE_RANK.get(str(item.get("access_scope")), -1) for item in values]
        result.append(
            {
                "ref": ref,
                "candidate_identity_keys": sorted(item["identity_key"] for item in values),
                "access_downgrade": min(scopes) < max(scopes),
                "access_scope_drift": len({item.get("access_scope") for item in values}) > 1,
                "label_drift": len({item.get("label") for item in values}) > 1,
                "kind_drift": len({item.get("kind") for item in values}) > 1,
                "digest_drift": len({item.get("sha256") for item in values}) > 1,
                "currentness_drift": len({item.get("currentness") for item in values}) > 1,
                "owner_drift": len({item.get("owner") for item in values}) > 1,
                "authority_drift": len({item.get("authority") for item in values}) > 1,
                "claim_limit_drift": len({item.get("claim_limit") for item in values}) > 1,
                "resolution": "unresolved",
                "winner": None,
                "claim_limit": CONFLICT_CLAIM_LIMIT,
            }
        )
    return result


def build_cursor(
    *,
    goal_id: str,
    master_thread_id: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    record_view = [
        {
            "record_id": item["record_id"],
            "observation_id": item["observation_id"],
            "entity_key": item["entity_key"],
            "kind": item["kind"],
            "payload_digest": item["payload_digest"],
            "source_digest": item["provenance"]["source_digest"],
            "access_scope": item["provenance"]["access_scope"],
            "authority": item["provenance"]["authority"],
            "claim_limit": item["provenance"]["claim_limit"],
        }
        for item in sorted(records, key=lambda value: value["record_id"])
    ]
    core: dict[str, Any] = {
        "schema_version": CURSOR_SCHEMA_VERSION,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "stream_id": f"goal:{goal_id}/thread:{master_thread_id}",
        "goal_id": goal_id,
        "master_thread_id": master_thread_id,
        "position": len(record_view),
        "record_ids": [item["record_id"] for item in record_view],
        "observation_digests": record_view,
        "source_watermarks": _source_watermarks(records),
        "source_collisions": _source_collisions(records),
        "input_digest": content_digest(record_view),
        "claim_limit": CLAIM_LIMIT,
    }
    core["cursor_digest"] = content_digest(core)
    return core


def validate_cursor(
    cursor: Any,
    *,
    expected_goal_id: str | None = None,
    expected_master_thread_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(cursor, dict):
        return ["cursor is not an object"]
    unknown_fields = sorted(set(cursor) - _CURSOR_FIELDS)
    if unknown_fields:
        errors.append("cursor has unknown fields: " + ",".join(unknown_fields))
    required_fields = (
        "schema_version",
        "projection_schema_version",
        "stream_id",
        "goal_id",
        "master_thread_id",
        "position",
        "record_ids",
        "observation_digests",
        "source_watermarks",
        "source_collisions",
        "input_digest",
        "cursor_digest",
        "claim_limit",
    )
    for field in required_fields:
        if field not in cursor:
            errors.append(f"cursor {field} is missing")
    if cursor.get("schema_version") != CURSOR_SCHEMA_VERSION:
        errors.append("cursor schema_version is unsupported")
    if cursor.get("projection_schema_version") != PROJECTION_SCHEMA_VERSION:
        errors.append("cursor projection_schema_version is unsupported")
    if cursor.get("claim_limit") != CLAIM_LIMIT:
        errors.append("cursor claim_limit is not the admitted limit")
    if expected_goal_id is not None and cursor.get("goal_id") != expected_goal_id:
        errors.append("cursor goal_id mismatch")
    if expected_master_thread_id is not None and cursor.get("master_thread_id") != expected_master_thread_id:
        errors.append("cursor master_thread_id mismatch")
    if _is_non_empty(cursor.get("goal_id")) and _is_non_empty(cursor.get("master_thread_id")):
        expected_stream = f"goal:{cursor['goal_id']}/thread:{cursor['master_thread_id']}"
        if cursor.get("stream_id") != expected_stream:
            errors.append("cursor stream_id does not match Goal/thread")
    if not _is_sha256(cursor.get("cursor_digest")):
        errors.append("cursor cursor_digest is malformed")
    if not _is_sha256(cursor.get("input_digest")):
        errors.append("cursor input_digest is malformed")
    if not isinstance(cursor.get("position"), int) or cursor.get("position", -1) < 0:
        errors.append("cursor position is malformed")
    if not isinstance(cursor.get("record_ids"), list):
        errors.append("cursor record_ids is not a list")
    if not isinstance(cursor.get("observation_digests"), list):
        errors.append("cursor observation_digests is not a list")
    if not isinstance(cursor.get("source_watermarks"), list):
        errors.append("cursor source_watermarks is not a list")
    if not isinstance(cursor.get("source_collisions"), list):
        errors.append("cursor source_collisions is not a list")
    if isinstance(cursor.get("record_ids"), list):
        if cursor.get("position") != len(cursor["record_ids"]):
            errors.append("cursor position does not match record_ids")
        if len(set(cursor["record_ids"])) != len(cursor["record_ids"]):
            errors.append("cursor record_ids contains duplicates")
        if cursor["record_ids"] != sorted(cursor["record_ids"]):
            errors.append("cursor record_ids are not canonicalized")
    if isinstance(cursor.get("observation_digests"), list):
        if [item.get("record_id") for item in cursor["observation_digests"] if isinstance(item, dict)] != cursor.get("record_ids"):
            errors.append("cursor observation_digests do not match record_ids")
        for index, item in enumerate(cursor["observation_digests"]):
            if not isinstance(item, dict):
                errors.append(f"cursor observation_digests[{index}] is malformed")
                continue
            for field in ("record_id", "observation_id", "entity_key", "kind", "payload_digest", "source_digest", "claim_limit"):
                if not _is_non_empty(item.get(field)):
                    errors.append(f"cursor observation_digests[{index}].{field} is missing")
            for field in ("payload_digest", "source_digest"):
                if not _is_sha256(item.get(field)):
                    errors.append(f"cursor observation_digests[{index}].{field} is malformed")
            if item.get("access_scope") not in KNOWN_ACCESS_SCOPES:
                errors.append(f"cursor observation_digests[{index}].access_scope is unknown")
            if item.get("authority") not in KNOWN_AUTHORITIES:
                errors.append(f"cursor observation_digests[{index}].authority is unknown")
    if isinstance(cursor.get("source_watermarks"), list):
        identities: set[str] = set()
        for index, item in enumerate(cursor["source_watermarks"]):
            if not isinstance(item, dict):
                errors.append(f"cursor source_watermarks[{index}] is malformed")
                continue
            for field in ("identity_key", "label", "kind", "ref", "currentness", "owner", "access_scope", "authority", "claim_limit"):
                if not _is_non_empty(item.get(field)):
                    errors.append(f"cursor source_watermarks[{index}].{field} is missing")
            if not _is_sha256(item.get("identity_key")):
                errors.append(f"cursor source_watermarks[{index}].identity_key is malformed")
            if item.get("sha256") is not None and not _is_sha256(item.get("sha256")):
                errors.append(f"cursor source_watermarks[{index}] has malformed sha256")
            if item.get("currentness") not in KNOWN_CURRENTNESS:
                errors.append(f"cursor source_watermarks[{index}] has unknown currentness")
            if item.get("access_scope") not in KNOWN_ACCESS_SCOPES:
                errors.append(f"cursor source_watermarks[{index}] has unknown access scope")
            if item.get("authority") not in KNOWN_AUTHORITIES:
                errors.append(f"cursor source_watermarks[{index}] has unknown authority")
            if item.get("identity_key") in identities:
                errors.append(f"cursor source_watermarks[{index}] identity collides")
            identities.add(str(item.get("identity_key")))
    if isinstance(cursor, dict) and _is_sha256(cursor.get("cursor_digest")):
        copy_value = copy.deepcopy(cursor)
        copy_value.pop("cursor_digest", None)
        if content_digest(copy_value) != cursor.get("cursor_digest"):
            errors.append("cursor cursor_digest does not match cursor contents")
    return errors


def _cursor_maps(cursor: dict[str, Any]) -> tuple[set[str], dict[str, str], dict[str, str]]:
    record_ids = {str(item) for item in cursor.get("record_ids", [])}
    observation_digests = {
        str(item.get("record_id")): content_digest(item)
        for item in cursor.get("observation_digests", [])
        if isinstance(item, dict) and _is_non_empty(item.get("record_id"))
    }
    source_watermarks = {
        str(item.get("identity_key")): content_digest(item)
        for item in cursor.get("source_watermarks", [])
        if isinstance(item, dict) and _is_non_empty(item.get("identity_key"))
    }
    return record_ids, observation_digests, source_watermarks


def validate_checkpoint(
    checkpoint: Any,
    *,
    expected_goal_id: str | None = None,
    expected_master_thread_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(checkpoint, dict):
        return ["checkpoint is not an object"]
    unknown_fields = sorted(set(checkpoint) - _CHECKPOINT_FIELDS)
    if unknown_fields:
        errors.append("checkpoint has unknown fields: " + ",".join(unknown_fields))
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        errors.append("checkpoint schema_version is unsupported")
    if checkpoint.get("projection_schema_version") != PROJECTION_SCHEMA_VERSION:
        errors.append("checkpoint projection_schema_version is unsupported")
    for field in ("checkpoint_id", "goal_id", "master_thread_id", "projection_digest", "claim_limit"):
        if not _is_non_empty(checkpoint.get(field)):
            errors.append(f"checkpoint {field} is missing")
    if checkpoint.get("claim_limit") != CLAIM_LIMIT:
        errors.append("checkpoint claim_limit is not the admitted limit")
    if expected_goal_id is not None and checkpoint.get("goal_id") != expected_goal_id:
        errors.append("checkpoint goal_id mismatch")
    if expected_master_thread_id is not None and checkpoint.get("master_thread_id") != expected_master_thread_id:
        errors.append("checkpoint master_thread_id mismatch")
    if not _is_sha256(checkpoint.get("projection_digest")):
        errors.append("checkpoint projection_digest is malformed")
    if checkpoint.get("rebuild_mode") not in {"initial", "replay", "extension", "invalid"}:
        errors.append("checkpoint rebuild_mode is unsupported")
    for field in ("retained_observation_ids", "conflict_ids"):
        if not isinstance(checkpoint.get(field), list):
            errors.append(f"checkpoint {field} is not a list")
    cursor = checkpoint.get("cursor")
    if isinstance(cursor, dict) and checkpoint.get("checkpoint_id") != f"checkpoint:{cursor.get('cursor_digest', '')}":
        errors.append("checkpoint checkpoint_id does not match cursor")
    if isinstance(cursor, dict) and isinstance(checkpoint.get("retained_observation_ids"), list):
        if checkpoint["retained_observation_ids"] != cursor.get("record_ids"):
            errors.append("checkpoint retained_observation_ids do not match cursor")
    errors.extend(
        f"checkpoint cursor: {error}"
        for error in validate_cursor(
            checkpoint.get("cursor"),
            expected_goal_id=expected_goal_id,
            expected_master_thread_id=expected_master_thread_id,
        )
    )
    return errors


def _projection_model(
    *,
    goal_id: str,
    master_thread_id: str,
    cursor: dict[str, Any],
    records: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    duplicates: list[dict[str, Any]],
    mode: str,
    errors: list[str],
) -> dict[str, Any]:
    source_collision_count = len(cursor.get("source_collisions", []))
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "goal_id": goal_id,
        "master_thread_id": master_thread_id,
        "status": "invalid" if errors else ("conflicted" if conflicts or source_collision_count else "current"),
        "cursor": cursor,
        "observations": records,
        "conflicts": conflicts,
        "duplicates": duplicates,
        "retention": {
            "mode": "append_only_metadata",
            "retained_observation_count": len(records),
            "conflict_count": len(conflicts),
            "source_collision_count": source_collision_count,
            "duplicate_count": len(duplicates),
            "provenance_preserved": True,
            "winner_selection": "none",
            "claim_limit": CONFLICT_CLAIM_LIMIT if conflicts or source_collision_count else CLAIM_LIMIT,
        },
        "rebuild": {
            "mode": mode,
            "deterministic": not errors,
            "replay_safe": not errors,
            "errors": errors,
            "claim_limit": "A rebuild result is a derived read model; it is not source-owner truth.",
        },
        "authority": "aoa-dashboard:derived_goal_local_correlation",
        "claim_limits": [CLAIM_LIMIT, CONFLICT_CLAIM_LIMIT],
    }


def _projection_digest(model: dict[str, Any]) -> str:
    value = _stable_payload(copy.deepcopy(model))
    value.pop("checkpoint", None)
    value.pop("generated_at", None)
    rebuild = value.get("rebuild")
    if isinstance(rebuild, dict):
        rebuild.pop("mode", None)
    return content_digest(value)


def _authenticate_checkpoint(
    checkpoint: dict[str, Any],
    *,
    raw_observations: list[dict[str, Any]],
    goal_id: str,
    master_thread_id: str,
) -> list[str]:
    """Authenticate checkpoint content against retained log observations."""

    errors = validate_checkpoint(
        checkpoint,
        expected_goal_id=goal_id,
        expected_master_thread_id=master_thread_id,
    )
    if checkpoint.get("rebuild_mode") == "invalid":
        errors.append("checkpoint rebuild_mode invalid cannot be authenticated")
    if errors:
        return [f"checkpoint_invalid:{error}" for error in errors]

    previous = checkpoint["cursor"]
    old_ids, _, _ = _cursor_maps(previous)
    retained_raw = [item for item in raw_observations if item.get("record_id") in old_ids]
    retained_ids = {_record_id(item) for item in retained_raw}
    if retained_ids != old_ids:
        return ["checkpoint_invalid:cursor_drift:retained observation records are not all available in the log"]
    prior_records, prior_duplicates = _normalise_records(retained_raw)
    prior_records.sort(key=lambda item: item["record_id"])
    prior_conflicts = _conflicts(prior_records)
    expected_cursor = build_cursor(goal_id=goal_id, master_thread_id=master_thread_id, records=prior_records)
    if canonical_json(previous) != canonical_json(expected_cursor):
        return ["checkpoint_invalid:cursor does not match canonical retained observations"]
    expected_conflict_ids = [item["conflict_id"] for item in prior_conflicts]
    if checkpoint.get("retained_observation_ids") != expected_cursor["record_ids"]:
        return ["checkpoint_invalid:retained_observation_ids do not match canonical records"]
    if checkpoint.get("conflict_ids") != expected_conflict_ids:
        return ["checkpoint_invalid:conflict_ids do not match canonical retained conflicts"]
    prior_model = _projection_model(
        goal_id=goal_id,
        master_thread_id=master_thread_id,
        cursor=expected_cursor,
        records=prior_records,
        conflicts=prior_conflicts,
        duplicates=prior_duplicates,
        mode=str(checkpoint.get("rebuild_mode")),
        errors=[],
    )
    expected_projection_digest = _projection_digest(prior_model)
    if checkpoint.get("projection_digest") != expected_projection_digest:
        return ["checkpoint_invalid:projection_digest does not match canonical retained observations"]
    return []


def _checkpoint_disposition(
    checkpoint: dict[str, Any] | None,
    cursor: dict[str, Any],
    records: list[dict[str, Any]],
    raw_observations: list[dict[str, Any]],
    *,
    goal_id: str,
    master_thread_id: str,
) -> tuple[str, list[str]]:
    if checkpoint is None:
        return "initial", []
    authentication_errors = _authenticate_checkpoint(
        checkpoint,
        raw_observations=raw_observations,
        goal_id=goal_id,
        master_thread_id=master_thread_id,
    )
    if authentication_errors:
        return "invalid", authentication_errors
    previous = checkpoint["cursor"]
    if previous["cursor_digest"] == cursor["cursor_digest"]:
        return "replay", []
    old_ids, old_observations, old_sources = _cursor_maps(previous)
    new_ids, new_observations, new_sources = _cursor_maps(cursor)
    if not old_ids <= new_ids:
        return "invalid", ["cursor_drift:previous records disappeared"]
    for record_id, digest in old_observations.items():
        if new_observations.get(record_id) != digest:
            return "invalid", [f"cursor_drift:observation identity changed:{record_id}"]
    for identity_key, digest in old_sources.items():
        if new_sources.get(identity_key) != digest:
            return "invalid", [f"cursor_drift:source watermark changed:{identity_key}"]
    if len(records) < len(old_ids):
        return "invalid", ["cursor_drift:cursor position moved backwards"]
    return "extension", []


def _checkpoint(
    *,
    goal_id: str,
    master_thread_id: str,
    cursor: dict[str, Any],
    projection_digest: str,
    records: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "projection_schema_version": PROJECTION_SCHEMA_VERSION,
        "checkpoint_id": f"checkpoint:{cursor['cursor_digest']}",
        "goal_id": goal_id,
        "master_thread_id": master_thread_id,
        "cursor": cursor,
        "projection_digest": projection_digest,
        "retained_observation_ids": [item["record_id"] for item in records],
        "conflict_ids": [item["conflict_id"] for item in conflicts],
        "rebuild_mode": mode,
        "claim_limit": CLAIM_LIMIT,
    }


def rebuild_goal_local_projection(
    *,
    goal_id: str,
    master_thread_id: str,
    observations: list[dict[str, Any]],
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rebuild a Goal-local projection from a full, canonical observation set."""

    errors: list[str] = []
    if not _is_non_empty(goal_id) or not _is_non_empty(master_thread_id):
        errors.append("goal_id and master_thread_id are required")
    if not isinstance(observations, list):
        observations = []
        errors.append("observations is not a list")
    valid: list[dict[str, Any]] = []
    for index, observation in enumerate(observations):
        item_errors = validate_observation(
            observation,
            expected_goal_id=goal_id,
            expected_master_thread_id=master_thread_id,
        )
        if item_errors:
            errors.extend(f"observation[{index}]:{error}" for error in item_errors)
        else:
            valid.append(copy.deepcopy(observation))
    if any(item.get("provenance", {}).get("currentness") == "invalid" for item in valid):
        errors.append("observation source currentness is invalid")
    records, duplicates = _normalise_records(valid)
    records.sort(key=lambda item: item["record_id"])
    conflicts = _conflicts(records)
    cursor = build_cursor(goal_id=goal_id, master_thread_id=master_thread_id, records=records)
    mode, checkpoint_errors = _checkpoint_disposition(
        checkpoint,
        cursor,
        records,
        valid,
        goal_id=goal_id,
        master_thread_id=master_thread_id,
    )
    errors.extend(checkpoint_errors)
    model = _projection_model(
        goal_id=goal_id,
        master_thread_id=master_thread_id,
        cursor=cursor,
        records=records,
        conflicts=conflicts,
        duplicates=duplicates,
        mode=mode,
        errors=errors,
    )
    projection_digest = _projection_digest(model)
    if checkpoint is not None and mode == "replay" and not checkpoint_errors:
        if checkpoint.get("projection_digest") != projection_digest:
            errors.append("checkpoint_invalid:projection_digest does not match replay")
            mode = "invalid"
            model["status"] = "invalid"
            model["rebuild"]["mode"] = mode
            model["rebuild"]["deterministic"] = False
            model["rebuild"]["replay_safe"] = False
            model["rebuild"]["errors"] = errors
    model["checkpoint"] = _checkpoint(
        goal_id=goal_id,
        master_thread_id=master_thread_id,
        cursor=cursor,
        projection_digest=projection_digest,
        records=records,
        conflicts=conflicts,
        mode=mode,
    )
    return model


def migrate_legacy_correlation_input(config: dict[str, Any], correlation_source: dict[str, Any]) -> dict[str, Any]:
    """Describe the old bootstrap/master-filter route without inventing fields."""

    current = config.get("current_correlation") if isinstance(config.get("current_correlation"), dict) else {}
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    master_filter = metadata.get("master_filter") if isinstance(metadata.get("master_filter"), dict) else {}
    return {
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "input_schema_version": config.get("schema_version", "legacy_bootstrap_config"),
        "bootstrap_binding": {
            "accepted": isinstance(config.get("historical_bootstrap"), dict) or bool(config.get("session_manifest_path")),
            "scope": "historical_only",
            "claim_limit": "Legacy bootstrap input is retained as context and is never promoted to current holder authority.",
        },
        "master_filter_binding": {
            "accepted": bool(current.get("master_filter_path")) and bool(master_filter),
            "ref": master_filter.get("ref"),
            "claim_limit": "Legacy master-filter input is a task-local disposition source; it is not proof or acceptance.",
        },
        "cursor_checkpoint": {
            "mode": "new_versioned_projection",
            "legacy_input_replayed": True,
            "claim_limit": "The compatibility bridge is deterministic only after the canonical observation cursor is built.",
        },
        "notes": [
            "Existing current_correlation.master_filter_path, handoff_glob and wake_glob remain accepted.",
            "Existing master-filter returns are adapted through the explicit metadata admission boundary.",
            "Legacy values are not silently treated as a cursor or as an owner verdict.",
        ],
        "claim_limit": CLAIM_LIMIT,
    }


@dataclass(frozen=True)
class _VerifiedLedgerLock:
    ledger_identity: str
    log_path: Path
    checkpoint_path: Path
    lock_path: Path


def _ledger_identity_from_stat(item: os.stat_result) -> str:
    if not stat.S_ISREG(item.st_mode):
        raise ValueError("observation ledger must be a regular file")
    return f"inode:{item.st_dev}:{item.st_ino}"


def _ledger_identity_for_path(path: Path) -> str:
    try:
        return _ledger_identity_from_stat(path.stat())
    except FileNotFoundError:
        raise ValueError("cannot prove physical observation-ledger identity for a missing path") from None


def _ledger_lock_path_for_identity(identity: str) -> Path:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return Path(tempfile.gettempdir()) / f".aoa-dashboard-ledger-{digest}.lock"


def _checkpoint_lock_path(observation_log_path: Path, checkpoint_path: Path) -> Path:
    """Return a lock for the physical/logical log identity, never the checkpoint path."""

    del checkpoint_path
    return _ledger_lock_path_for_identity(_ledger_identity_for_path(observation_log_path))


def _checkpoint_binding_path(path: Path) -> str:
    return str(path.resolve(strict=False))


def _read_lock_binding(descriptor: int) -> dict[str, Any] | None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    raw = os.read(descriptor, 16 * 1024)
    if not raw:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ledger lock binding is malformed: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("ledger lock binding is not an object")
    return value


def _write_lock_binding(descriptor: int, value: dict[str, Any]) -> None:
    data = (canonical_json(value) + "\n").encode("utf-8")
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.ftruncate(descriptor, 0)
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short ledger lock binding write")
        view = view[written:]
    os.fsync(descriptor)


def _binding_matches_ledger(binding: dict[str, Any], ledger_identity: str) -> bool:
    if binding.get("ledger_identity") != ledger_identity:
        return False
    bound_path_value = binding.get("canonical_log_path")
    if not isinstance(bound_path_value, str) or not bound_path_value:
        return False
    bound_path = Path(bound_path_value)
    try:
        return _ledger_identity_from_stat(bound_path.stat()) == ledger_identity
    except (FileNotFoundError, OSError, ValueError):
        # Inode numbers can be reused after a temporary ledger is deleted.  A
        # lock-file binding whose original path disappeared is not allowed to
        # bind a new ledger merely because the kernel reused the inode tuple.
        return False


def _local_ledger_lock(key: str) -> threading.Lock:
    with _LEDGER_LOCAL_LOCKS_GUARD:
        return _LEDGER_LOCAL_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def _ledger_lock(observation_log_path: Path, checkpoint_path: Path):
    """Serialize one physical log and bind it to one canonical checkpoint."""

    observation_log_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    log_descriptor = os.open(observation_log_path, os.O_CREAT | os.O_RDWR, 0o600)
    ledger_identity = _ledger_identity_from_stat(os.fstat(log_descriptor))
    lock_path = _ledger_lock_path_for_identity(ledger_identity)
    local_lock = _local_ledger_lock(ledger_identity)
    local_lock.acquire()
    descriptor = -1
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        binding = _read_lock_binding(descriptor)
        canonical_checkpoint = _checkpoint_binding_path(checkpoint_path)
        canonical_log = observation_log_path.resolve(strict=False)
        if binding is None or not _binding_matches_ledger(binding, ledger_identity):
            _write_lock_binding(
                descriptor,
                {
                    "schema_version": "aoa_dashboard_ledger_binding_v1",
                    "ledger_identity": ledger_identity,
                    "canonical_log_path": str(canonical_log),
                    "canonical_checkpoint_path": canonical_checkpoint,
                },
            )
        elif binding.get("canonical_checkpoint_path") != canonical_checkpoint:
            raise ValueError(
                "observation ledger is already bound to a different canonical checkpoint path"
            )
        yield _VerifiedLedgerLock(
            ledger_identity=ledger_identity,
            log_path=observation_log_path.resolve(strict=False),
            checkpoint_path=Path(canonical_checkpoint),
            lock_path=lock_path,
        )
    finally:
        if descriptor != -1:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        local_lock.release()
        os.close(log_descriptor)


def _require_verified_lock(
    lock_context: _VerifiedLedgerLock | None,
    log_path: Path | None = None,
    checkpoint_path: Path | None = None,
) -> None:
    if not isinstance(lock_context, _VerifiedLedgerLock):
        raise ValueError("ledger write requires a verified lock context")
    if log_path is not None and _ledger_identity_for_path(log_path) != lock_context.ledger_identity:
        raise ValueError("ledger write path is outside the verified physical ledger")
    if checkpoint_path is not None and _checkpoint_binding_path(checkpoint_path) != str(lock_context.checkpoint_path):
        raise ValueError("checkpoint write path is outside the verified canonical binding")


def _checkpoint_temp_paths(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f".{path.name}.tmp-*"))


def _cleanup_checkpoint_temps(path: Path) -> None:
    for temporary in _checkpoint_temp_paths(path):
        try:
            temporary.unlink()
        except FileNotFoundError:
            continue


def _fsync_parent_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace one checkpoint file, with durable temp cleanup."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.tmp-", dir=path.parent)
    temporary = Path(temporary_name)
    replaced = False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            stream.write(canonical_json(value) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        replaced = True
        _fsync_parent_directory(path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        if not replaced:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def _write_all(stream: Any, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if not isinstance(written, int) or written <= 0:
            raise OSError("short JSONL frame write")
        view = view[written:]


def _read_log_internal(
    path: str | os.PathLike[str],
    *,
    recover_partial_tail: bool,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any] | None]:
    source = Path(path)
    if not source.exists():
        return [], [], None
    try:
        raw = source.read_bytes()
    except (OSError, UnicodeError) as exc:
        return [], [f"observation log unreadable: {exc}"], None
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    recovery: dict[str, Any] | None = None
    offset = 0
    lines = raw.splitlines(keepends=True)
    for line_number, line in enumerate(lines, 1):
        line_end = offset + len(line)
        if not line.strip():
            offset = line_end
            continue
        framed = line.endswith(b"\n") or line.endswith(b"\r")
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            if recover_partial_tail and line_number == len(lines) and not framed:
                recovery = {"action": "truncate_partial_tail", "offset": offset}
                break
            errors.append(f"line {line_number}: malformed JSON: {exc}")
            offset = line_end
            continue
        if not isinstance(value, dict):
            errors.append(f"line {line_number}: observation is not an object")
            offset = line_end
            continue
        if not framed:
            if recover_partial_tail and line_number == len(lines):
                recovery = {"action": "complete_final_frame"}
            else:
                errors.append(f"line {line_number}: JSONL frame has no terminating newline")
        records.append(value)
        offset = line_end
    return records, errors, recovery


def _recover_partial_tail(path: Path, recovery: dict[str, Any] | None) -> None:
    if recovery is None:
        return
    if recovery.get("action") == "truncate_partial_tail":
        with path.open("r+b") as stream:
            stream.truncate(int(recovery["offset"]))
            stream.flush()
            os.fsync(stream.fileno())
        return
    if recovery.get("action") == "complete_final_frame":
        with path.open("ab", buffering=0) as stream:
            _write_all(stream, b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        return
    raise ValueError("unknown JSONL recovery action")


def read_correlation_observation_log(path: str | os.PathLike[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Read an append-only log without discarding malformed or partial lines."""

    records, errors, recovery = _read_log_internal(path, recover_partial_tail=False)
    if recovery is not None:
        errors.append("observation log has an unterminated final frame")
    return records, errors


def append_correlation_observations(
    path: str | os.PathLike[str],
    observations: list[dict[str, Any]],
    *,
    lock_context: _VerifiedLedgerLock | None = None,
) -> int:
    """Append framed JSONL records only under the verified materializer lock."""

    target = Path(path)
    _require_verified_lock(lock_context, target)

    for index, observation in enumerate(observations):
        errors = validate_observation(observation)
        if errors:
            raise ValueError(f"observation[{index}] is not admissible: {'; '.join(errors)}")
    if not observations:
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("ab", buffering=0) as stream:
        for observation in observations:
            frame = (canonical_json(observation) + "\n").encode("utf-8")
            _write_all(stream, frame)
        stream.flush()
        os.fsync(stream.fileno())
    return len(observations)


def read_correlation_checkpoint(path: str | os.PathLike[str]) -> tuple[dict[str, Any] | None, list[str]]:
    source = Path(path)
    if not source.exists():
        return None, []
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, [f"checkpoint unreadable: {exc}"]
    if not isinstance(value, dict):
        return None, ["checkpoint is not an object"]
    return value, []


def write_correlation_checkpoint(
    path: str | os.PathLike[str],
    checkpoint: dict[str, Any],
    *,
    lock_context: _VerifiedLedgerLock | None = None,
) -> None:
    target = Path(path)
    _require_verified_lock(lock_context, checkpoint_path=target)
    errors = validate_checkpoint(checkpoint)
    if errors:
        raise ValueError(f"checkpoint is not admissible: {'; '.join(errors)}")
    _write_json_atomic(target, checkpoint)


def materialize_goal_local_projection(
    *,
    goal_id: str,
    master_thread_id: str,
    observations: list[dict[str, Any]],
    observation_log_path: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Materialize one ledger pair under a recoverable single-writer lock.

    Crash states are explicit: a complete log with an old checkpoint is
    log-ahead and is recovered by the next invocation; a partial final JSONL
    frame is truncated or completed only when it is the final unterminated
    frame; a checkpoint replace/fsync failure never returns success.  The
    function makes no two-file atomicity claim.
    """

    log_path = Path(observation_log_path)
    checkpoint_file = Path(checkpoint_path)
    recovered_tail: dict[str, Any] | None = None
    with _ledger_lock(log_path, checkpoint_file) as lock_context:
        lock_path = lock_context.lock_path
        _cleanup_checkpoint_temps(checkpoint_file)
        existing, log_errors, recovery = _read_log_internal(log_path, recover_partial_tail=True)
        if log_errors:
            raise ValueError(f"observation log is not admissible: {'; '.join(log_errors)}")
        if recovery is not None:
            _recover_partial_tail(log_path, recovery)
            recovered_tail = recovery
        checkpoint, checkpoint_errors = read_correlation_checkpoint(checkpoint_file)
        if checkpoint_errors:
            raise ValueError(f"checkpoint is not admissible: {'; '.join(checkpoint_errors)}")
        candidate = rebuild_goal_local_projection(
            goal_id=goal_id,
            master_thread_id=master_thread_id,
            observations=[*existing, *observations],
            checkpoint=checkpoint,
        )
        if candidate["status"] == "invalid":
            raise ValueError("refusing to persist invalid correlation rebuild: " + "; ".join(candidate["rebuild"]["errors"]))

        existing_raw_digests = {content_digest(item) for item in existing}
        new_observations: list[dict[str, Any]] = []
        for item in observations:
            raw_digest = content_digest(item)
            if raw_digest not in existing_raw_digests:
                new_observations.append(item)
                existing_raw_digests.add(raw_digest)
        if new_observations:
            append_correlation_observations(log_path, new_observations, lock_context=lock_context)
        write_correlation_checkpoint(checkpoint_file, candidate["checkpoint"], lock_context=lock_context)
        candidate["storage"] = {
            "observation_log_path": str(observation_log_path),
            "checkpoint_path": str(checkpoint_path),
            "lock_path": str(lock_path),
            "durability": "locked_recoverable_log_ahead_checkpoint",
            "crash_states": [
                "complete_log_old_checkpoint_is recovered as log-ahead on the next locked invocation",
                "unterminated final JSONL frame is recovered only as a final partial tail",
                "checkpoint replace/fsync failure raises without reporting success",
            ],
            "recovered_tail": recovered_tail,
            "two_file_atomicity": False,
            "claim_limit": "Local materialization is derived evidence and never owner source truth.",
        }
        return candidate


# Stable descriptive aliases keep the contract discoverable without coupling
# callers to the internal function name used by the rebuild implementation.
build_correlation_cursor = build_cursor
build_goal_local_projection = rebuild_goal_local_projection
