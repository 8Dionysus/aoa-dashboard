"""Fail-closed admission for owner-published Goal navigation surfaces.

The dashboard may consume a path or an explicitly configured owner command,
but it never discovers a source by guessing a checkout, session, or Goal
identifier. Catalog pagination remains opaque to the adapter and browser.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .source_binding import FileSnapshot, is_sha256, loads_json, read_file_snapshot, snapshot_ref, utc_now


OWNER_SCHEMA = "aoa_session_memory_goal_catalog_v1"
PUBLICATION_SCHEMA = "aoa_session_memory_goal_catalog_public_v1"
DASHBOARD_SCHEMA = "aoa_dashboard_goal_catalog_projection_v1"
PROJECTION_OWNER_SCHEMA = "aoa_session_memory_goal_projection_v1"
PROJECTION_DASHBOARD_SCHEMA = "aoa_dashboard_goal_projection_v1"
OWNER = "aoa-session-memory"
SOURCE_REF = "aoa-session-memory:goal-lifecycles"
PROJECTION_SOURCE_REF = "aoa-session-memory:goal-projection"
CURRENTNESS = frozenset({"current", "stale", "deferred", "unknown", "invalid"})
PUBLICATION_STATES = frozenset({"current", "current_at_read", "stale", "deferred", "unknown", "invalid", "missing"})
PUBLIC_STATES = frozenset({"current", "missing", "unknown", "stale", "deferred", "invalid"})
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
MAX_PUBLICATION_BYTES = 4 * 1024 * 1024
LANGUAGE_RE = re.compile(r"^[a-z]{2}(?:-[A-Z]{2})?$")
PUBLIC_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PUBLIC_ITEM_FIELDS = frozenset(
    {
        "goal_ref",
        "goal_ref_state",
        "goal_instance_id",
        "goal_instance_id_state",
        "goal_id",
        "goal_id_state",
        "thread_id",
        "thread_id_state",
        "safe_title_state",
        "safe_title_reason",
        "title",
        "title_state",
        "reason",
        "lifecycle_state",
        "lifecycle_group",
        "thread_metadata_state",
        "relation_state",
        "first_observed_at",
        "last_observed_at",
        "evidence_ref",
        "ambiguity_state",
        "ambiguity",
        "redacted_fields",
        "item_digest",
    }
)


def _empty(state: str, reason: str, *, evidence_refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": state,
        "items": [],
        "counts_by_group": {},
        "pagination": {"mode": "snapshot", "cursor": None, "next_cursor": None, "complete": True},
        "source": None,
        "evidence_refs": evidence_refs or [],
        "diagnostics": [reason],
        "claim_limit": "Scope: owner-published Goal navigation.",
    }


def _publication_descriptor(binding: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return one explicit publication route without resolving any path."""

    nested = binding.get("publication")
    publication = nested if isinstance(nested, dict) else binding
    capability = publication.get("capability")
    if not isinstance(capability, str) or not capability.strip() or len(capability) > 256:
        if "command" in publication or isinstance(nested, dict):
            return None, "publisher_capability_missing"
        capability = "legacy-path-publication"
    capability = capability.strip()
    command = publication.get("command")
    path = publication.get("path", binding.get("path"))
    transport = publication.get("transport")
    if transport is None:
        transport = "command" if command is not None else "path"
    if transport not in {"path", "command"}:
        return None, "publisher_transport_invalid"
    result: dict[str, Any] = {
        "capability": capability,
        "transport": transport,
        "expected_sha256": publication.get("expected_sha256", binding.get("expected_sha256")),
        "timeout_seconds": publication.get("timeout_seconds", binding.get("timeout_seconds", 5)),
    }
    expected = result["expected_sha256"]
    if expected is not None and not is_sha256(expected):
        return None, "publisher_expected_digest_invalid"
    timeout = result["timeout_seconds"]
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
        return None, "publisher_timeout_invalid"
    if transport == "path":
        if not isinstance(path, str) or not path.strip() or not Path(path).is_absolute():
            return None, "publisher_path_missing"
        result["path"] = str(Path(path).resolve(strict=False))
    else:
        if not isinstance(command, list) or not command or len(command) > 64 or any(
            not isinstance(item, str) or not item.strip() or len(item) > 4096 or "\x00" in item
            for item in command
        ):
            return None, "publisher_command_invalid"
        result["command"] = list(command)
        cursor_arg = publication.get("cursor_arg", binding.get("cursor_arg"))
        if cursor_arg is not None:
            if not isinstance(cursor_arg, str) or not cursor_arg.strip() or len(cursor_arg) > 128 or any(
                character.isspace() for character in cursor_arg
            ):
                return None, "publisher_cursor_arg_invalid"
            result["cursor_arg"] = cursor_arg.strip()
        max_pages = publication.get(
            "max_pages",
            binding.get("max_pages", 64 if cursor_arg is not None else 1),
        )
        if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= 128:
            return None, "publisher_max_pages_invalid"
        result["max_pages"] = max_pages
    return result, None


def _command_snapshot(publication: dict[str, Any], *, cursor: str | None = None) -> FileSnapshot:
    capability = publication["capability"]
    evidence_path = Path(f"capability:{re.sub(r'[^A-Za-z0-9_.:-]+', '_', capability)}")
    observed_at = utc_now()
    command = list(publication["command"])
    if cursor is not None:
        cursor_arg = publication.get("cursor_arg")
        if not isinstance(cursor_arg, str) or not cursor_arg:
            return FileSnapshot(
                evidence_path,
                None,
                None,
                None,
                "invalid",
                publication.get("expected_sha256"),
                None,
                "publication cursor argument is not configured",
                observed_at,
            )
        command.extend([cursor_arg, cursor])
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=float(publication["timeout_seconds"]),
        )
    except subprocess.TimeoutExpired:
        return FileSnapshot(evidence_path, None, None, None, "stale", publication.get("expected_sha256"), None, "publication command timed out", observed_at)
    except (OSError, ValueError) as exc:
        return FileSnapshot(evidence_path, None, None, None, "invalid", publication.get("expected_sha256"), None, str(exc), observed_at)
    raw = completed.stdout if isinstance(completed.stdout, bytes) else b""
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) > MAX_PUBLICATION_BYTES:
        return FileSnapshot(evidence_path, raw[:MAX_PUBLICATION_BYTES], digest, None, "invalid", publication.get("expected_sha256"), None, "publication output exceeded limit", observed_at)
    parsed: Any = None
    parse_error: str | None = None
    try:
        parsed = loads_json(raw.decode("utf-8"), reject_duplicate_keys=True)
        if not isinstance(parsed, dict):
            parsed = None
            parse_error = "top-level JSON value is not an object"
    except (UnicodeError, ValueError) as exc:
        parse_error = "publication output is not valid JSON"
        if "duplicate JSON object name" in str(exc):
            parse_error = "duplicate JSON object name"
    if parse_error:
        return FileSnapshot(evidence_path, raw, digest, None, "invalid", publication.get("expected_sha256"), parse_error, None, observed_at)
    if publication.get("expected_sha256") is not None and digest != publication["expected_sha256"]:
        return FileSnapshot(evidence_path, raw, digest, parsed, "stale", publication.get("expected_sha256"), None, None, observed_at)
    return FileSnapshot(
        evidence_path,
        raw,
        digest,
        parsed,
        "current_at_read",
        publication.get("expected_sha256"),
        None,
        "publication command failed" if completed.returncode != 0 else None,
        observed_at,
    )


def _read_publication(binding: dict[str, Any], *, goal_ref: str | None = None) -> tuple[FileSnapshot | None, dict[str, Any] | None, str | None]:
    publication, error = _publication_descriptor(binding)
    if publication is None:
        return None, None, error
    if goal_ref is not None and publication["transport"] == "command":
        goal_ref_arg = binding.get("goal_ref_arg")
        nested = binding.get("publication")
        if isinstance(nested, dict):
            goal_ref_arg = nested.get("goal_ref_arg", goal_ref_arg)
        if not isinstance(goal_ref_arg, str) or not goal_ref_arg.strip() or "\n" in goal_ref_arg or "\x00" in goal_ref_arg:
            return None, publication, "per_goal_goal_ref_argument_missing"
        publication["command"] = [*publication["command"], goal_ref_arg, goal_ref]
    if publication["transport"] == "command":
        return _command_snapshot(publication), publication, None
    return read_file_snapshot(
        publication["path"],
        expected_digest=publication.get("expected_sha256"),
        parser="json",
        reject_duplicate_keys=True,
    ), publication, None


def _publication_ref(snapshot: FileSnapshot, publication: dict[str, Any], *, label: str, claim_limit: str) -> dict[str, Any]:
    ref = snapshot_ref(
        snapshot,
        label=label,
        kind="goal_catalog_publication" if "catalog" in label.lower() else "goal_projection_publication",
        owner=OWNER,
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="source_owner_metadata",
        claim_limit=claim_limit,
    )
    if publication.get("transport") == "command":
        ref["ref"] = f"capability:{publication['capability']}"
        ref["publication_capability"] = publication["capability"]
    return ref


def _pagination(value: Any) -> dict[str, Any]:
    if value is None:
        return {"mode": "snapshot", "cursor": None, "next_cursor": None, "complete": True}
    if not isinstance(value, dict):
        raise ValueError("publisher_pagination_invalid")
    cursor = value.get("cursor")
    next_cursor = value.get("next_cursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 512):
        raise ValueError("publisher_cursor_invalid")
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > 512):
        raise ValueError("publisher_next_cursor_invalid")
    complete = value.get("complete", next_cursor is None)
    if not isinstance(complete, bool):
        raise ValueError("publisher_pagination_complete_invalid")
    mode = value.get("mode")
    if mode is None:
        mode = "opaque_cursor" if cursor is not None or next_cursor is not None else "snapshot"
    if mode not in {"snapshot", "opaque_cursor"}:
        raise ValueError("publisher_pagination_mode_invalid")
    if mode == "snapshot" and (cursor is not None or next_cursor is not None):
        raise ValueError("publisher_snapshot_cursor_invalid")
    return {"mode": mode, "cursor": cursor, "next_cursor": next_cursor, "complete": complete}


def _human_title(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 96:
        raise ValueError("human_title_invalid")
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value) or TECHNICAL_TITLE_RE.search(value):
        raise ValueError("human_title_invalid")
    return " ".join(value.split())


def _localized_titles(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict) or len(value) > 8:
        raise ValueError("localized_title_invalid")
    result: dict[str, str] = {}
    for language, title in value.items():
        if not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language):
            raise ValueError("localized_title_language_invalid")
        result[language] = _human_title(title)
    return result


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
        title = _human_title(title) if title is not None else None
        title_by_locale = _localized_titles(value.get("title_by_locale"))
        if title is None and not title_by_locale:
            raise ValueError("human_title_invalid")
        title_locale = value.get("title_locale")
        if title_locale is not None and (not isinstance(title_locale, str) or not LANGUAGE_RE.fullmatch(title_locale)):
            raise ValueError("title_locale_invalid")
    elif title_state in {"missing", "withheld"}:
        if title is not None:
            raise ValueError("withheld_title_present")
        if value.get("title_by_locale") is not None:
            raise ValueError("withheld_title_present")
        title_by_locale = {}
        title_locale = None
    else:
        raise ValueError("title_state_invalid")
    result = {
        "ref": goal_ref,
        "title": title,
        "title_state": title_state,
        "lifecycle_state": lifecycle,
        "group": GROUPS[lifecycle],
        "first_observed_at": _iso_timestamp(value.get("first_observed_at")),
        "last_observed_at": _iso_timestamp(value.get("last_observed_at")),
        "ambiguity": bool(value.get("ambiguity")),
    }
    if title_state == "available" and title_by_locale:
        result["title_by_locale"] = title_by_locale
    if title_state == "available" and title_locale is not None:
        result["title_locale"] = title_locale
    return result


def _public_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not PUBLIC_DIGEST_RE.fullmatch(value):
        raise ValueError(f"publisher_{field}_invalid")
    return value


def _public_count(value: Any, field: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"publisher_{field}_invalid")
    return value


def _public_watermark(value: Any, field: str) -> dict[str, Any]:
    required = {
        "schema_version",
        "kind",
        "registry_digest",
        "source_set_digest",
        "session_count",
        "goal_lifecycle_count",
        "coverage",
        "max_updated_at",
        "max_raw_line_count",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError(f"publisher_{field}_invalid")
    if value["schema_version"] != 1 or value["kind"] != "complete_session_index_set_v1":
        raise ValueError(f"publisher_{field}_invalid")
    if value["registry_digest"] is not None and not isinstance(value["registry_digest"], str):
        raise ValueError(f"publisher_{field}_invalid")
    _public_digest(value["source_set_digest"], f"{field}_source_set_digest")
    _public_count(value["session_count"], f"{field}_session_count")
    _public_count(value["goal_lifecycle_count"], f"{field}_goal_lifecycle_count")
    if value["coverage"] not in {"complete", "incomplete"} or not isinstance(value["max_updated_at"], str):
        raise ValueError(f"publisher_{field}_invalid")
    _public_count(value["max_raw_line_count"], f"{field}_max_raw_line_count")
    return dict(value)


def _public_lifecycle_group(value: Any) -> dict[str, Any]:
    required = {
        "group_ref",
        "grouping_basis",
        "member_count",
        "current_member_count",
        "historical_member_count",
        "unknown_member_count",
        "states",
        "history_state",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("publisher_lifecycle_group_invalid")
    if not isinstance(value["group_ref"], str) or not value["group_ref"] or len(value["group_ref"]) > 512:
        raise ValueError("publisher_lifecycle_group_invalid")
    if value["grouping_basis"] not in {"thread_id", "goal_instance_id"} or value["history_state"] != "complete":
        raise ValueError("publisher_lifecycle_group_invalid")
    member_count = _public_count(value["member_count"], "lifecycle_group_member_count", minimum=1)
    current_count = _public_count(value["current_member_count"], "lifecycle_group_current_member_count")
    historical_count = _public_count(value["historical_member_count"], "lifecycle_group_historical_member_count")
    unknown_count = _public_count(value["unknown_member_count"], "lifecycle_group_unknown_member_count")
    if current_count + historical_count + unknown_count != member_count:
        raise ValueError("publisher_lifecycle_group_counts_invalid")
    states = value["states"]
    if not isinstance(states, list) or not states or len(states) > 32 or any(
        not isinstance(state, str) or not state or len(state) > 64 for state in states
    ):
        raise ValueError("publisher_lifecycle_group_states_invalid")
    return {
        "group_ref": value["group_ref"],
        "grouping_basis": value["grouping_basis"],
        "member_count": member_count,
        "current_member_count": current_count,
        "historical_member_count": historical_count,
        "unknown_member_count": unknown_count,
        "states": list(states),
        "history_state": "complete",
    }


def _public_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PUBLIC_ITEM_FIELDS:
        raise ValueError("publisher_item_fields_invalid")
    for field in ("goal_ref", "goal_instance_id", "evidence_ref"):
        if not isinstance(value[field], str) or not value[field] or len(value[field]) > 512:
            raise ValueError(f"publisher_{field}_invalid")
    for field in ("goal_ref_state", "goal_instance_id_state", "goal_id_state", "thread_id_state"):
        if value[field] not in {"available", "opaque", "missing"}:
            raise ValueError(f"publisher_{field}_invalid")
    for field in ("goal_id", "thread_id"):
        if value[field] is not None and (not isinstance(value[field], str) or len(value[field]) > 512):
            raise ValueError(f"publisher_{field}_invalid")
    title_state = value["title_state"]
    if title_state not in {"available", "missing", "withheld"} or value["safe_title_state"] != title_state:
        raise ValueError("publisher_title_state_invalid")
    if value["safe_title_reason"] not in {"private_objective_omitted", "objective_missing"} or value["reason"] != value["safe_title_reason"]:
        raise ValueError("publisher_title_reason_invalid")
    title = value["title"]
    if title_state == "available":
        title = _human_title(title)
    elif title is not None:
        raise ValueError("publisher_withheld_title_present")
    lifecycle = value["lifecycle_state"]
    if not isinstance(lifecycle, str) or not lifecycle or len(lifecycle) > 64 or lifecycle not in LIFECYCLE_STATES:
        raise ValueError("publisher_lifecycle_state_invalid")
    group = _public_lifecycle_group(value["lifecycle_group"])
    for field in ("thread_metadata_state",):
        if value[field] not in {"available", "missing", "unknown", "invalid"}:
            raise ValueError(f"publisher_{field}_invalid")
    if value["relation_state"] not in {"complete", "deferred", "missing", "unknown", "invalid"}:
        raise ValueError("publisher_relation_state_invalid")
    first = _iso_timestamp(value["first_observed_at"])
    last = _iso_timestamp(value["last_observed_at"])
    ambiguity_state = value["ambiguity_state"]
    if ambiguity_state not in {"present", "none"} or (ambiguity_state == "present") != bool(value["ambiguity"]):
        raise ValueError("publisher_ambiguity_invalid")
    redacted = value["redacted_fields"]
    if not isinstance(redacted, list) or len(redacted) > 64 or any(
        not isinstance(field, str) or not field or len(field) > 128 for field in redacted
    ):
        raise ValueError("publisher_redacted_fields_invalid")
    item_digest = _public_digest(value["item_digest"], "item_digest")
    return {
        "ref": value["goal_ref"],
        "title": title,
        "title_state": title_state,
        "lifecycle_state": lifecycle,
        "group": GROUPS[lifecycle],
        "first_observed_at": first,
        "last_observed_at": last,
        "ambiguity": bool(value["ambiguity"]),
        "evidence_ref": value["evidence_ref"],
        "lifecycle_group": group,
        "thread_metadata_state": value["thread_metadata_state"],
        "relation_state": value["relation_state"],
        "ambiguity_state": ambiguity_state,
        "redacted_fields": list(redacted),
        "item_digest": item_digest,
    }


def _validate_public_page(payload: Any) -> dict[str, Any]:
    required = {
        "schema_version",
        "publication_schema_version",
        "artifact_type",
        "generated_at",
        "ok",
        "state",
        "currentness",
        "publication_state",
        "target",
        "order",
        "source",
        "source_generation",
        "source_watermark",
        "snapshot",
        "pagination",
        "page",
        "snapshot_digest",
        "page_digest",
        "source_item_count",
        "item_count",
        "total_item_count",
        "lifecycle_group_count",
        "counts_by_lifecycle_state",
        "items",
        "diagnostics",
        "omissions",
        "privacy",
        "claim_limit",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("publisher_public_fields_invalid")
    if payload["schema_version"] != OWNER_SCHEMA or payload["publication_schema_version"] != PUBLICATION_SCHEMA:
        raise ValueError("publisher_schema_unsupported")
    state = payload["state"]
    if state not in PUBLIC_STATES or payload["currentness"] != state:
        raise ValueError("publisher_currentness_invalid")
    if payload["ok"] is not (state == "current"):
        raise ValueError("publisher_ok_state_mismatch")
    expected_publication_state = "bound" if state == "current" else state
    if payload["publication_state"] != expected_publication_state:
        raise ValueError("publisher_publication_state_invalid")
    if not isinstance(payload["generated_at"], str) or not payload["generated_at"]:
        raise ValueError("publisher_generated_at_invalid")
    if not isinstance(payload["target"], str) or not payload["target"] or len(payload["target"]) > 512:
        raise ValueError("publisher_target_invalid")
    if payload["order"] not in {"recent", "chronological"}:
        raise ValueError("publisher_order_invalid")
    source = payload["source"]
    source_fields = {
        "owner",
        "ref",
        "goal_lifecycle_schema_version",
        "generation_identity",
        "goal_lifecycle_generation",
        "watermark",
        "currentness",
    }
    if not isinstance(source, dict) or set(source) != source_fields:
        raise ValueError("publisher_source_invalid")
    if source["owner"] != OWNER or source["ref"] != SOURCE_REF or not isinstance(source["goal_lifecycle_schema_version"], int) or isinstance(source["goal_lifecycle_schema_version"], bool):
        raise ValueError("publisher_owner_invalid")
    if not isinstance(source["generation_identity"], dict) or not isinstance(source["goal_lifecycle_generation"], dict):
        raise ValueError("publisher_generation_invalid")
    if source["currentness"] not in PUBLIC_STATES:
        raise ValueError("publisher_source_currentness_invalid")
    watermark = _public_watermark(payload["source_watermark"], "source_watermark")
    if _public_watermark(source["watermark"], "source_watermark_nested") != watermark:
        raise ValueError("publisher_source_watermark_mismatch")
    if not isinstance(payload["source_generation"], dict) or payload["source_generation"] != source["generation_identity"]:
        raise ValueError("publisher_source_generation_mismatch")
    snapshot = payload["snapshot"]
    snapshot_fields = {"snapshot_ref", "snapshot_digest", "generated_at", "source_watermark", "source_freshness", "projection_freshness", "immutable"}
    if not isinstance(snapshot, dict) or set(snapshot) != snapshot_fields:
        raise ValueError("publisher_snapshot_invalid")
    snapshot_digest = _public_digest(payload["snapshot_digest"], "snapshot_digest")
    if snapshot["snapshot_ref"] != snapshot_digest or snapshot["snapshot_digest"] != snapshot_digest or snapshot["immutable"] is not True:
        raise ValueError("publisher_snapshot_digest_invalid")
    if snapshot["source_watermark"] != watermark or snapshot["source_freshness"] != source["currentness"] or snapshot["projection_freshness"] != state:
        raise ValueError("publisher_snapshot_currentness_invalid")
    pagination = payload["pagination"]
    pagination_fields = {"mode", "cursor", "next_cursor", "complete_for_query", "page_size", "supports_immutable_snapshot"}
    if not isinstance(pagination, dict) or set(pagination) != pagination_fields or pagination["mode"] != "immutable_snapshot":
        raise ValueError("publisher_pagination_invalid")
    for field in ("cursor", "next_cursor"):
        if pagination[field] is not None and (not isinstance(pagination[field], str) or len(pagination[field]) > 512):
            raise ValueError(f"publisher_{field}_invalid")
    if not isinstance(pagination["complete_for_query"], bool) or not isinstance(pagination["page_size"], int) or isinstance(pagination["page_size"], bool) or pagination["page_size"] <= 0 or pagination["supports_immutable_snapshot"] is not True:
        raise ValueError("publisher_pagination_invalid")
    if pagination["complete_for_query"] != (pagination["next_cursor"] is None):
        raise ValueError("publisher_pagination_completion_invalid")
    page = payload["page"]
    if not isinstance(page, dict) or set(page) != {"offset", "item_count", "page_digest"}:
        raise ValueError("publisher_page_invalid")
    _public_count(page["offset"], "page_offset")
    _public_count(page["item_count"], "page_item_count")
    page_digest = _public_digest(payload["page_digest"], "page_digest")
    if page["page_digest"] != page_digest:
        raise ValueError("publisher_page_digest_invalid")
    items = payload["items"]
    if not isinstance(items, list) or len(items) > 500:
        raise ValueError("publisher_items_invalid")
    if page["item_count"] != len(items) or payload["item_count"] != len(items):
        raise ValueError("publisher_item_count_mismatch")
    if state != "current" and items:
        raise ValueError("publisher_negative_items_present")
    normalized_items = [_public_item(item) for item in items]
    refs = [item["ref"] for item in normalized_items]
    if len(refs) != len(set(refs)):
        raise ValueError("publisher_duplicate_goal_ref")
    for field in ("source_item_count", "item_count", "total_item_count", "lifecycle_group_count"):
        _public_count(payload[field], field)
    if payload["source_item_count"] != payload["total_item_count"] or payload["total_item_count"] < payload["item_count"]:
        raise ValueError("publisher_total_item_count_mismatch")
    counts = payload["counts_by_lifecycle_state"]
    if not isinstance(counts, dict) or any(
        not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0
        for key, value in counts.items()
    ):
        raise ValueError("publisher_counts_invalid")
    if state != "current" and counts:
        raise ValueError("publisher_negative_counts_present")
    diagnostics = payload["diagnostics"]
    if not isinstance(diagnostics, list) or len(diagnostics) > 256 or any(
        not isinstance(item, str) or not item or len(item) > 512 for item in diagnostics
    ):
        raise ValueError("publisher_diagnostics_invalid")
    omissions = payload["omissions"]
    if not isinstance(omissions, dict) or any(value is not True for value in omissions.values()):
        raise ValueError("publisher_omissions_invalid")
    privacy = payload["privacy"]
    privacy_fields = {
        "scope",
        "allowlisted_fields",
        "withheld_fields",
        "prohibited_join_keys",
        "no_transcript_body",
        "no_process_identity",
        "no_actor_inference",
    }
    if not isinstance(privacy, dict) or set(privacy) != privacy_fields or privacy["scope"] != "owner_bounded_public_safe" or any(
        privacy[field] is not True for field in ("no_transcript_body", "no_process_identity", "no_actor_inference")
    ):
        raise ValueError("publisher_privacy_invalid")
    for field in ("allowlisted_fields", "withheld_fields", "prohibited_join_keys"):
        if not isinstance(privacy[field], list) or any(not isinstance(item, str) or not item for item in privacy[field]):
            raise ValueError("publisher_privacy_fields_invalid")
    if not isinstance(payload["claim_limit"], str) or not payload["claim_limit"] or len(payload["claim_limit"]) > 640:
        raise ValueError("publisher_claim_limit_invalid")
    return {
        "state": state,
        "source": source,
        "source_generation": payload["source_generation"],
        "source_watermark": watermark,
        "snapshot": snapshot,
        "snapshot_digest": snapshot_digest,
        "pagination": dict(pagination),
        "page": dict(page),
        "items": normalized_items,
        "counts_by_lifecycle_state": dict(counts),
        "generated_at": payload["generated_at"],
        "target": payload["target"],
        "order": payload["order"],
        "diagnostics": list(diagnostics),
        "omissions": dict(omissions),
        "privacy": privacy,
        "claim_limit": payload["claim_limit"],
        "total_item_count": payload["total_item_count"],
        "source_item_count": payload["source_item_count"],
    }


def _normalized_public_source(page: dict[str, Any]) -> dict[str, Any]:
    source = page["source"]
    return {
        "owner": OWNER,
        "ref": SOURCE_REF,
        "owner_schema_version": OWNER_SCHEMA,
        "publication_schema_version": PUBLICATION_SCHEMA,
        "goal_lifecycle_schema_version": source["goal_lifecycle_schema_version"],
        "currentness": source["currentness"],
        "generation_identity": source["generation_identity"],
        "goal_lifecycle_generation": source["goal_lifecycle_generation"],
        "watermark": page["source_watermark"],
        "snapshot": page["snapshot"],
        "snapshot_digest": page["snapshot_digest"],
        "target": page["target"],
        "order": page["order"],
    }


def _normalized_public_page(page: dict[str, Any], evidence_refs: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in page["items"]:
        group = item["group"]
        counts[group] = counts.get(group, 0) + 1
    pagination = page["pagination"]
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": page["state"],
        "currentness": page["state"],
        "generated_at": page["generated_at"],
        "items": page["items"],
        "counts_by_group": counts,
        "pagination": {
            "mode": "immutable_snapshot",
            "cursor": pagination["cursor"],
            "next_cursor": pagination["next_cursor"],
            "complete": pagination["complete_for_query"],
            "complete_for_query": pagination["complete_for_query"],
            "page_size": pagination["page_size"],
            "supports_immutable_snapshot": True,
        },
        "source": _normalized_public_source(page),
        "source_watermark": page["source_watermark"],
        "snapshot": page["snapshot"],
        "snapshot_digest": page["snapshot_digest"],
        "page_digest": page["page"]["page_digest"],
        "target": page["target"],
        "order": page["order"],
        "publication_schema_version": PUBLICATION_SCHEMA,
        "omissions": page["omissions"],
        "privacy": page["privacy"],
        "evidence_refs": evidence_refs,
        "diagnostics": page["diagnostics"],
        "claim_limit": page["claim_limit"],
    }


def _dashboard_page_digest(items: list[dict[str, Any]], snapshot_digest: str) -> str:
    encoded = json.dumps(
        {"snapshot_digest": snapshot_digest, "items": items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _observe_public_catalog(
    binding: dict[str, Any],
    first_snapshot: FileSnapshot,
    publication: dict[str, Any],
) -> dict[str, Any]:
    first_ref = _publication_ref(
        first_snapshot,
        publication,
        label="Goal catalog",
        claim_limit="Scope: owner-published Goal navigation.",
    )
    evidence_refs = [first_ref]
    if first_snapshot.currentness == "missing":
        return _empty("missing", "publisher_missing", evidence_refs=evidence_refs)
    if first_snapshot.currentness == "stale":
        return _empty("stale", "publisher_stale", evidence_refs=evidence_refs)
    if first_snapshot.currentness == "invalid" or not isinstance(first_snapshot.parsed, dict):
        return _empty("invalid", "publisher_unreadable", evidence_refs=evidence_refs)
    try:
        first_page = _validate_public_page(first_snapshot.parsed)
    except ValueError as exc:
        return _empty("invalid", str(exc), evidence_refs=evidence_refs)
    if first_page["state"] != "current":
        first_ref["currentness"] = first_page["state"]
        first_ref["freshness"] = first_page["state"]
        return _normalized_public_page(first_page, evidence_refs)
    if first_page["pagination"]["cursor"] is not None or first_page["page"]["offset"] != 0:
        return _empty("invalid", "publisher_initial_page_not_root", evidence_refs=evidence_refs)

    pages = [first_page]
    cursor = first_page["pagination"]["next_cursor"]
    expected_snapshot_digest = first_page["snapshot_digest"]
    expected_offset = len(first_page["items"])
    max_pages = publication.get("max_pages", 1) if publication.get("transport") == "command" else 1
    cursor_route_available = publication.get("transport") == "command" and isinstance(publication.get("cursor_arg"), str)
    while cursor and cursor_route_available and len(pages) < max_pages:
        snapshot = _command_snapshot(publication, cursor=cursor)
        page_ref = _publication_ref(
            snapshot,
            publication,
            label=f"Goal catalog page {len(pages) + 1}",
            claim_limit="Scope: owner-published Goal navigation.",
        )
        evidence_refs.append(page_ref)
        if snapshot.currentness != "current_at_read" or not isinstance(snapshot.parsed, dict):
            return _empty("invalid", "publisher_page_unreadable", evidence_refs=evidence_refs)
        try:
            page = _validate_public_page(snapshot.parsed)
        except ValueError as exc:
            return _empty("invalid", str(exc), evidence_refs=evidence_refs)
        if page["state"] != "current":
            return _empty(page["state"], "publisher_page_not_current", evidence_refs=evidence_refs)
        if page["snapshot_digest"] != expected_snapshot_digest:
            return _empty("stale", "publisher_snapshot_changed", evidence_refs=evidence_refs)
        if page["pagination"]["cursor"] != cursor or page["page"]["offset"] != expected_offset:
            return _empty("invalid", "publisher_page_cursor_mismatch", evidence_refs=evidence_refs)
        pages.append(page)
        expected_offset += len(page["items"])
        cursor = page["pagination"]["next_cursor"]

    if cursor and cursor_route_available and len(pages) >= max_pages:
        return _empty("deferred", "publisher_page_limit_reached", evidence_refs=evidence_refs)

    if len(pages) == 1 and not cursor_route_available:
        return _normalized_public_page(first_page, evidence_refs)

    items: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for page in pages:
        items.extend(page["items"])
        diagnostics.extend(page["diagnostics"])
    refs = [item["ref"] for item in items]
    if len(refs) != len(set(refs)):
        return _empty("invalid", "publisher_duplicate_goal_ref", evidence_refs=evidence_refs)
    aggregate = dict(pages[0])
    aggregate["items"] = items
    aggregate["diagnostics"] = list(dict.fromkeys(diagnostics))
    aggregate["pagination"] = dict(pages[-1]["pagination"])
    aggregate["pagination"]["cursor"] = pages[0]["pagination"]["cursor"]
    aggregate["page"] = {
        "offset": 0,
        "item_count": len(items),
        "page_digest": _dashboard_page_digest(items, expected_snapshot_digest),
    }
    if aggregate["total_item_count"] != len(items) or not aggregate["pagination"]["complete_for_query"]:
        return _empty("invalid", "publisher_page_count_mismatch", evidence_refs=evidence_refs)
    normalized = _normalized_public_page(aggregate, evidence_refs)
    normalized["owner_page_digests"] = [page["page"]["page_digest"] for page in pages]
    normalized["owner_page_count"] = len(pages)
    return normalized


def observe_goal_catalog(config: dict[str, Any]) -> dict[str, Any]:
    binding = config.get("goal_catalog_source")
    if not isinstance(binding, dict):
        return _empty("missing", "publisher_binding_missing")
    snapshot, publication, publication_error = _read_publication(binding)
    if snapshot is None or publication is None:
        state = "missing" if publication_error in {"publisher_path_missing", "publisher_capability_missing"} else "invalid"
        return _empty(state, publication_error or "publisher_binding_invalid")
    base_ref = _publication_ref(snapshot, publication, label="Goal catalog", claim_limit="Scope: owner-published Goal navigation.")
    if snapshot.currentness == "missing":
        return _empty("missing", "publisher_missing", evidence_refs=[base_ref])
    if snapshot.currentness == "stale":
        return _empty("stale", "publisher_stale", evidence_refs=[base_ref])
    if snapshot.currentness == "invalid" or not isinstance(snapshot.parsed, dict):
        return _empty("invalid", "publisher_unreadable", evidence_refs=[base_ref])
    payload = snapshot.parsed
    if payload.get("publication_schema_version") == PUBLICATION_SCHEMA:
        return _observe_public_catalog(binding, snapshot, publication)
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
        item_count = payload.get("item_count")
        page_item_count = payload.get("page_item_count")
        if not isinstance(item_count, int) or isinstance(item_count, bool) or item_count < len(items):
            raise ValueError("publisher_item_count_mismatch")
        if page_item_count is not None and (not isinstance(page_item_count, int) or isinstance(page_item_count, bool) or page_item_count != len(items)):
            raise ValueError("publisher_page_item_count_mismatch")
        if page_item_count is None and item_count != len(items):
            raise ValueError("publisher_item_count_mismatch")
        claim_limit = payload.get("claim_limit")
        if not isinstance(claim_limit, str) or not claim_limit or len(claim_limit) > 320:
            raise ValueError("publisher_claim_limit_invalid")
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, list) or any(item not in OWNER_DIAGNOSTICS for item in diagnostics):
            raise ValueError("publisher_diagnostics_invalid")
        pagination = _pagination(payload.get("pagination"))
        counts_value = payload.get("counts_by_group")
        if counts_value is not None:
            if not isinstance(counts_value, dict) or any(
                not isinstance(key, str) or not isinstance(value, int) or isinstance(value, bool) or value < 0
                for key, value in counts_value.items()
            ):
                raise ValueError("publisher_counts_invalid")
            counts = {key: value for key, value in counts_value.items() if key in GROUPS.values()}
        else:
            counts = {}
        if pagination["complete"] and item_count != len(items):
            raise ValueError("publisher_item_count_mismatch")
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
    if not counts:
        counts = {}
        for item in items:
            counts[item["group"]] = counts.get(item["group"], 0) + 1
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": currentness,
        "currentness": currentness,
        "generated_at": payload.get("generated_at"),
        "items": items,
        "counts_by_group": counts,
        "pagination": pagination,
        "omissions": payload.get("omissions", {}) if isinstance(payload.get("omissions"), dict) else {},
        "source": normalized_source,
        "evidence_refs": [base_ref],
        "diagnostics": diagnostics,
        "claim_limit": claim_limit,
    }


def _empty_goal_projection(
    goal_ref: str | None,
    state: str,
    reason: str,
    *,
    evidence_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PROJECTION_DASHBOARD_SCHEMA,
        "state": state,
        "currentness": state,
        "goal_ref": goal_ref,
        "title": None,
        "title_state": "missing",
        "lifecycle_state": "unknown",
        "summary": None,
        "presentation": {},
        "public_items": [],
        "omissions": {},
        "pagination": {"mode": "snapshot", "cursor": None, "next_cursor": None, "complete": True},
        "source": None,
        "evidence_refs": evidence_refs or [],
        "diagnostics": [reason],
        "claim_limit": "Scope: owner-qualified per-Goal public-safe projection; no dashboard Goal semantics or acceptance.",
    }


def _public_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 200:
        raise ValueError("public_items_invalid")
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("public_safe") is not True:
            raise ValueError("public_item_not_admitted")
        if item.get("kind") not in {"goal", "branch", "thread", "trajectory", "attention"}:
            raise ValueError("public_item_kind_invalid")
        safe = {
            key: item[key]
            for key in ("kind", "ref", "title", "state", "summary", "parent_ref", "thread_ref", "goal_ref")
            if key in item
        }
        if not isinstance(safe.get("ref"), str) or not safe["ref"]:
            raise ValueError("public_item_ref_invalid")
        items.append(safe)
    return items


def observe_goal_projection(
    config: dict[str, Any],
    goal_ref: str | None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read one exact owner-qualified projection after catalog admission."""

    if not isinstance(goal_ref, str) or not goal_ref:
        return _empty_goal_projection(goal_ref, "missing", "selected_goal_missing")
    catalog_value = catalog if isinstance(catalog, dict) else observe_goal_catalog(config)
    if catalog_value.get("state") in {"missing", "invalid"}:
        return _empty_goal_projection(goal_ref, "deferred", "per_goal_catalog_not_admitted")
    if not any(isinstance(item, dict) and item.get("ref") == goal_ref for item in catalog_value.get("items", [])):
        return _empty_goal_projection(goal_ref, "missing", "selected_goal_not_in_catalog")
    binding = config.get("goal_projection_source")
    if not isinstance(binding, dict):
        return _empty_goal_projection(goal_ref, "deferred", "per_goal_publisher_missing")
    snapshot, publication, publication_error = _read_publication(binding, goal_ref=goal_ref)
    if snapshot is None or publication is None:
        state = "deferred" if publication_error == "per_goal_goal_ref_argument_missing" else "invalid"
        return _empty_goal_projection(goal_ref, state, publication_error or "per_goal_publisher_invalid")
    evidence = _publication_ref(
        snapshot,
        publication,
        label="Goal projection",
        claim_limit="Scope: owner-qualified per-Goal public-safe projection; no dashboard Goal semantics or acceptance.",
    )
    if snapshot.currentness == "missing":
        return _empty_goal_projection(goal_ref, "missing", "per_goal_publisher_missing", evidence_refs=[evidence])
    if snapshot.currentness == "stale":
        return _empty_goal_projection(goal_ref, "stale", "per_goal_publisher_stale", evidence_refs=[evidence])
    if snapshot.currentness == "invalid" or not isinstance(snapshot.parsed, dict):
        return _empty_goal_projection(goal_ref, "invalid", "per_goal_publisher_unreadable", evidence_refs=[evidence])
    payload = snapshot.parsed
    try:
        if payload.get("schema_version") != PROJECTION_OWNER_SCHEMA:
            raise ValueError("per_goal_schema_unsupported")
        if payload.get("artifact_type") not in {"goal_projection", "goal_projection_public"}:
            raise ValueError("per_goal_artifact_invalid")
        currentness = payload.get("currentness")
        if currentness not in CURRENTNESS or payload.get("state") != currentness:
            raise ValueError("per_goal_currentness_invalid")
        source = payload.get("source")
        if not isinstance(source, dict) or source.get("owner") != OWNER or not isinstance(source.get("ref"), str) or not source.get("ref"):
            raise ValueError("per_goal_owner_invalid")
        if source.get("currentness") != currentness:
            raise ValueError("per_goal_source_currentness_mismatch")
        if payload.get("goal_ref") != goal_ref:
            raise ValueError("per_goal_goal_ref_mismatch")
        title_state = payload.get("title_state", "missing")
        title = payload.get("title")
        if title_state == "available":
            title = _human_title(title) if title is not None else None
            title_by_locale = _localized_titles(payload.get("title_by_locale"))
            if title is None and not title_by_locale:
                raise ValueError("per_goal_title_invalid")
            title_locale = payload.get("title_locale")
            if title_locale is not None and (not isinstance(title_locale, str) or not LANGUAGE_RE.fullmatch(title_locale)):
                raise ValueError("per_goal_title_locale_invalid")
        elif title_state in {"missing", "withheld"} and title is None:
            title_by_locale = {}
            title_locale = None
        else:
            raise ValueError("per_goal_title_invalid")
        projection = payload.get("projection") if isinstance(payload.get("projection"), dict) else payload
        lifecycle_state = projection.get("lifecycle_state", payload.get("lifecycle_state", "unknown"))
        if not isinstance(lifecycle_state, str) or not lifecycle_state or len(lifecycle_state) > 64:
            raise ValueError("per_goal_lifecycle_invalid")
        summary = projection.get("summary", payload.get("summary"))
        if summary is not None and not isinstance(summary, (str, dict)):
            raise ValueError("per_goal_summary_invalid")
        public_items = _public_items(projection.get("public_items", payload.get("public_items")))
        pagination = _pagination(projection.get("pagination", payload.get("pagination")))
        omissions = projection.get("omissions", payload.get("omissions", {}))
        if not isinstance(omissions, dict):
            raise ValueError("per_goal_omissions_invalid")
        claim_limit = payload.get("claim_limit")
        if not isinstance(claim_limit, str) or not claim_limit or len(claim_limit) > 640:
            raise ValueError("per_goal_claim_limit_invalid")
    except ValueError as exc:
        return _empty_goal_projection(goal_ref, "invalid", str(exc), evidence_refs=[evidence])
    evidence["currentness"] = currentness
    evidence["freshness"] = currentness
    generation = source.get("generation_identity") if isinstance(source.get("generation_identity"), dict) else {}
    result: dict[str, Any] = {
        "schema_version": PROJECTION_DASHBOARD_SCHEMA,
        "state": currentness,
        "currentness": currentness,
        "goal_ref": goal_ref,
        "title": title,
        "title_state": title_state,
        "lifecycle_state": lifecycle_state,
        "summary": summary,
        "presentation": projection.get("presentation", {}) if isinstance(projection.get("presentation"), dict) else {},
        "public_items": public_items,
        "omissions": omissions,
        "pagination": pagination,
        "source": {
            "owner": OWNER,
            "ref": source["ref"],
            "owner_schema_version": PROJECTION_OWNER_SCHEMA,
            "currentness": currentness,
            "generation_id": generation.get("generation_id") if isinstance(generation.get("generation_id"), str) else None,
        },
        "evidence_refs": [evidence],
        "diagnostics": payload.get("diagnostics", []) if isinstance(payload.get("diagnostics"), list) else [],
        "claim_limit": claim_limit,
    }
    if title_by_locale:
        result["title_by_locale"] = title_by_locale
    if title_locale is not None:
        result["title_locale"] = title_locale
    return result
