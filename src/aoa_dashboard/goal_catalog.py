"""Fail-closed admission for owner-published Goal navigation surfaces.

The dashboard may consume a path or an explicitly configured owner command,
but it never discovers a source by guessing a checkout, session, or Goal
identifier. Catalog pagination remains opaque to the adapter and browser.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from .source_binding import FileSnapshot, is_sha256, loads_json, read_file_snapshot, snapshot_ref, utc_now


OWNER_SCHEMA = "aoa_session_memory_goal_catalog_v1"
DASHBOARD_SCHEMA = "aoa_dashboard_goal_catalog_projection_v1"
PROJECTION_OWNER_SCHEMA = "aoa_session_memory_goal_projection_v1"
PROJECTION_DASHBOARD_SCHEMA = "aoa_dashboard_goal_projection_v1"
OWNER = "aoa-session-memory"
SOURCE_REF = "aoa-session-memory:goal-lifecycles"
PROJECTION_SOURCE_REF = "aoa-session-memory:goal-projection"
CURRENTNESS = frozenset({"current", "stale", "deferred", "unknown", "invalid"})
PUBLICATION_STATES = frozenset({"current", "current_at_read", "stale", "deferred", "unknown", "invalid", "missing"})
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
    return result, None


def _command_snapshot(publication: dict[str, Any]) -> FileSnapshot:
    capability = publication["capability"]
    evidence_path = Path(f"capability:{re.sub(r'[^A-Za-z0-9_.:-]+', '_', capability)}")
    observed_at = utc_now()
    try:
        completed = subprocess.run(
            publication["command"],
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
    if completed.returncode != 0:
        return FileSnapshot(evidence_path, raw, digest, None, "invalid", publication.get("expected_sha256"), None, "publication command failed", observed_at)
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
    return FileSnapshot(evidence_path, raw, digest, parsed, "current_at_read", publication.get("expected_sha256"), None, None, observed_at)


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
