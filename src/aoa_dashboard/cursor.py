"""Versioned, deterministic retention for the Goal-local correlation read model.

The task-local handoff and wake files remain owned by their source routes.  This
module only turns the already-adapted, metadata-only observations into a
rebuildable dashboard projection.  It deliberately never selects a winning
observation when two observations disagree.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


OBSERVATION_SCHEMA_VERSION = "aoa_dashboard_correlation_observation_v1"
CURSOR_SCHEMA_VERSION = "aoa_dashboard_correlation_cursor_v1"
CHECKPOINT_SCHEMA_VERSION = "aoa_dashboard_correlation_checkpoint_v1"
PROJECTION_SCHEMA_VERSION = "aoa_dashboard_goal_local_correlation_projection_v1"
MIGRATION_SCHEMA_VERSION = "aoa_dashboard_correlation_migration_v1"

KNOWN_CURRENTNESS = frozenset(
    {"current", "current_at_read", "stale", "deferred", "missing", "unknown", "invalid"}
)
KNOWN_ACCESS_SCOPES = frozenset({"dashboard_local", "owner_bounded", "public_metadata"})
KNOWN_AUTHORITIES = frozenset(
    {
        "dashboard_derived",
        "source_owner",
        "master_filter",
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


def canonical_json(value: Any) -> str:
    """Return the stable JSON representation used by every cursor digest."""

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not canonically serializable: {exc}") from exc


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _is_non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _stable_payload(value: Any, *, in_source_ref: bool = False) -> Any:
    """Remove only volatile timestamps from source-ref metadata.

    The current correlation adapter stamps a read-time ``observed_at`` onto
    some refs.  Keeping that value in the cursor would make an unchanged input
    look different on every poll.  The timestamp remains in the retained
    provenance; only the deterministic payload digest omits it.
    """

    if isinstance(value, dict):
        is_source_ref = in_source_ref or ("ref" in value and "kind" in value and "claim_limit" in value)
        return {
            key: _stable_payload(item, in_source_ref=is_source_ref)
            for key, item in value.items()
            if not (is_source_ref and key == "observed_at")
        }
    if isinstance(value, list):
        return [_stable_payload(item, in_source_ref=in_source_ref) for item in value]
    return value


def _owner_for_kind(kind: str) -> str:
    if kind in {"task_local_handoff", "task_local_wake_receipt"}:
        return "aoa-agents"
    if kind == "task_local_master_filter":
        return "master-thread"
    if kind == "goal_anchor":
        return "goal-anchor"
    if kind == "task_local_directory":
        return "task-local-runtime"
    return "aoa-dashboard"


def _normalise_ref(raw: Any, *, default_owner: str | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    ref = raw.get("ref") or raw.get("path")
    kind = raw.get("kind")
    if not _is_non_empty(ref) or not _is_non_empty(kind):
        return None
    digest = raw.get("sha256")
    if digest is not None and not _is_sha256(digest):
        return None
    currentness = raw.get("currentness") or raw.get("freshness") or "unknown"
    if currentness not in KNOWN_CURRENTNESS:
        return None
    claim_limit = raw.get("claim_limit")
    if not _is_non_empty(claim_limit):
        return None
    owner = raw.get("owner") or default_owner or _owner_for_kind(str(kind))
    if not _is_non_empty(owner):
        return None
    result: dict[str, Any] = {
        "label": raw.get("label") or str(kind),
        "kind": str(kind),
        "ref": str(ref),
        "sha256": digest,
        "currentness": currentness,
        "owner": str(owner),
        "access_scope": raw.get("access_scope") or "owner_bounded",
        "authority": raw.get("authority") or "dashboard_derived",
        "claim_limit": claim_limit,
    }
    if raw.get("observed_at") is not None:
        result["observed_at"] = raw["observed_at"]
    return result


def _collect_refs(value: Any, result: list[dict[str, Any]], seen: set[tuple[str, str, str | None]]) -> None:
    if isinstance(value, dict):
        if "ref" in value and "kind" in value:
            normalised = _normalise_ref(value)
            if normalised is not None:
                key = (normalised["kind"], normalised["ref"], normalised.get("sha256"))
                if key not in seen:
                    seen.add(key)
                    result.append(normalised)
        for item in value.values():
            _collect_refs(item, result, seen)
    elif isinstance(value, list):
        for item in value:
            _collect_refs(item, result, seen)


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
    return content_digest(
        [
            {
                "kind": item["kind"],
                "ref": item["ref"],
                "sha256": item.get("sha256"),
                "currentness": item["currentness"],
                "owner": item["owner"],
            }
            for item in sorted(refs, key=lambda value: (value["kind"], value["ref"], str(value.get("sha256"))))
        ]
    )


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
) -> dict[str, Any]:
    """Build a fully attributed observation for callers and tests."""

    if not all(_is_non_empty(value) for value in (goal_id, master_thread_id, observation_id, entity_key, kind)):
        raise ValueError("observation identity fields are required")
    if not isinstance(payload, dict):
        raise ValueError("observation payload must be an object")
    refs = []
    for raw in source_refs:
        normalised = _normalise_ref(raw)
        if normalised is None:
            raise ValueError("observation source refs must be typed and attributed")
        refs.append(normalised)
    if not refs:
        raise ValueError("observation requires at least one source ref")
    if access_scope not in KNOWN_ACCESS_SCOPES:
        raise ValueError(f"unknown access scope: {access_scope}")
    if authority not in KNOWN_AUTHORITIES:
        raise ValueError(f"unknown authority: {authority}")
    stable_payload = _stable_payload(payload)
    return {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_id,
        "record_id": f"{observation_id}#{content_digest(stable_payload)}",
        "entity_key": entity_key,
        "kind": kind,
        "goal_id": goal_id,
        "master_thread_id": master_thread_id,
        "observed_at": observed_at,
        "payload": stable_payload,
        "payload_digest": content_digest(stable_payload),
        "provenance": {
            "source_refs": refs,
            "source_digest": _source_digest(refs),
            "currentness": currentness or _currentness(refs),
            "access_scope": access_scope,
            "authority": authority,
            "claim_limit": CLAIM_LIMIT,
        },
    }


def _base_refs(correlation_source: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    _collect_refs(correlation_source.get("evidence_refs", []), refs, seen)
    return refs


def observations_from_correlation(
    correlation_source: dict[str, Any],
    *,
    goal_id: str,
    master_thread_id: str,
) -> list[dict[str, Any]]:
    """Adapt the existing correlation envelope into deterministic observations.

    This is the compatibility bridge for the current bootstrap/master-filter
    input.  It reads existing facts and does not change the wake adapter.
    """

    if not isinstance(correlation_source, dict):
        return []
    metadata = correlation_source.get("metadata") if isinstance(correlation_source.get("metadata"), dict) else {}
    base_refs = _base_refs(correlation_source)
    observations: list[dict[str, Any]] = []
    raw_envelopes = metadata.get("envelopes") if isinstance(metadata.get("envelopes"), list) else []
    for index, envelope in enumerate(raw_envelopes):
        if not isinstance(envelope, dict):
            continue
        refs = copy.deepcopy(base_refs)
        local_refs: list[dict[str, Any]] = []
        _collect_refs(envelope, local_refs, {(item["kind"], item["ref"], item.get("sha256")) for item in refs})
        refs.extend(local_refs)
        return_observation = envelope.get("return_observation") if isinstance(envelope.get("return_observation"), dict) else {}
        return_id = return_observation.get("return_id") or envelope.get("correlation_id") or f"index-{index}"
        observed_at = (
            (envelope.get("wake_observation") or {}).get("observed_at")
            if isinstance(envelope.get("wake_observation"), dict)
            else None
        )
        observations.append(
            make_observation(
                goal_id=goal_id,
                master_thread_id=master_thread_id,
                observation_id=f"envelope:{return_id}",
                entity_key=f"return:{return_id}",
                kind="correlation_envelope",
                payload=envelope,
                source_refs=refs,
                currentness=correlation_source.get("freshness") or "unknown",
                observed_at=observed_at,
            )
        )

    master_filter = metadata.get("master_filter") if isinstance(metadata.get("master_filter"), dict) else {}
    filter_ref = master_filter.get("ref") if isinstance(master_filter.get("ref"), dict) else None
    if filter_ref is not None:
        refs = copy.deepcopy(base_refs)
        normalised = _normalise_ref(filter_ref, default_owner="master-thread")
        if normalised is not None:
            refs.append(normalised)
        payload = {
            "schema_version": master_filter.get("schema_version"),
            "reviewed_at": master_filter.get("reviewed_at"),
            "goal_ref": master_filter.get("goal_ref"),
            "return_ids": master_filter.get("return_ids", []),
            "goal_dag": master_filter.get("goal_dag", []),
            "new_required_obligations": master_filter.get("new_required_obligations", []),
            "rejected_or_deferred_claims": master_filter.get("rejected_or_deferred_claims", []),
        }
        observations.append(
            make_observation(
                goal_id=goal_id,
                master_thread_id=master_thread_id,
                observation_id="master-filter",
                entity_key="master-filter",
                kind="master_filter",
                payload=payload,
                source_refs=refs,
                currentness=master_filter.get("ref", {}).get("freshness", "unknown"),
                observed_at=master_filter.get("reviewed_at"),
            )
        )

    if not observations:
        payload = {
            "state": correlation_source.get("state", "missing"),
            "freshness": correlation_source.get("freshness", "unknown"),
            "degradation": correlation_source.get("degradation", []),
            "observation": correlation_source.get("observation", "No correlation envelope was available."),
        }
        fallback_refs = base_refs or [
            {
                "label": "correlation source",
                "kind": "derived_correlation_source",
                "ref": "correlation:unresolved",
                "sha256": None,
                "currentness": "unknown",
                "owner": "aoa-dashboard",
                "claim_limit": CLAIM_LIMIT,
            }
        ]
        observations.append(
            make_observation(
                goal_id=goal_id,
                master_thread_id=master_thread_id,
                observation_id="correlation-surface",
                entity_key="correlation-surface",
                kind="correlation_surface",
                payload=payload,
                source_refs=fallback_refs,
                currentness=correlation_source.get("freshness") or "unknown",
            )
        )
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
    if observation.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        errors.append("observation schema_version is unsupported")
    for field in ("observation_id", "record_id", "entity_key", "kind", "goal_id", "master_thread_id"):
        if not _is_non_empty(observation.get(field)):
            errors.append(f"observation {field} is missing")
    if expected_goal_id is not None and observation.get("goal_id") != expected_goal_id:
        errors.append("observation goal_id mismatch")
    if expected_master_thread_id is not None and observation.get("master_thread_id") != expected_master_thread_id:
        errors.append("observation master_thread_id mismatch")
    payload = observation.get("payload")
    if not isinstance(payload, dict):
        errors.append("observation payload is not an object")
    else:
        try:
            expected_payload_digest = content_digest(_stable_payload(payload))
            if observation.get("payload_digest") != expected_payload_digest:
                errors.append("observation payload_digest does not match payload")
            if _is_non_empty(observation.get("observation_id")) and observation.get("record_id") != (
                f"{observation['observation_id']}#{expected_payload_digest}"
            ):
                errors.append("observation record_id does not match observation identity and payload")
        except ValueError as exc:
            errors.append(f"observation payload is not canonical: {exc}")
    provenance = observation.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("observation provenance is missing")
        return errors
    refs = provenance.get("source_refs")
    if not isinstance(refs, list) or not refs:
        errors.append("observation provenance has no source_refs")
    else:
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                errors.append(f"observation source ref {index} is not an object")
                continue
            if _normalise_ref(ref) is None:
                errors.append(f"observation source ref {index} is malformed")
            if ref.get("access_scope") not in KNOWN_ACCESS_SCOPES:
                errors.append(f"observation source ref {index} has unknown access scope")
            if ref.get("authority") not in KNOWN_AUTHORITIES:
                errors.append(f"observation source ref {index} has unknown authority")
    source_digest = provenance.get("source_digest")
    if not _is_sha256(source_digest):
        errors.append("observation provenance source_digest is missing or malformed")
    elif isinstance(refs, list):
        try:
            if source_digest != _source_digest([_normalise_ref(ref) for ref in refs if _normalise_ref(ref) is not None]):
                errors.append("observation provenance source_digest does not match refs")
        except (TypeError, ValueError):
            errors.append("observation provenance source_digest cannot be checked")
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
    return errors


def _record_id(observation: dict[str, Any]) -> str:
    return f"{observation['observation_id']}#{observation['payload_digest']}"


def _normalise_records(observations: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: dict[tuple[str, str], dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    for observation in sorted(observations, key=lambda item: (_record_id(item), item["entity_key"])):
        key = (observation["observation_id"], observation["payload_digest"])
        if key not in records:
            item = copy.deepcopy(observation)
            item["record_id"] = _record_id(observation)
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
                "payload_digest": observation["payload_digest"],
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
        # One disagreement can be visible through both its logical entity key
        # and an observation-id collision.  Retain one conflict record for the
        # same retained records so the read model does not double-count it.
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
                        "payload_digest": item["payload_digest"],
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
            key = str(ref["ref"])
            values[key] = {
                "ref": key,
                "sha256": ref.get("sha256"),
                "currentness": ref.get("currentness"),
                "owner": ref.get("owner"),
            }
    return [values[key] for key in sorted(values)]


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
            "payload_digest": item["payload_digest"],
            "source_digest": item["provenance"]["source_digest"],
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
        "observation_digests": [
            {"observation_id": item["observation_id"], "payload_digest": item["payload_digest"]}
            for item in record_view
        ],
        "source_watermarks": _source_watermarks(records),
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
    if cursor.get("schema_version") != CURSOR_SCHEMA_VERSION:
        errors.append("cursor schema_version is unsupported")
    if cursor.get("projection_schema_version") != PROJECTION_SCHEMA_VERSION:
        errors.append("cursor projection_schema_version is unsupported")
    for field in ("goal_id", "master_thread_id", "stream_id", "cursor_digest", "input_digest", "claim_limit"):
        if not _is_non_empty(cursor.get(field)):
            errors.append(f"cursor {field} is missing")
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
    if not isinstance(cursor.get("record_ids"), list):
        errors.append("cursor record_ids is not a list")
    if not isinstance(cursor.get("observation_digests"), list):
        errors.append("cursor observation_digests is not a list")
    if not isinstance(cursor.get("source_watermarks"), list):
        errors.append("cursor source_watermarks is not a list")
    if isinstance(cursor.get("record_ids"), list) and cursor.get("position") != len(cursor["record_ids"]):
        errors.append("cursor position does not match record_ids")
    if isinstance(cursor.get("record_ids"), list) and isinstance(cursor.get("observation_digests"), list):
        if len(cursor["record_ids"]) != len(cursor["observation_digests"]):
            errors.append("cursor record_ids and observation_digests lengths differ")
    if isinstance(cursor.get("source_watermarks"), list):
        for index, item in enumerate(cursor["source_watermarks"]):
            if not isinstance(item, dict) or not _is_non_empty(item.get("ref")):
                errors.append(f"cursor source_watermarks[{index}] is malformed")
            elif not _is_non_empty(item.get("owner")) or item.get("currentness") not in KNOWN_CURRENTNESS:
                errors.append(f"cursor source_watermarks[{index}] lacks owner/currentness")
            elif item.get("sha256") is not None and not _is_sha256(item.get("sha256")):
                errors.append(f"cursor source_watermarks[{index}] has malformed sha256")
    if isinstance(cursor, dict) and _is_sha256(cursor.get("cursor_digest")):
        copy_value = copy.deepcopy(cursor)
        copy_value.pop("cursor_digest", None)
        if content_digest(copy_value) != cursor.get("cursor_digest"):
            errors.append("cursor cursor_digest does not match cursor contents")
    return errors


def _cursor_maps(cursor: dict[str, Any]) -> tuple[set[str], dict[str, tuple[str, ...]], dict[str, tuple[Any, ...]]]:
    record_ids = set(str(item) for item in cursor.get("record_ids", []))
    observation_digests: dict[str, list[str]] = {}
    for item in cursor.get("observation_digests", []):
        if isinstance(item, dict):
            observation_digests.setdefault(str(item.get("observation_id")), []).append(str(item.get("payload_digest")))
    source_watermarks: dict[str, tuple[Any, ...]] = {}
    for item in cursor.get("source_watermarks", []):
        if isinstance(item, dict) and _is_non_empty(item.get("ref")):
            source_watermarks[str(item["ref"])] = (
                item.get("sha256"),
                item.get("currentness"),
                item.get("owner"),
            )
    return record_ids, {key: tuple(sorted(value)) for key, value in observation_digests.items()}, source_watermarks


def validate_checkpoint(
    checkpoint: Any,
    *,
    expected_goal_id: str | None = None,
    expected_master_thread_id: str | None = None,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(checkpoint, dict):
        return ["checkpoint is not an object"]
    if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        errors.append("checkpoint schema_version is unsupported")
    if checkpoint.get("projection_schema_version") != PROJECTION_SCHEMA_VERSION:
        errors.append("checkpoint projection_schema_version is unsupported")
    for field in ("checkpoint_id", "goal_id", "master_thread_id", "projection_digest", "claim_limit"):
        if not _is_non_empty(checkpoint.get(field)):
            errors.append(f"checkpoint {field} is missing")
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


def _checkpoint_disposition(
    checkpoint: dict[str, Any] | None,
    cursor: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    goal_id: str,
    master_thread_id: str,
) -> tuple[str, list[str]]:
    if checkpoint is None:
        return "initial", []
    errors = validate_checkpoint(
        checkpoint,
        expected_goal_id=goal_id,
        expected_master_thread_id=master_thread_id,
    )
    if errors:
        return "invalid", [f"checkpoint_invalid:{error}" for error in errors]
    previous = checkpoint["cursor"]
    if previous["cursor_digest"] == cursor["cursor_digest"]:
        return "replay", []
    old_ids, old_observations, old_sources = _cursor_maps(previous)
    new_ids, new_observations, new_sources = _cursor_maps(cursor)
    if not old_ids <= new_ids:
        return "invalid", ["cursor_drift:previous records disappeared"]
    for observation_id, digests in old_observations.items():
        if new_observations.get(observation_id) != digests:
            return "invalid", [f"cursor_drift:observation payload changed:{observation_id}"]
    for ref, watermark in old_sources.items():
        if new_sources.get(ref) != watermark:
            return "invalid", [f"cursor_drift:source watermark changed:{ref}"]
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
    checkpoint_core: dict[str, Any] = {
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
    return checkpoint_core


def _projection_digest(model: dict[str, Any]) -> str:
    value = copy.deepcopy(model)
    value.pop("checkpoint", None)
    value.pop("generated_at", None)
    rebuild = value.get("rebuild")
    if isinstance(rebuild, dict):
        rebuild.pop("mode", None)
    return content_digest(value)


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
    records, duplicates = _normalise_records(valid)
    records.sort(key=lambda item: item["record_id"])
    conflicts = _conflicts(records)
    cursor = build_cursor(goal_id=goal_id, master_thread_id=master_thread_id, records=records)
    mode, checkpoint_errors = _checkpoint_disposition(
        checkpoint,
        cursor,
        records,
        goal_id=goal_id,
        master_thread_id=master_thread_id,
    )
    errors.extend(checkpoint_errors)
    status = "invalid" if errors else ("conflicted" if conflicts else "current")
    model: dict[str, Any] = {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        "goal_id": goal_id,
        "master_thread_id": master_thread_id,
        "status": status,
        "cursor": cursor,
        "observations": records,
        "conflicts": conflicts,
        "duplicates": duplicates,
        "retention": {
            "mode": "append_only_metadata",
            "retained_observation_count": len(records),
            "conflict_count": len(conflicts),
            "duplicate_count": len(duplicates),
            "provenance_preserved": True,
            "winner_selection": "none",
            "claim_limit": CONFLICT_CLAIM_LIMIT if conflicts else CLAIM_LIMIT,
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
            "Existing master-filter returns are adapted into metadata-only observations.",
            "Legacy values are not silently treated as a cursor or as an owner verdict.",
        ],
        "claim_limit": CLAIM_LIMIT,
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_correlation_observation_log(path: str | os.PathLike[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Read an append-only log without discarding malformed lines."""

    source = Path(path)
    if not source.exists():
        return [], []
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        with source.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    errors.append(f"line {line_number}: malformed JSON: {exc}")
                    continue
                if not isinstance(value, dict):
                    errors.append(f"line {line_number}: observation is not an object")
                    continue
                records.append(value)
    except (OSError, UnicodeError) as exc:
        errors.append(f"observation log unreadable: {exc}")
    return records, errors


def append_correlation_observations(path: str | os.PathLike[str], observations: list[dict[str, Any]]) -> int:
    """Durably append already-validated observations; never overwrite the log."""

    for index, observation in enumerate(observations):
        errors = validate_observation(observation)
        if errors:
            raise ValueError(f"observation[{index}] is not admissible: {'; '.join(errors)}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        for observation in observations:
            stream.write(canonical_json(observation) + "\n")
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


def write_correlation_checkpoint(path: str | os.PathLike[str], checkpoint: dict[str, Any]) -> None:
    errors = validate_checkpoint(checkpoint)
    if errors:
        raise ValueError(f"checkpoint is not admissible: {'; '.join(errors)}")
    _write_json_atomic(Path(path), checkpoint)


def materialize_goal_local_projection(
    *,
    goal_id: str,
    master_thread_id: str,
    observations: list[dict[str, Any]],
    observation_log_path: str | os.PathLike[str],
    checkpoint_path: str | os.PathLike[str],
) -> dict[str, Any]:
    """Explicitly persist a bounded local ledger and its checkpoint.

    Projection GETs remain read-only.  An owner-controlled materialization call
    can use this function when local durability is required; it appends only
    unseen observation identities and writes the checkpoint atomically.  An
    invalid/drifted rebuild is never persisted.
    """

    existing, log_errors = read_correlation_observation_log(observation_log_path)
    if log_errors:
        raise ValueError(f"observation log is not admissible: {'; '.join(log_errors)}")
    checkpoint, checkpoint_errors = read_correlation_checkpoint(checkpoint_path)
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
    known = {
        (item.get("observation_id"), item.get("payload_digest"))
        for item in existing
        if isinstance(item, dict)
    }
    new_observations = [
        item
        for item in observations
        if (item.get("observation_id"), item.get("payload_digest")) not in known
    ]
    if new_observations:
        append_correlation_observations(observation_log_path, new_observations)
    write_correlation_checkpoint(checkpoint_path, candidate["checkpoint"])
    candidate["storage"] = {
        "observation_log_path": str(observation_log_path),
        "checkpoint_path": str(checkpoint_path),
        "durability": "append_only_log_and_atomic_checkpoint",
        "claim_limit": "Local materialization is derived evidence and never owner source truth.",
    }
    return candidate


# Stable descriptive aliases keep the contract discoverable without coupling
# callers to the internal function name used by the rebuild implementation.
build_correlation_cursor = build_cursor
build_goal_local_projection = rebuild_goal_local_projection
