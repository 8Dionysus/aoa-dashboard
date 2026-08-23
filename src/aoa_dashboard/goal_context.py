"""Read-only consumers for the exact Goal context owner publications.

This module owns only a small dashboard projection.  The two upstream
publications remain authoritative for their own safe fields and currentness:
the session-memory Goal/thread board is not a branch or participant source,
and the aoa-agents relation graph is not actor, runtime, or acceptance
authority.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from .goal_catalog import _read_publication
from .quality import combine_quality_states
from .source_binding import safe_diagnostic, snapshot_ref, utc_now


DASHBOARD_SCHEMA = "aoa_dashboard_goal_context_v1"
THREAD_SCHEMA = "aoa_session_memory_goal_thread_board_v1"
THREAD_PUBLICATION_SCHEMA = "aoa_session_memory_goal_thread_board_public_v1"
GRAPH_SCHEMA = "aoa_agents_goal_participant_graph_v1"
THREAD_OWNER = "aoa-session-memory"
GRAPH_OWNER = "aoa-agents"
THREAD_OWNER_COMMIT = "f19b598368d9422152c6ca41d09ffe5de22637dd"
GRAPH_OWNER_COMMIT = "db7b7f7ac7465406b3a90ca26d3cf31ac81706fe"
THREAD_CAPABILITY = "aoa-session-memory:goal-thread-board"
GRAPH_CAPABILITY = "aoa-agents:goal-participant-graph"
QUALITY_STATES = frozenset({"current", "current_at_read", "missing", "unknown", "stale", "deferred", "invalid"})
CONTEXT_STATES = frozenset({"current", "missing", "unknown", "stale", "deferred", "invalid"})

THREAD_CLAIM_LIMIT = (
    "Exact public-safe Goal/thread board metadata from aoa-session-memory. "
    "Item order is source-page order; branch lifecycle, participants, runtime, "
    "proof, acceptance, and semantic event history remain unavailable."
)
GRAPH_CLAIM_LIMIT = (
    "Exact aoa-agents Goal participant relation dimensions joined only by the "
    "publisher-owned relation_key and exact scope. No display, liveness, wake, "
    "completion, proof, or acceptance claim is made."
)
CONTEXT_CLAIM_LIMIT = (
    "Dashboard-owned derived Goal context. It preserves owner currentness and "
    "privacy omissions; it does not own Goal meaning, participants, runtime, "
    "proof, acceptance, or action execution."
)

_THREAD_REQUIRED = frozenset(
    {
        "schema_version",
        "publication_schema_version",
        "artifact_type",
        "state",
        "currentness",
        "publication_state",
        "goal_ref",
        "master_thread_id",
        "exact_binding",
        "source",
        "owner_read",
        "items",
        "relations",
        "relation_state",
        "branch",
        "omissions",
        "privacy",
        "claim_limit",
    }
)
_THREAD_ITEM_FIELDS = (
    "item_ref",
    "item_id",
    "item_id_state",
    "item_kind",
    "owner_event_kind",
    "owner_item_type",
    "review_state",
    "body_state",
    "order",
    "order_state",
    "goal_ref",
    "thread_id",
    "observed_at",
    "source_ref",
    "evidence_ref",
    "redacted_fields",
    "item_digest",
)
_THREAD_RELATION_FIELDS = (
    "relation_ref",
    "relation_kind",
    "from_thread_id",
    "to_thread_id",
    "from_thread_id_state",
    "to_thread_id_state",
    "relation_state",
    "semantic_branch_state",
    "order",
    "source_ref",
    "goal_ref",
    "evidence_ref",
    "redacted_fields",
    "relation_digest",
)
_GRAPH_DIMENSIONS = (
    "identity",
    "obligation_role",
    "task_assignment",
    "model_realization",
    "runtime_incarnation",
)
_THREAD_ITEM_TYPES = frozenset({"agentMessage", "commandExecution", "collabAgentToolCall", "dynamicToolCall", "fileChange", "hookPrompt", "mcpToolCall", "plan", "reasoning", "userMessage"})
_THREAD_EVENT_KINDS = frozenset({"goal_blocked", "goal_completed", "goal_create_failed", "goal_create_requested", "goal_created", "goal_inspected", "goal_updated"})
_THREAD_RELATION_KINDS = frozenset({"spawn_parent", "history_fork"})
_GRAPH_OMISSIONS = frozenset({"human_display_name", "raw_prompt", "secrets", "cwd", "path", "pid", "terminal_title", "unreviewed_model_metadata"})
_THREAD_OMISSIONS = frozenset(
    {
        "prompt",
        "transcript_body",
        "objective",
        "raw_paths",
        "private_metadata",
        "command_text",
        "tool_arguments",
        "tool_results",
        "process_identity",
        "actor_identity",
        "model_identity",
    }
)


class GoalContextInvalid(ValueError):
    """Raised for a source shape that must not be projected."""


def _state(value: Any, fallback: str = "unknown") -> str:
    if value == "current_at_read":
        return "current"
    if isinstance(value, str) and value in CONTEXT_STATES:
        return value
    return fallback


def _currentness(value: Any, fallback: str = "unknown") -> str:
    if isinstance(value, str) and value in QUALITY_STATES:
        return "current" if value == "current_at_read" else value
    return fallback


def _text(value: Any, *, maximum: int = 512) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        return None
    return value.strip()


def _opaque(value: Any, *, maximum: int = 512) -> str | None:
    result = _text(value, maximum=maximum)
    if result is None or any(character.isspace() for character in result):
        return None
    return result


def _bounded_list(value: Any, *, maximum: int = 64) -> list[Any]:
    return list(value[:maximum]) if isinstance(value, list) else []


def _safe_diagnostics(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [safe_diagnostic(item) for item in value[:64]]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _scope_equal(expected: Any, actual: Any) -> bool:
    return isinstance(expected, dict) and isinstance(actual, dict) and _canonical(expected) == _canonical(actual)


def _safe_public_ref(value: Any, *, expected_owner: str | None = None) -> dict[str, str]:
    if not isinstance(value, dict):
        raise GoalContextInvalid("public_ref_shape_invalid")
    owner_repo = _opaque(value.get("owner_repo"), maximum=256)
    object_id = _opaque(value.get("object_id"), maximum=512)
    source_ref = _opaque(value.get("source_ref"), maximum=1024)
    schema_version = _opaque(value.get("schema_version"), maximum=256)
    content_digest = _opaque(value.get("content_digest"), maximum=128)
    if expected_owner is not None and owner_repo != expected_owner:
        raise GoalContextInvalid("public_ref_owner_invalid")
    if not owner_repo or not object_id or not source_ref or not source_ref.startswith("repo:") or not schema_version or "_v" not in schema_version or not schema_version.rsplit("_v", 1)[1].isdigit() or not content_digest or not content_digest.startswith("sha256:") or len(content_digest) != 71 or any(character not in "0123456789abcdef" for character in content_digest[7:]):
        raise GoalContextInvalid("public_ref_shape_invalid")
    return {
        "owner_repo": owner_repo,
        "object_id": object_id,
        "source_ref": source_ref,
        "schema_version": schema_version,
        "content_digest": content_digest,
    }


def _context_bindings(config: dict[str, Any]) -> dict[str, Any]:
    root = config.get("goal_context_sources")
    if isinstance(root, dict):
        return root
    legacy = {
        "thread_board": config.get("goal_thread_board_source"),
        "participant_graph": config.get("goal_participant_graph_source"),
    }
    return {key: value for key, value in legacy.items() if value is not None}


def _descriptor(
    config: dict[str, Any],
    key: str,
    *,
    owner: str,
    capability: str,
    owner_commit: str,
    schema: str,
) -> tuple[dict[str, Any] | None, str | None]:
    value = _context_bindings(config).get(key)
    if value is None:
        return None, "binding_missing"
    if not isinstance(value, dict):
        return None, "binding_invalid"
    result = copy.deepcopy(value)
    if result.get("owner", owner) != owner:
        return None, "owner_mismatch"
    configured_commit = result.get("owner_commit")
    if configured_commit is not None and configured_commit != owner_commit:
        return None, "owner_commit_mismatch"
    configured_schema = result.get("expected_schema_version", schema)
    if configured_schema != schema:
        return None, "schema_binding_mismatch"
    result.setdefault("owner", owner)
    result.setdefault("capability", capability)
    result.setdefault("owner_commit", owner_commit)
    result.setdefault("expected_schema_version", schema)
    result.setdefault("authority", "source_owner")
    result.setdefault("access_scope", "owner_bounded")
    result.setdefault("claim_policy", "source_owner_metadata")
    result.setdefault("claim_limit", THREAD_CLAIM_LIMIT if key == "thread_board" else GRAPH_CLAIM_LIMIT)
    return result, None


def _missing_evidence(
    descriptor: dict[str, Any] | None,
    *,
    label: str,
    owner: str,
    capability: str,
    state: str,
    claim_limit: str,
    diagnostic: str,
) -> dict[str, Any]:
    capability_ref = _text((descriptor or {}).get("capability"), maximum=256) or capability
    return {
        "label": label,
        "kind": "goal_context_publication",
        "ref": f"capability:{capability_ref}",
        "currentness": state,
        "freshness": state,
        "owner": owner,
        "access_scope": "owner_bounded",
        "authority": "source_owner",
        "claim_policy": "source_owner_metadata",
        "claim_limit": claim_limit,
        "degradation": [diagnostic],
        "observed_at": utc_now(),
    }


def _read_source(
    descriptor: dict[str, Any] | None,
    descriptor_error: str | None,
    *,
    goal_ref: str,
    label: str,
    owner: str,
    capability: str,
    owner_commit: str,
    claim_limit: str,
) -> tuple[Any, dict[str, Any], str, list[str]]:
    if descriptor is None:
        state = "missing" if descriptor_error == "binding_missing" else "invalid"
        evidence = _missing_evidence(descriptor, label=label, owner=owner, capability=capability, state=state, claim_limit=claim_limit, diagnostic=descriptor_error or "binding_invalid")
        return None, evidence, state, [descriptor_error or "binding_invalid"]
    try:
        snapshot, publication, publication_error = _read_publication(descriptor, goal_ref=goal_ref)
    except (OSError, TypeError, ValueError):
        diagnostic = "publisher_read_invalid"
        evidence = _missing_evidence(descriptor, label=label, owner=owner, capability=capability, state="invalid", claim_limit=claim_limit, diagnostic=diagnostic)
        return None, evidence, "invalid", [diagnostic]
    if snapshot is None:
        diagnostic = publication_error or "publisher_binding_invalid"
        state = "missing" if diagnostic in {"publisher_path_missing", "publisher_capability_missing", "binding_missing"} else "deferred" if diagnostic == "per_goal_goal_ref_argument_missing" else "invalid"
        evidence = _missing_evidence(descriptor, label=label, owner=owner, capability=capability, state=state, claim_limit=claim_limit, diagnostic=diagnostic)
        return None, evidence, state, [diagnostic]
    state = _currentness(snapshot.currentness)
    evidence = snapshot_ref(
        snapshot,
        label=label,
        kind="goal_context_publication",
        owner=owner,
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="source_owner_metadata",
        claim_limit=claim_limit,
    )
    evidence["owner_commit"] = owner_commit
    evidence["capability"] = _text((publication or descriptor).get("capability"), maximum=256) or capability
    if publication and publication.get("transport") == "command":
        evidence["ref"] = f"capability:{evidence['capability']}"
    diagnostics = []
    if snapshot.parse_error:
        diagnostics.append("source_parse_invalid")
    if snapshot.read_error:
        diagnostics.append("source_read_invalid")
    if snapshot.expected_digest is not None and snapshot.digest != snapshot.expected_digest:
        diagnostics.append("expected_digest_mismatch")
    return snapshot.parsed, evidence, state, diagnostics


def _source_record(
    *,
    source_id: str,
    owner: str,
    capability: str,
    owner_commit: str,
    state: str,
    evidence: dict[str, Any],
    diagnostics: list[str],
    claim_limit: str,
) -> dict[str, Any]:
    display_state = "current_at_read" if state == "current" else state
    return {
        "id": source_id,
        "owner": owner,
        "state": display_state,
        "freshness": display_state,
        "publisher_status": state,
        "owner_commit": owner_commit,
        "capability": capability,
        "observation": "Owner publication is available." if state == "current" else "Owner publication is not currently available.",
        "degradation": list(dict.fromkeys(diagnostics)),
        "evidence_refs": [evidence],
        "claim_limit": claim_limit,
    }


def _safe_thread_item(value: Any, *, goal_ref: str, master_thread_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoalContextInvalid("thread_item_shape_invalid")
    item_goal = value.get("goal_ref")
    if item_goal is not None and item_goal != goal_ref:
        raise GoalContextInvalid("thread_item_goal_mismatch")
    item_thread = value.get("thread_id")
    if item_thread not in {None, master_thread_id}:
        raise GoalContextInvalid("thread_item_thread_mismatch")
    result: dict[str, Any] = {}
    for field in _THREAD_ITEM_FIELDS:
        if field not in value:
            continue
        child = value[field]
        if field == "redacted_fields":
            result[field] = [item for item in _bounded_list(child) if _text(item, maximum=128)]
        elif field == "order":
            if not isinstance(child, int) or isinstance(child, bool) or child < 0:
                raise GoalContextInvalid("thread_item_order_invalid")
            result[field] = child
        elif field in {"item_id_state"}:
            if child not in {"available", "opaque"}:
                raise GoalContextInvalid("thread_item_id_state_invalid")
            result[field] = child
        elif field in {"from_thread_id_state", "to_thread_id_state"}:
            if child not in {"available", "opaque"}:
                raise GoalContextInvalid("thread_relation_thread_id_state_invalid")
            result[field] = child
        elif field in {"order_state"}:
            if child not in {"owner_page_order", "owner_index_order"}:
                raise GoalContextInvalid("thread_item_order_state_invalid")
            result[field] = child
        elif field in {"thread_id", "observed_at"} and child is not None:
            safe = _text(child, maximum=512)
            if safe is None:
                raise GoalContextInvalid("thread_item_text_invalid")
            result[field] = safe
        elif field == "item_kind":
            if child not in {"codex_thread_item_observation", "goal_lifecycle_observation"}:
                raise GoalContextInvalid("thread_item_kind_invalid")
            result[field] = child
        elif field == "owner_event_kind":
            if child is not None and child not in _THREAD_EVENT_KINDS:
                raise GoalContextInvalid("thread_item_event_kind_invalid")
            result[field] = child
        elif field == "owner_item_type":
            if child is not None and child not in _THREAD_ITEM_TYPES:
                raise GoalContextInvalid("thread_item_type_invalid")
            result[field] = child
        elif field == "review_state":
            if child != "reviewed_public_safe":
                raise GoalContextInvalid("thread_item_review_state_invalid")
            result[field] = child
        elif field == "body_state":
            if child != "withheld":
                raise GoalContextInvalid("thread_item_body_state_invalid")
            result[field] = child
        elif field in {"item_ref", "item_id", "source_ref", "evidence_ref", "item_digest"}:
            safe = _opaque(child, maximum=512)
            if safe is None:
                raise GoalContextInvalid("thread_item_ref_invalid")
            result[field] = safe
        else:
            safe = _opaque(child, maximum=512)
            if safe is None:
                raise GoalContextInvalid("thread_item_ref_invalid")
            result[field] = safe
    if not result.get("item_ref") or not result.get("item_id"):
        raise GoalContextInvalid("thread_item_identity_missing")
    return result


def _safe_thread_relation(value: Any, *, goal_ref: str, master_thread_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoalContextInvalid("thread_relation_shape_invalid")
    relation_goal = value.get("goal_ref")
    if relation_goal is not None and relation_goal != goal_ref:
        raise GoalContextInvalid("thread_relation_goal_mismatch")
    result: dict[str, Any] = {}
    for field in _THREAD_RELATION_FIELDS:
        if field not in value:
            continue
        child = value[field]
        if field == "order":
            if not isinstance(child, int) or isinstance(child, bool) or child < 0:
                raise GoalContextInvalid("thread_relation_order_invalid")
            result[field] = child
        elif field in {"redacted_fields"}:
            result[field] = [item for item in _bounded_list(child) if _text(item, maximum=128)]
        elif field == "relation_kind":
            if child not in _THREAD_RELATION_KINDS:
                raise GoalContextInvalid("thread_relation_kind_invalid")
            result[field] = child
        elif field == "relation_state":
            if child != "available":
                raise GoalContextInvalid("thread_relation_state_invalid")
            result[field] = child
        elif field == "semantic_branch_state":
            if child != "missing":
                raise GoalContextInvalid("thread_relation_branch_state_invalid")
            result[field] = child
        elif field in {"relation_ref", "from_thread_id", "to_thread_id", "source_ref", "evidence_ref", "relation_digest"}:
            safe = _opaque(child, maximum=512)
            if safe is None:
                raise GoalContextInvalid("thread_relation_ref_invalid")
            result[field] = safe
        else:
            safe = _opaque(child, maximum=512)
            if safe is None:
                raise GoalContextInvalid("thread_relation_ref_invalid")
            result[field] = safe
    if result.get("from_thread_id") not in {None, master_thread_id} and result.get("to_thread_id") not in {None, master_thread_id}:
        # Structural relations may point to the other endpoint, but the Goal
        # master must be one of the exact endpoints.
        raise GoalContextInvalid("thread_relation_thread_mismatch")
    if not result.get("relation_ref") or not result.get("relation_kind"):
        raise GoalContextInvalid("thread_relation_identity_missing")
    return result


def _safe_owner_read(value: Any, *, goal_ref: str, master_thread_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoalContextInvalid("thread_owner_read_invalid")
    result: dict[str, Any] = {
        "owner": "codex-app-server",
        "state": _state(value.get("state"), "unknown"),
        "currentness": _currentness(value.get("currentness"), "unknown"),
        "diagnostics": _safe_diagnostics(value.get("diagnostics")),
    }
    source = value.get("source")
    if isinstance(source, dict):
        result["source"] = {
            "owner": "codex-app-server",
            "currentness": _currentness(source.get("currentness"), "unknown"),
            "methods": [item for item in _bounded_list(source.get("methods"), maximum=16) if item in {"thread/goal/get", "thread/read", "thread/items/list", "thread/list"}],
        }
    goal = value.get("goal")
    if isinstance(goal, dict):
        if goal.get("thread_id") not in {None, master_thread_id}:
            raise GoalContextInvalid("thread_owner_goal_mismatch")
        safe_goal: dict[str, Any] = {}
        if goal.get("thread_id") == master_thread_id:
            safe_goal["thread_id"] = master_thread_id
        status = _opaque(goal.get("status"), maximum=128)
        if status:
            safe_goal["status"] = status
        for key in ("created_at", "updated_at"):
            if key in goal and (isinstance(goal[key], int) and not isinstance(goal[key], bool) and goal[key] >= 0 or goal[key] is None):
                safe_goal[key] = goal[key]
        result["goal"] = safe_goal
    thread = value.get("thread")
    if isinstance(thread, dict):
        if thread.get("thread_id") not in {None, master_thread_id}:
            raise GoalContextInvalid("thread_owner_thread_mismatch")
        safe_thread: dict[str, Any] = {}
        if thread.get("thread_id") == master_thread_id:
            safe_thread["thread_id"] = master_thread_id
        thread_status = _opaque(thread.get("status"), maximum=128)
        if thread_status:
            safe_thread["status"] = thread_status
        for key in ("parentThreadId_state", "forkedFromId_state"):
            if thread.get(key) in {"available", "opaque"}:
                safe_thread[key] = thread[key]
        result["thread"] = safe_thread
    digest = _opaque(value.get("observation_digest"), maximum=128)
    if digest is not None and (not digest.startswith("sha256:") or len(digest) != 71 or any(character not in "0123456789abcdef" for character in digest[7:])):
        digest = None
    if digest:
        result["observation_digest"] = digest
    return result


def _safe_thread_pagination(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("mode") != "immutable_snapshot" or value.get("supports_immutable_snapshot") is not True or not isinstance(value.get("complete_for_query"), bool) or not isinstance(value.get("owner_page_complete"), bool):
        raise GoalContextInvalid("thread_board_pagination_invalid")
    page_size = value.get("page_size")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
        raise GoalContextInvalid("thread_board_pagination_invalid")
    states = {}
    for key in ("cursor", "next_cursor", "owner_next_cursor"):
        cursor = value.get(key)
        if cursor is not None and _text(cursor, maximum=1024) is None:
            raise GoalContextInvalid("thread_board_cursor_invalid")
        states[f"{key}_state"] = "present" if cursor is not None else "missing"
    return {
        "mode": "immutable_snapshot",
        "complete_for_query": value["complete_for_query"],
        "page_size": page_size,
        "owner_page_complete": value["owner_page_complete"],
        **states,
    }


def _observe_thread_board(config: dict[str, Any], *, goal_ref: str, master_thread_id: str) -> dict[str, Any]:
    descriptor, descriptor_error = _descriptor(
        config,
        "thread_board",
        owner=THREAD_OWNER,
        capability=THREAD_CAPABILITY,
        owner_commit=THREAD_OWNER_COMMIT,
        schema=THREAD_SCHEMA,
    )
    payload, evidence, transport_state, read_diagnostics = _read_source(
        descriptor,
        descriptor_error,
        goal_ref=goal_ref,
        label="Goal thread board",
        owner=THREAD_OWNER,
        capability=THREAD_CAPABILITY,
        owner_commit=THREAD_OWNER_COMMIT,
        claim_limit=THREAD_CLAIM_LIMIT,
    )
    base = {
        "state": transport_state,
        "currentness": transport_state,
        "goal_ref": goal_ref,
        "master_thread_id": master_thread_id,
        "source": {
            "owner": THREAD_OWNER,
            "ref": THREAD_CAPABILITY,
            "capability": _text((descriptor or {}).get("capability"), maximum=256) or THREAD_CAPABILITY,
            "owner_commit": THREAD_OWNER_COMMIT,
            "schema_version": THREAD_SCHEMA,
            "claim_limit": THREAD_CLAIM_LIMIT,
        },
        "items": [],
        "relations": [],
        "relation_state": transport_state,
        "branch": {"state": "missing", "branch_ref": None, "lifecycle_state": None, "reason": "no_canonical_goal_branch_publisher"},
        "owner_read": {"state": transport_state, "currentness": transport_state, "diagnostics": list(read_diagnostics)},
        "diagnostics": list(read_diagnostics),
        "evidence_refs": [evidence],
        "claim_limit": THREAD_CLAIM_LIMIT,
    }
    if payload is None:
        return base
    if transport_state != "current":
        return base
    try:
        if not isinstance(payload, dict) or not _THREAD_REQUIRED.issubset(payload):
            raise GoalContextInvalid("thread_board_shape_invalid")
        if payload.get("schema_version") != THREAD_SCHEMA or payload.get("publication_schema_version") != THREAD_PUBLICATION_SCHEMA or payload.get("artifact_type") != "goal_thread_board_projection":
            raise GoalContextInvalid("thread_board_schema_unsupported")
        if payload.get("goal_ref") != goal_ref or payload.get("master_thread_id") != master_thread_id:
            raise GoalContextInvalid("thread_board_exact_binding_mismatch")
        exact = payload.get("exact_binding")
        if not isinstance(exact, dict) or exact.get("goal_ref") != goal_ref or exact.get("master_thread_id") != master_thread_id or exact.get("equal") is not True or exact.get("query_mode") != "exact_only":
            raise GoalContextInvalid("thread_board_exact_binding_invalid")
        source = payload.get("source")
        if not isinstance(source, dict) or source.get("owner") != THREAD_OWNER or source.get("ref") != THREAD_CAPABILITY:
            raise GoalContextInvalid("thread_board_source_invalid")
        payload_state = _state(payload.get("state"), "invalid")
        payload_currentness = _currentness(payload.get("currentness"), "invalid")
        if payload_state == "current" and payload_currentness != "current":
            raise GoalContextInvalid("thread_board_currentness_invalid")
        if payload_state == "current" and payload.get("publication_state") != "bound":
            raise GoalContextInvalid("thread_board_publication_state_invalid")
        if not isinstance(payload.get("omissions"), dict) or not _THREAD_OMISSIONS.issubset(payload["omissions"]):
            raise GoalContextInvalid("thread_board_privacy_omissions_invalid")
        privacy = payload.get("privacy")
        if not isinstance(privacy, dict) or privacy.get("scope") != "owner_bounded_public_safe" or privacy.get("no_transcript_body") is not True or privacy.get("no_raw_paths") is not True or privacy.get("no_private_metadata") is not True or privacy.get("no_actor_inference") is not True:
            raise GoalContextInvalid("thread_board_privacy_invalid")
        owner_read = _safe_owner_read(payload.get("owner_read"), goal_ref=goal_ref, master_thread_id=master_thread_id)
        relation_state = payload.get("relation_state")
        if relation_state not in {"complete", "available", "missing", "unknown", "stale", "deferred", "invalid"}:
            raise GoalContextInvalid("thread_board_relation_state_invalid")
        branch = payload.get("branch")
        if not isinstance(branch, dict) or branch.get("state") not in CONTEXT_STATES:
            raise GoalContextInvalid("thread_board_branch_invalid")
        if branch.get("state") != "missing":
            raise GoalContextInvalid("thread_board_branch_state_unsupported")
        safe_branch = {"state": "missing", "branch_ref": None, "lifecycle_state": None, "reason": "no_canonical_goal_branch_publisher"}
        if payload_state == "current":
            items = [_safe_thread_item(item, goal_ref=goal_ref, master_thread_id=master_thread_id) for item in _bounded_list(payload.get("items"), maximum=128)]
            relations = [_safe_thread_relation(item, goal_ref=goal_ref, master_thread_id=master_thread_id) for item in _bounded_list(payload.get("relations"), maximum=64)]
        else:
            items, relations = [], []
        diagnostics = [*read_diagnostics, *_safe_diagnostics(payload.get("diagnostics"))]
        return {
            **base,
            "state": payload_state,
            "currentness": payload_currentness,
            "source": {
                **base["source"],
                "publisher_currentness": _currentness(source.get("currentness"), payload_currentness),
            },
            "owner_read": owner_read,
            "items": items,
            "relations": relations,
            "relation_state": relation_state,
            "branch": safe_branch,
            "diagnostics": list(dict.fromkeys(diagnostics)),
            "snapshot": {
                key: payload.get("snapshot", {}).get(key)
                for key in ("snapshot_ref", "snapshot_digest", "generated_at", "source_freshness", "projection_freshness", "immutable")
                if isinstance(payload.get("snapshot"), dict) and key in payload["snapshot"]
            },
            "pagination": _safe_thread_pagination(payload.get("pagination")),
            "privacy": {
                "scope": "owner_bounded_public_safe",
                "prohibited_join_keys": _bounded_list(privacy.get("prohibited_join_keys"), maximum=32),
                "omissions_applied": True,
            },
            "source_counts": {key: payload.get(key) for key in ("source_item_count", "item_count", "total_item_count") if key in payload},
        }
    except (GoalContextInvalid, TypeError, ValueError) as exc:
        diagnostic = str(exc) if isinstance(exc, GoalContextInvalid) else "thread_board_shape_invalid"
        return {**base, "state": "invalid", "currentness": "invalid", "diagnostics": list(dict.fromkeys([*read_diagnostics, diagnostic])), "items": [], "relations": [], "relation_state": "invalid"}


def _safe_graph_dimension(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoalContextInvalid("participant_dimension_invalid")
    state = value.get("state")
    if state not in {"present", "missing", "unknown", "stale", "deferred", "invalid"}:
        raise GoalContextInvalid("participant_dimension_state_invalid")
    result: dict[str, Any] = {"state": state}
    owner_ref = value.get("owner_ref")
    if owner_ref is not None:
        _safe_public_ref(owner_ref)
        result["owner_ref_state"] = "present"
    else:
        result["owner_ref_state"] = "missing"
    observed = _text(value.get("observed_at"), maximum=64)
    if observed:
        result["observed_at"] = observed
    evidence = value.get("evidence_refs")
    if isinstance(evidence, list):
        result["evidence_ref_count"] = min(len(evidence), 16)
    claim = _text(value.get("claim_limit"), maximum=640)
    if claim:
        result["claim_limit"] = claim
    return result


def _safe_graph_record(value: Any, *, expected_scope: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("kind") != "aoa_agents_goal_participant_relation":
        raise GoalContextInvalid("participant_relation_shape_invalid")
    if value.get("evidence_class") == "synthetic_public_example":
        raise GoalContextInvalid("participant_relation_synthetic_not_admitted")
    relation_id = _opaque(value.get("relation_id"), maximum=512)
    if relation_id is None or not relation_id.startswith("rel-record:"):
        raise GoalContextInvalid("participant_relation_id_missing")
    scope = value.get("scope")
    if not isinstance(scope, dict) or set(scope) != {"goal_ref", "goal_instance_ref", "master_thread_ref"}:
        raise GoalContextInvalid("participant_relation_scope_invalid")
    for item in scope.values():
        _safe_public_ref(item)
    if not _scope_equal(expected_scope, scope):
        raise GoalContextInvalid("participant_relation_scope_mismatch")
    relation_key = value.get("relation_key")
    key_id = _opaque(relation_key.get("key_id"), maximum=512) if isinstance(relation_key, dict) else None
    key_digest = _opaque(relation_key.get("content_digest"), maximum=128) if isinstance(relation_key, dict) else None
    if not isinstance(relation_key, dict) or relation_key.get("schema_version") != "aoa_agents_goal_participant_relation_key_v1" or key_id is None or not key_id.startswith("rel:") or key_digest is None or not key_digest.startswith("sha256:") or len(key_digest) != 71 or any(character not in "0123456789abcdef" for character in key_digest[7:]):
        raise GoalContextInvalid("participant_relation_key_invalid")
    _safe_public_ref(relation_key.get("publisher_ref"), expected_owner=GRAPH_OWNER)
    endpoint_refs = relation_key.get("endpoint_refs")
    if not isinstance(endpoint_refs, list) or len(endpoint_refs) < 3:
        raise GoalContextInvalid("participant_relation_endpoints_invalid")
    for endpoint in endpoint_refs:
        _safe_public_ref(endpoint)
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, dict):
        raise GoalContextInvalid("participant_relation_dimensions_invalid")
    safe_dimensions = {name: _safe_graph_dimension(dimensions.get(name)) for name in _GRAPH_DIMENSIONS}
    privacy = value.get("privacy_omissions")
    if not isinstance(privacy, dict) or privacy.get("state") != "applied" or not _GRAPH_OMISSIONS.issubset(set(privacy.get("omitted_fields", []))):
        raise GoalContextInvalid("participant_relation_privacy_invalid")
    claim_limit = _text(value.get("claim_limit"), maximum=640)
    if claim_limit is None:
        raise GoalContextInvalid("participant_relation_claim_limit_missing")
    return {
        "relation_id": relation_id,
        "state": combine_quality_states(*(item["state"] for item in safe_dimensions.values()), all_missing="missing"),
        "scope_state": "present",
        "relation_key": {
            "state": "present",
            "key_id": key_id,
            "content_digest": key_digest,
            "endpoint_count": len(endpoint_refs),
        },
        "dimensions": safe_dimensions,
        "privacy_omissions_applied": True,
        "claim_limit": claim_limit,
    }


def _safe_graph_pagination(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoalContextInvalid("participant_graph_pagination_invalid")
    page_index = value.get("page_index")
    page_size = value.get("page_size")
    if not isinstance(page_index, int) or isinstance(page_index, bool) or page_index < 0 or not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1 or not isinstance(value.get("has_more"), bool):
        raise GoalContextInvalid("participant_graph_pagination_invalid")
    next_cursor = value.get("next_cursor_ref")
    if next_cursor is not None:
        _safe_public_ref(next_cursor)
    return {
        "page_index": page_index,
        "page_size": page_size,
        "has_more": value["has_more"],
        "next_cursor_state": "present" if next_cursor is not None else "missing",
    }


def _observe_participant_graph(config: dict[str, Any], *, goal_ref: str, master_thread_id: str) -> dict[str, Any]:
    descriptor, descriptor_error = _descriptor(
        config,
        "participant_graph",
        owner=GRAPH_OWNER,
        capability=GRAPH_CAPABILITY,
        owner_commit=GRAPH_OWNER_COMMIT,
        schema=GRAPH_SCHEMA,
    )
    payload, evidence, transport_state, read_diagnostics = _read_source(
        descriptor,
        descriptor_error,
        goal_ref=goal_ref,
        label="Goal participant relations",
        owner=GRAPH_OWNER,
        capability=GRAPH_CAPABILITY,
        owner_commit=GRAPH_OWNER_COMMIT,
        claim_limit=GRAPH_CLAIM_LIMIT,
    )
    base = {
        "state": transport_state,
        "currentness": transport_state,
        "source": {
            "owner": GRAPH_OWNER,
            "ref": GRAPH_CAPABILITY,
            "capability": _text((descriptor or {}).get("capability"), maximum=256) or GRAPH_CAPABILITY,
            "owner_commit": GRAPH_OWNER_COMMIT,
            "schema_version": GRAPH_SCHEMA,
            "claim_limit": GRAPH_CLAIM_LIMIT,
        },
        "records": [],
        "diagnostics": list(read_diagnostics),
        "evidence_refs": [evidence],
        "claim_limit": GRAPH_CLAIM_LIMIT,
    }
    if payload is None:
        return base
    if transport_state != "current":
        return base
    try:
        if not isinstance(payload, dict) or payload.get("schema_version") != GRAPH_SCHEMA or payload.get("kind") != "aoa_agents_goal_participant_graph" or payload.get("owner_repo") != GRAPH_OWNER:
            raise GoalContextInvalid("participant_graph_schema_invalid")
        currentness = payload.get("currentness")
        if not isinstance(currentness, dict) or currentness.get("state") not in {"current", "stale", "deferred", "unknown", "invalid"}:
            raise GoalContextInvalid("participant_graph_currentness_invalid")
        payload_state = _state(currentness.get("state"), "invalid")
        source = payload.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("source_ref"), dict) or not isinstance(source.get("contract_ref"), dict):
            raise GoalContextInvalid("participant_graph_source_invalid")
        _safe_public_ref(source["source_ref"])
        _safe_public_ref(source["contract_ref"])
        pagination = _safe_graph_pagination(payload.get("pagination"))
        privacy = payload.get("privacy_omissions")
        if not isinstance(privacy, dict) or privacy.get("state") != "applied" or not _GRAPH_OMISSIONS.issubset(set(privacy.get("omitted_fields", []))):
            raise GoalContextInvalid("participant_graph_privacy_invalid")
        fallback = payload.get("fallback_policy")
        if not isinstance(fallback, dict) or fallback.get("state") != "disabled":
            raise GoalContextInvalid("participant_graph_fallback_enabled")
        expected_scope = (descriptor or {}).get("goal_scope")
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise GoalContextInvalid("participant_graph_records_invalid")
        records: list[dict[str, Any]] = []
        diagnostics = [*read_diagnostics, *_safe_diagnostics(currentness.get("reason"))]
        if raw_records and not isinstance(expected_scope, dict):
            return {**base, "state": "deferred", "currentness": "deferred", "diagnostics": list(dict.fromkeys([*diagnostics, "participant_graph_scope_binding_missing"]))}
        if payload_state == "current":
            records = [_safe_graph_record(item, expected_scope=expected_scope) for item in raw_records[:128]] if raw_records else []
        return {
            **base,
            "state": payload_state,
            "currentness": payload_state,
            "records": records,
            "pagination": pagination,
            "privacy": {"state": "applied", "omitted_fields": sorted(_GRAPH_OMISSIONS)},
            "fallback_policy": {"state": "disabled"},
            "diagnostics": list(dict.fromkeys(diagnostics)),
        }
    except (GoalContextInvalid, TypeError, ValueError) as exc:
        diagnostic = str(exc) if isinstance(exc, GoalContextInvalid) else "participant_graph_shape_invalid"
        return {**base, "state": "invalid", "currentness": "invalid", "diagnostics": list(dict.fromkeys([*read_diagnostics, diagnostic])), "records": []}


def _combine_context_states(*values: Any) -> str:
    states = [_state(value, "unknown") for value in values]
    if not states:
        return "unknown"
    if all(item == "missing" for item in states):
        return "missing"
    combined = combine_quality_states(*states, all_missing="missing")
    return "current" if combined == "present" else combined


def observe_goal_context(config: dict[str, Any], *, goal_ref: str | None, master_thread_id: str | None) -> dict[str, Any]:
    """Consume both exact public publications for one selected Goal."""

    if not _text(goal_ref) or not _text(master_thread_id):
        thread = {"state": "missing", "currentness": "missing", "items": [], "relations": [], "diagnostics": ["goal_context_exact_binding_missing"], "claim_limit": THREAD_CLAIM_LIMIT}
        graph = {"state": "missing", "currentness": "missing", "records": [], "diagnostics": ["goal_context_exact_binding_missing"], "claim_limit": GRAPH_CLAIM_LIMIT}
    else:
        thread = _observe_thread_board(config, goal_ref=goal_ref, master_thread_id=master_thread_id)
        graph = _observe_participant_graph(config, goal_ref=goal_ref, master_thread_id=master_thread_id)
    sources = [
        _source_record(
            source_id="goal-thread-board",
            owner=THREAD_OWNER,
            capability=THREAD_CAPABILITY,
            owner_commit=THREAD_OWNER_COMMIT,
            state=_state(thread.get("state"), "unknown"),
            evidence=(thread.get("evidence_refs") or [_missing_evidence(None, label="Goal thread board", owner=THREAD_OWNER, capability=THREAD_CAPABILITY, state="unknown", claim_limit=THREAD_CLAIM_LIMIT, diagnostic="goal_context_unavailable")])[0],
            diagnostics=_safe_diagnostics(thread.get("diagnostics")),
            claim_limit=THREAD_CLAIM_LIMIT,
        ),
        _source_record(
            source_id="participant-relations",
            owner=GRAPH_OWNER,
            capability=GRAPH_CAPABILITY,
            owner_commit=GRAPH_OWNER_COMMIT,
            state=_state(graph.get("state"), "unknown"),
            evidence=(graph.get("evidence_refs") or [_missing_evidence(None, label="Goal participant relations", owner=GRAPH_OWNER, capability=GRAPH_CAPABILITY, state="unknown", claim_limit=GRAPH_CLAIM_LIMIT, diagnostic="goal_context_unavailable")])[0],
            diagnostics=_safe_diagnostics(graph.get("diagnostics")),
            claim_limit=GRAPH_CLAIM_LIMIT,
        ),
    ]
    state = _combine_context_states(thread.get("state"), graph.get("state"))
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": state,
        "goal_ref": goal_ref,
        "master_thread_id": master_thread_id,
        "thread_board": thread,
        "participant_graph": graph,
        "source_observations": sources,
        "privacy": {
            "owner_bounded": True,
            "raw_payload": "withheld",
            "technical_provenance": "optional_detail",
            "no_actor_inference": True,
            "no_join_by_label_or_process": True,
        },
        "claim_limit": CONTEXT_CLAIM_LIMIT,
    }


__all__ = [
    "DASHBOARD_SCHEMA",
    "GRAPH_OWNER_COMMIT",
    "GRAPH_SCHEMA",
    "THREAD_OWNER_COMMIT",
    "THREAD_SCHEMA",
    "observe_goal_context",
]
