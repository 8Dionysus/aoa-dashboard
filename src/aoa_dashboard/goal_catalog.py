"""Fail-closed admission for the owner-published Goal catalog snapshot."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from .source_binding import read_file_snapshot, snapshot_ref


OWNER_SCHEMA = "aoa_session_memory_goal_catalog_v1"
DASHBOARD_SCHEMA = "aoa_dashboard_goal_catalog_projection_v1"
OWNER = "aoa-session-memory"
SOURCE_REF = "aoa-session-memory:goal-lifecycles"
CURRENTNESS = frozenset({"current", "stale", "deferred", "unknown", "invalid"})
LIFECYCLE_STATES = frozenset(
    {
        "unknown",
        "create_requested",
        "create_failed",
        "active",
        "inspected",
        "updated",
        "paused",
        "deferred",
        "complete",
        "blocked",
    }
)
GROUPS = {
    "create_requested": "active",
    "active": "active",
    "inspected": "active",
    "updated": "active",
    "blocked": "attention",
    "create_failed": "attention",
    "unknown": "attention",
    "paused": "paused",
    "deferred": "paused",
    "complete": "completed",
}
TECHNICAL_TITLE_RE = re.compile(
    r"(?:^[/~.]|/(?:home|srv|tmp|var|run|etc|opt|usr)/|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
    r"\b(?:sha256:)?[0-9a-f]{40,64}\b|"
    r"\b(?:schema_version|artifact_type|thread_id|goal_instance_id|wake_receipt|luna_handoff)\b|"
    r"\.(?:jsonl?|toml|ya?ml|service|socket|target)(?:\b|$))",
    flags=re.IGNORECASE,
)
OWNER_DIAGNOSTICS = frozenset({"goal_lifecycle_source_generation_incompatible"})


def _empty(state: str, reason: str, *, evidence_refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": state,
        "items": [],
        "counts_by_group": {},
        "source": None,
        "evidence_refs": evidence_refs or [],
        "diagnostics": [reason],
        "claim_limit": "Scope: owner-published Goal navigation.",
    }


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 40:
        raise ValueError("timestamp_invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp_invalid") from exc
    return value


def _item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("catalog_item_invalid")
    goal_ref = value.get("goal_ref")
    lifecycle = value.get("lifecycle_state")
    title_state = value.get("title_state")
    title = value.get("title")
    if not isinstance(goal_ref, str) or not goal_ref or len(goal_ref) > 160:
        raise ValueError("goal_ref_invalid")
    if lifecycle not in LIFECYCLE_STATES:
        raise ValueError("lifecycle_state_invalid")
    if title_state == "available":
        if (
            not isinstance(title, str)
            or not title.strip()
            or len(title) > 96
            or any(ord(character) < 32 and character not in "\t\n\r" for character in title)
            or TECHNICAL_TITLE_RE.search(title)
        ):
            raise ValueError("human_title_invalid")
        title = " ".join(title.split())
    elif title_state in {"missing", "withheld"}:
        if title is not None:
            raise ValueError("withheld_title_present")
    else:
        raise ValueError("title_state_invalid")
    return {
        "ref": goal_ref,
        "title": title,
        "title_state": title_state,
        "lifecycle_state": lifecycle,
        "group": GROUPS[lifecycle],
        "first_observed_at": _iso_timestamp(value.get("first_observed_at")),
        "last_observed_at": _iso_timestamp(value.get("last_observed_at")),
        "ambiguity": bool(value.get("ambiguity")),
    }


def observe_goal_catalog(config: dict[str, Any]) -> dict[str, Any]:
    binding = config.get("goal_catalog_source")
    if not isinstance(binding, dict):
        return _empty("missing", "publisher_binding_missing")
    path = binding.get("path")
    if not isinstance(path, str) or not path:
        return _empty("missing", "publisher_path_missing")
    snapshot = read_file_snapshot(path, parser="json")
    base_ref = snapshot_ref(
        snapshot,
        label="Goal catalog",
        kind="goal_catalog_snapshot",
        owner=OWNER,
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="source_owner_metadata",
        claim_limit="Scope: owner-published Goal navigation.",
    )
    if snapshot.currentness == "missing":
        return _empty("missing", "publisher_missing", evidence_refs=[base_ref])
    if snapshot.currentness == "invalid" or not isinstance(snapshot.parsed, dict):
        return _empty("invalid", "publisher_unreadable", evidence_refs=[base_ref])
    payload = snapshot.parsed
    try:
        if payload.get("schema_version") != OWNER_SCHEMA:
            raise ValueError("publisher_schema_unsupported")
        if payload.get("artifact_type") != "goal_catalog_projection":
            raise ValueError("publisher_artifact_invalid")
        source = payload.get("source")
        if not isinstance(source, dict):
            raise ValueError("publisher_source_missing")
        if source.get("owner") != OWNER or source.get("ref") != SOURCE_REF:
            raise ValueError("publisher_owner_invalid")
        currentness = payload.get("currentness")
        if currentness not in CURRENTNESS or payload.get("state") != currentness:
            raise ValueError("publisher_currentness_invalid")
        if source.get("currentness") != currentness:
            raise ValueError("publisher_source_currentness_mismatch")
        values = payload.get("items")
        if not isinstance(values, list) or len(values) > 500:
            raise ValueError("publisher_items_invalid")
        items = [_item(value) for value in values]
        refs = [item["ref"] for item in items]
        if len(refs) != len(set(refs)):
            raise ValueError("publisher_duplicate_goal_ref")
        if payload.get("item_count") != len(items):
            raise ValueError("publisher_item_count_mismatch")
        claim_limit = payload.get("claim_limit")
        if not isinstance(claim_limit, str) or not claim_limit or len(claim_limit) > 320:
            raise ValueError("publisher_claim_limit_invalid")
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, list) or any(item not in OWNER_DIAGNOSTICS for item in diagnostics):
            raise ValueError("publisher_diagnostics_invalid")
    except ValueError as exc:
        return _empty("invalid", str(exc), evidence_refs=[base_ref])

    base_ref["currentness"] = currentness
    base_ref["freshness"] = currentness
    generation = source.get("generation_identity") if isinstance(source.get("generation_identity"), dict) else {}
    normalized_source = {
        "owner": OWNER,
        "ref": SOURCE_REF,
        "owner_schema_version": OWNER_SCHEMA,
        "currentness": currentness,
        "generation_id": generation.get("generation_id") if isinstance(generation.get("generation_id"), str) else None,
    }
    counts: dict[str, int] = {}
    for item in items:
        counts[item["group"]] = counts.get(item["group"], 0) + 1
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": currentness,
        "currentness": currentness,
        "generated_at": payload.get("generated_at"),
        "items": items,
        "counts_by_group": counts,
        "source": normalized_source,
        "evidence_refs": [base_ref],
        "diagnostics": diagnostics,
        "claim_limit": claim_limit,
    }
