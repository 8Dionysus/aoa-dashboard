"""Read-only live Goal catalog observation and source-preserving federation.

The Codex app-server is queried through an explicitly supplied control-socket
binding.  The adapter lists threads, then asks the owner for a Goal for each
exact thread id.  It never uses the current correlation, selected Goal, path,
title, task root, timestamp, or model as an identity join.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .codex_goal import CodexGoalUnavailable, UnixWebSocketRpc, _validate_goal
from .goal_catalog import DASHBOARD_SCHEMA, GROUPS, _human_title


LIVE_OWNER = "codex-app-server"
LIVE_SOURCE_REF = "codex-app-server:goal-catalog"
FEDERATION_OWNER = "aoa-dashboard"
FEDERATION_SOURCE_REF = "aoa-dashboard:goal-catalog-federation"
LIVE_CLAIM_LIMIT = (
    "Read-only Codex app-server Goal catalog observation from exact thread/list "
    "and thread/goal/get calls; it is not runtime health, acceptance, or proof."
)
FEDERATION_CLAIM_LIMIT = (
    "Derived union of independently observed owner Goal catalogs. Exact owner "
    "refs and source currentness remain attached; the dashboard does not choose "
    "role, lifecycle, acceptance, or owner truth."
)
MAX_CURSOR_LENGTH = 512
MAX_THREAD_REF_LENGTH = 256
MAX_PAGE_SIZE = 512
MAX_PAGE_COUNT = 128
QUALITY_STATES = frozenset({"current", "current_at_read", "stale", "deferred", "unknown", "invalid", "missing"})


def _pagination(
    *,
    cursor: str | None,
    next_cursor: str | None,
    complete: bool,
    page_size: int | None = None,
    pages_read: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": "opaque_cursor",
        "cursor": cursor,
        "next_cursor": next_cursor,
        "complete": complete,
        "complete_for_query": complete,
        "supports_immutable_snapshot": False,
    }
    if page_size is not None:
        result["page_size"] = page_size
    if pages_read is not None:
        result["pages_read"] = pages_read
    return result


def _empty_live(
    state: str,
    reason: str,
    *,
    evidence_refs: list[dict[str, Any]] | None = None,
    pagination: dict[str, Any] | None = None,
    source_currentness: str | None = None,
) -> dict[str, Any]:
    currentness = source_currentness or state
    source = None
    if state != "missing" or evidence_refs:
        source = _live_source_descriptor(
            state=state,
            currentness=currentness,
            pagination=pagination or _pagination(cursor=None, next_cursor=None, complete=False),
            diagnostics=[reason],
        )
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": currentness,
        "items": [],
        "counts_by_group": {},
        "pagination": pagination or _pagination(cursor=None, next_cursor=None, complete=False),
        "source": source,
        "evidence_refs": evidence_refs or [],
        "diagnostics": [reason],
        "claim_limit": LIVE_CLAIM_LIMIT,
    }


def _live_source_descriptor(
    *,
    state: str,
    currentness: str,
    pagination: dict[str, Any],
    diagnostics: list[str],
    pages_read: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "owner": LIVE_OWNER,
        "ref": LIVE_SOURCE_REF,
        "kind": "owner_api_catalog",
        "methods": ["thread/list", "thread/goal/get"],
        "transport": "websocket_unix",
        "state": state,
        "currentness": currentness,
        "pagination": copy.deepcopy(pagination),
        "claim_limit": LIVE_CLAIM_LIMIT,
    }
    if pages_read is not None:
        result["pages_read"] = pages_read
    if diagnostics:
        result["diagnostics"] = list(dict.fromkeys(diagnostics))
    return result


def _binding_value(binding: dict[str, Any], key: str, *, default: Any = None) -> Any:
    value = binding.get(key, default)
    if value is not None:
        return value
    query = binding.get("query")
    if isinstance(query, dict):
        return query.get(key, default)
    return default


def _validated_binding(config: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    binding = config.get("live_goal_catalog_source")
    if not isinstance(binding, dict):
        return None, "live_owner_binding_missing"
    if binding.get("enabled") is not True:
        return None, "live_owner_binding_disabled"
    if binding.get("owner") != LIVE_OWNER:
        return None, "live_owner_binding_owner_invalid"
    if binding.get("authority") != "source_owner":
        return None, "live_owner_binding_authority_invalid"
    if binding.get("access_scope") != "owner_bounded":
        return None, "live_owner_binding_scope_invalid"
    if not isinstance(binding.get("claim_policy"), str) or not binding["claim_policy"].strip():
        return None, "live_owner_binding_claim_policy_invalid"
    if not isinstance(binding.get("claim_limit"), str) or not binding["claim_limit"].strip():
        return None, "live_owner_binding_claim_limit_invalid"
    if binding.get("access") != "read_only":
        return None, "live_owner_binding_access_invalid"
    if binding.get("methods") != ["thread/list", "thread/goal/get"]:
        return None, "live_owner_binding_methods_invalid"
    socket_path = binding.get("socket_path")
    if not isinstance(socket_path, str) or not socket_path or not Path(socket_path).is_absolute():
        return None, "live_owner_socket_binding_missing"
    page_size = _binding_value(binding, "page_size")
    max_pages = _binding_value(binding, "max_pages")
    timeout = _binding_value(binding, "timeout_seconds", default=1.5)
    archived = _binding_value(binding, "archived")
    client_version = _binding_value(binding, "client_version")
    if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= MAX_PAGE_SIZE:
        return None, "live_owner_page_size_invalid"
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or not 1 <= max_pages <= MAX_PAGE_COUNT:
        return None, "live_owner_max_pages_invalid"
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
        return None, "live_owner_timeout_invalid"
    if archived is not False:
        return None, "live_owner_archived_query_invalid"
    if not isinstance(client_version, str) or not client_version.strip() or len(client_version) > 64 or any(
        character.isspace() for character in client_version
    ):
        return None, "live_owner_client_version_invalid"
    normalized = {
        "owner": LIVE_OWNER,
        "socket_path": str(Path(socket_path).resolve(strict=False)),
        "page_size": page_size,
        "max_pages": max_pages,
        "timeout_seconds": float(timeout),
        "archived": False,
        "client_version": client_version.strip(),
    }
    for key in ("sort_key", "sort_direction"):
        value = _binding_value(binding, key)
        if value is not None:
            if not isinstance(value, str) or not value or len(value) > 64 or any(character.isspace() for character in value):
                return None, f"live_owner_{key}_invalid"
            normalized[key] = value
    return normalized, None


def _source_evidence(*, label: str, ref: str, method: str, currentness: str) -> dict[str, Any]:
    return {
        "label": label,
        "kind": "owner_api_observation",
        "ref": ref,
        "owner": LIVE_OWNER,
        "method": method,
        "currentness": currentness,
        "claim_limit": LIVE_CLAIM_LIMIT,
    }


def _timestamp(value: Any) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CodexGoalUnavailable("owner_goal_timestamp_invalid")
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    except (OverflowError, OSError, ValueError) as exc:
        raise CodexGoalUnavailable("owner_goal_timestamp_invalid") from exc


def _live_item(goal: dict[str, Any], *, page_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    thread_id = goal["thread_id"]
    if not isinstance(thread_id, str) or not thread_id or len(thread_id) > MAX_THREAD_REF_LENGTH:
        raise CodexGoalUnavailable("owner_goal_thread_id_invalid")
    lifecycle = goal["status"]
    if lifecycle not in GROUPS:
        raise CodexGoalUnavailable("owner_goal_status_invalid")
    title: str | None
    title_state: str
    try:
        title = _human_title(goal["objective"])
        title_state = "available"
    except ValueError:
        title = None
        title_state = "withheld"
    goal_ref = f"{LIVE_SOURCE_REF}:thread/goal/get:{thread_id}"
    page_ref = f"{LIVE_SOURCE_REF}:thread/list:page:{page_number}"
    source_records = [
        {
            "owner": LIVE_OWNER,
            "ref": page_ref,
            "kind": "owner_api_page",
            "method": "thread/list",
            "currentness": "current_at_read",
            "claim_limit": LIVE_CLAIM_LIMIT,
        },
        {
            "owner": LIVE_OWNER,
            "ref": goal_ref,
            "kind": "owner_api_goal",
            "method": "thread/goal/get",
            "currentness": "current_at_read",
            "claim_limit": LIVE_CLAIM_LIMIT,
        },
    ]
    item = {
        "ref": thread_id,
        "title": title,
        "title_state": title_state,
        "lifecycle_state": lifecycle,
        "group": GROUPS[lifecycle],
        "first_observed_at": _timestamp(goal["created_at"]),
        "last_observed_at": _timestamp(goal["updated_at"]),
        "ambiguity": False,
        "identity": {
            "owner": LIVE_OWNER,
            "ref": thread_id,
            "basis": "exact_thread_list_id_and_goal_threadId",
        },
        "source_records": source_records,
    }
    return item, source_records[1]


def _validate_list_page(value: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(value, dict):
        raise CodexGoalUnavailable("owner_thread_list_schema_invalid")
    if "nextCursor" not in value:
        raise CodexGoalUnavailable("owner_thread_list_cursor_missing")
    data = value.get("data")
    if not isinstance(data, list):
        raise CodexGoalUnavailable("owner_thread_list_data_invalid")
    next_cursor = value.get("nextCursor")
    if next_cursor is not None and (not isinstance(next_cursor, str) or len(next_cursor) > MAX_CURSOR_LENGTH):
        raise CodexGoalUnavailable("owner_thread_list_cursor_invalid")
    backwards_cursor = value.get("backwardsCursor")
    if backwards_cursor is not None and (
        not isinstance(backwards_cursor, str) or len(backwards_cursor) > MAX_CURSOR_LENGTH
    ):
        raise CodexGoalUnavailable("owner_thread_list_backwards_cursor_invalid")
    threads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for thread in data:
        if not isinstance(thread, dict):
            raise CodexGoalUnavailable("owner_thread_item_invalid")
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id or len(thread_id) > MAX_THREAD_REF_LENGTH:
            raise CodexGoalUnavailable("owner_thread_id_invalid")
        if thread_id in seen:
            raise CodexGoalUnavailable("owner_duplicate_thread_id")
        seen.add(thread_id)
        threads.append(thread)
    return threads, next_cursor


def observe_live_goal_catalog(
    config: dict[str, Any],
    *,
    rpc_factory: Callable[..., Any] = UnixWebSocketRpc,
) -> dict[str, Any]:
    """Read a bounded, explicitly configured live Goal catalog."""

    binding, binding_error = _validated_binding(config)
    if binding is None:
        state = "missing" if binding_error == "live_owner_binding_missing" else "invalid"
        return _empty_live(state, binding_error or "live_owner_binding_invalid")
    endpoint = Path(binding["socket_path"])
    evidence_refs: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    item_refs: set[str] = set()
    diagnostics: list[str] = []
    cursor: str | None = None
    first_cursor: str | None = None
    pages_read = 0
    next_cursor: str | None = None
    listed_thread_ids: set[str] = set()
    seen_cursors: set[str] = set()
    try:
        with rpc_factory(endpoint, timeout=binding["timeout_seconds"]) as rpc:
            rpc.call(
                "initialize",
                {
                    "clientInfo": {
                        "name": "aoa_dashboard",
                        "title": "AoA Dashboard read-only Goal catalog",
                        "version": binding["client_version"],
                    },
                    "capabilities": {},
                },
            )
            rpc.notify("initialized")
            while pages_read < binding["max_pages"]:
                if cursor is not None:
                    if cursor in seen_cursors:
                        raise CodexGoalUnavailable("owner_thread_cursor_cycle")
                    seen_cursors.add(cursor)
                query: dict[str, Any] = {
                    "archived": binding["archived"],
                    "limit": binding["page_size"],
                }
                if cursor is not None:
                    query["cursor"] = cursor
                if "sort_key" in binding:
                    query["sortKey"] = binding["sort_key"]
                if "sort_direction" in binding:
                    query["sortDirection"] = binding["sort_direction"]
                page_number = pages_read + 1
                raw_page = rpc.call("thread/list", query)
                threads, next_cursor = _validate_list_page(raw_page)
                if first_cursor is None:
                    first_cursor = cursor
                page_ref = _source_evidence(
                    label=f"Codex live Goal catalog page {page_number}",
                    ref=f"{LIVE_SOURCE_REF}:thread/list:page:{page_number}",
                    method="thread/list",
                    currentness="current_at_read",
                )
                evidence_refs.append(page_ref)
                pages_read += 1
                page_goal_refs: set[str] = set()
                for thread in threads:
                    thread_id = thread["id"]
                    if thread_id in listed_thread_ids:
                        raise CodexGoalUnavailable("owner_duplicate_thread_id")
                    listed_thread_ids.add(thread_id)
                    try:
                        goal = rpc.call("thread/goal/get", {"threadId": thread_id})
                        if isinstance(goal, dict) and goal.get("goal") is None:
                            diagnostics.append("live_thread_without_goal")
                            continue
                        normalized_goal = _validate_goal(goal, thread_id)
                    except CodexGoalUnavailable as exc:
                        reason = str(exc)
                        if reason == "owner_method_failed:thread/goal/get":
                            diagnostics.append("live_goal_read_deferred")
                        else:
                            diagnostics.append("live_goal_item_invalid")
                        continue
                    if normalized_goal["thread_id"] in page_goal_refs or normalized_goal["thread_id"] in item_refs:
                        raise CodexGoalUnavailable("owner_duplicate_goal_ref")
                    live_item, goal_evidence = _live_item(normalized_goal, page_number=page_number)
                    items.append(live_item)
                    item_refs.add(normalized_goal["thread_id"])
                    page_goal_refs.add(normalized_goal["thread_id"])
                    evidence_refs.append(goal_evidence)
                if next_cursor is None:
                    break
                if next_cursor in seen_cursors:
                    raise CodexGoalUnavailable("owner_thread_cursor_cycle")
                cursor = next_cursor
            else:
                if next_cursor is not None:
                    diagnostics.append("live_page_limit_reached")
    except (OSError, TimeoutError, CodexGoalUnavailable, TypeError) as exc:
        reason = str(exc)
        if reason.startswith("owner_thread") or reason.startswith("owner_duplicate") or reason.startswith("owner_goal_"):
            state = "invalid"
            diagnostics.append(reason)
        else:
            state = "unknown"
            diagnostics.append("live_owner_unavailable")
        pagination = _pagination(
            cursor=first_cursor,
            next_cursor=next_cursor,
            complete=False,
            page_size=binding["page_size"],
            pages_read=pages_read,
        )
        source = _live_source_descriptor(
            state=state,
            currentness=state,
            pagination=pagination,
            diagnostics=diagnostics,
            pages_read=pages_read,
        )
        return {
            "schema_version": DASHBOARD_SCHEMA,
            "state": state,
            "currentness": state,
            "items": items,
            "counts_by_group": _counts(items),
            "pagination": pagination,
            "source": source,
            "evidence_refs": evidence_refs,
            "diagnostics": list(dict.fromkeys(diagnostics)),
            "claim_limit": LIVE_CLAIM_LIMIT,
        }

    complete = next_cursor is None
    state = "deferred" if not complete else "current"
    if "live_goal_item_invalid" in diagnostics:
        state = "invalid"
    degrading_diagnostics = {
        "live_page_limit_reached",
        "live_goal_read_deferred",
        "live_goal_item_invalid",
    }
    if degrading_diagnostics.intersection(diagnostics) and state == "current":
        state = "deferred"
    pagination = _pagination(
        cursor=first_cursor,
        next_cursor=next_cursor,
        complete=complete and not diagnostics,
        page_size=binding["page_size"],
        pages_read=pages_read,
    )
    source = _live_source_descriptor(
        state=state,
        currentness="current_at_read" if state == "current" else state,
        pagination=pagination,
        diagnostics=diagnostics,
        pages_read=pages_read,
    )
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": "current_at_read" if state == "current" else state,
        "items": items,
        "counts_by_group": _counts(items),
        "pagination": pagination,
        "source": source,
        "evidence_refs": evidence_refs,
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "claim_limit": LIVE_CLAIM_LIMIT,
    }


def _counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        group = item.get("group")
        if isinstance(group, str):
            counts[group] = counts.get(group, 0) + 1
    return counts


def _source_state(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "missing"
    state = value.get("state")
    return state if state in QUALITY_STATES or state == "current" else "unknown"


def _source_currentness(value: dict[str, Any] | None) -> str:
    if not isinstance(value, dict):
        return "missing"
    currentness = value.get("currentness", value.get("state"))
    return currentness if currentness in QUALITY_STATES else "unknown"


def _identity(item: dict[str, Any], owner: str) -> tuple[str, str] | None:
    identity = item.get("identity")
    if isinstance(identity, dict) and identity.get("owner") == owner and isinstance(identity.get("ref"), str):
        return owner, identity["ref"]
    ref = item.get("ref")
    if isinstance(ref, str) and ref:
        return owner, ref
    return None


def _item_source_records(
    catalog: dict[str, Any],
    item: dict[str, Any],
    *,
    owner: str,
) -> list[dict[str, Any]]:
    records = item.get("source_records")
    if isinstance(records, list):
        return copy.deepcopy(records)
    source = catalog.get("source")
    publisher_ref = source.get("ref") if isinstance(source, dict) else None
    currentness = _source_currentness(catalog)
    return [
        {
            "owner": owner,
            "ref": publisher_ref or f"{owner}:goal-catalog",
            "kind": "owner_catalog_item",
            "currentness": currentness,
            "claim_limit": catalog.get("claim_limit") or "Owner-qualified Goal catalog item.",
        }
    ]


def _with_provenance(catalog: dict[str, Any], item: dict[str, Any], *, owner: str) -> dict[str, Any]:
    result = copy.deepcopy(item)
    identity = _identity(item, owner)
    if identity is None:
        identity = (owner, str(item.get("ref", "")))
    result["identity"] = {
        "owner": identity[0],
        "ref": identity[1],
        "basis": "exact_owner_catalog_ref" if owner != LIVE_OWNER else "exact_thread_list_id_and_goal_threadId",
    }
    result["source_records"] = _item_source_records(catalog, item, owner=owner)
    result["observations"] = [
        {
            "owner": owner,
            "ref": identity[1],
            "currentness": _source_currentness(catalog),
            "lifecycle_state": item.get("lifecycle_state", "unknown"),
            "group": item.get("group", "attention"),
            "title_state": item.get("title_state", "missing"),
            "claim_limit": catalog.get("claim_limit") or FEDERATION_CLAIM_LIMIT,
        }
    ]
    return result


def _merge_duplicate(historical: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Merge only an exact ref overlap, retaining both observations."""

    result = copy.deepcopy(historical)
    historical_state = historical.get("lifecycle_state")
    live_state = live.get("lifecycle_state")
    if historical_state != live_state:
        result["lifecycle_state"] = "unknown"
        result["group"] = "attention"
        result["ambiguity"] = True
    else:
        result["lifecycle_state"] = historical_state
        result["group"] = historical.get("group", "attention")
    historical_title = historical.get("title") if historical.get("title_state") == "available" else None
    live_title = live.get("title") if live.get("title_state") == "available" else None
    if historical_title and live_title and historical_title != live_title:
        result["title"] = None
        result["title_state"] = "withheld"
        result["ambiguity"] = True
    elif not historical_title and live_title:
        result["title"] = live_title
        result["title_state"] = "available"
    sources = [*copy.deepcopy(historical.get("source_records", [])), *copy.deepcopy(live.get("source_records", []))]
    result["source_records"] = _unique_records(sources)
    result["observations"] = _unique_records(
        [*copy.deepcopy(historical.get("observations", [])), *copy.deepcopy(live.get("observations", []))]
    )
    result["identity"] = {
        "owner": "federated-exact-ref-overlap",
        "ref": result["ref"],
        "basis": "exact_owner_ref_string_equality_only",
    }
    if historical.get("first_observed_at") is None:
        result["first_observed_at"] = live.get("first_observed_at")
    if historical.get("last_observed_at") is None:
        result["last_observed_at"] = live.get("last_observed_at")
    return result


def _unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        key = repr(sorted(record.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _aggregate_state(historical: dict[str, Any], live: dict[str, Any]) -> str:
    historical_state = _source_state(historical)
    live_state = _source_state(live)
    if live_state == "current":
        return "current"
    if historical_state in {"current", "current_at_read"}:
        return historical_state if historical_state != "current_at_read" else "current"
    if historical_state == "stale" and live_state in {"missing", "unknown", "invalid"}:
        return "stale"
    if historical_state not in {"missing", "unknown"}:
        return historical_state
    if live_state != "missing":
        return live_state
    return "missing"


def federate_goal_catalog(historical: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """Union two owner catalogs without erasing either source's degradation."""

    historical_value = historical if isinstance(historical, dict) else {}
    live_value = live if isinstance(live, dict) else {}
    historical_items = historical_value.get("items") if isinstance(historical_value.get("items"), list) else []
    live_items = live_value.get("items") if isinstance(live_value.get("items"), list) else []
    merged: list[dict[str, Any]] = []
    indexes: dict[str, int] = {}
    for item in historical_items:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        prepared = _with_provenance(historical_value, item, owner="aoa-session-memory")
        indexes[item["ref"]] = len(merged)
        merged.append(prepared)
    for item in live_items:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            continue
        prepared = _with_provenance(live_value, item, owner=LIVE_OWNER)
        existing = indexes.get(item["ref"])
        if existing is None:
            indexes[item["ref"]] = len(merged)
            merged.append(prepared)
        else:
            merged[existing] = _merge_duplicate(merged[existing], prepared)
    source_inputs = [
        _source_snapshot("historical", historical_value, owner="aoa-session-memory"),
        _source_snapshot("live", live_value, owner=LIVE_OWNER),
    ]
    aggregate_state = _aggregate_state(historical_value, live_value)
    diagnostics = _unique_strings(
        [
            *(_as_strings(historical_value.get("diagnostics"))),
            *(_as_strings(live_value.get("diagnostics"))),
            *(["catalog_sources_federated"] if merged else []),
        ]
    )
    historical_pagination = historical_value.get("pagination") if isinstance(historical_value.get("pagination"), dict) else _pagination(cursor=None, next_cursor=None, complete=True)
    live_pagination = live_value.get("pagination") if isinstance(live_value.get("pagination"), dict) else _pagination(cursor=None, next_cursor=None, complete=False)
    complete = bool(historical_pagination.get("complete", historical_value.get("state") in {"missing", "current"})) and bool(
        live_pagination.get("complete", live_value.get("state") in {"missing", "current"})
    )
    next_cursor = live_pagination.get("next_cursor") or historical_pagination.get("next_cursor")
    pagination = {
        "mode": "federated",
        "cursor": None,
        "next_cursor": next_cursor if isinstance(next_cursor, str) else None,
        "complete": complete,
        "complete_for_query": complete,
        "sources": {
            "historical": copy.deepcopy(historical_pagination),
            "live": copy.deepcopy(live_pagination),
        },
    }
    result = {
        "schema_version": DASHBOARD_SCHEMA,
        "state": aggregate_state,
        "currentness": aggregate_state,
        "items": merged,
        "counts_by_group": _counts(merged),
        "pagination": pagination,
        "source": {
            "owner": FEDERATION_OWNER,
            "ref": FEDERATION_SOURCE_REF,
            "kind": "derived_federation",
            "currentness": aggregate_state,
            "inputs": source_inputs,
            "claim_limit": FEDERATION_CLAIM_LIMIT,
        },
        "sources": source_inputs,
        "evidence_refs": _unique_records(
            [
                *(_as_dicts(historical_value.get("evidence_refs"))),
                *(_as_dicts(live_value.get("evidence_refs"))),
            ]
        ),
        "diagnostics": diagnostics,
        "claim_limit": FEDERATION_CLAIM_LIMIT,
    }
    return result


def _source_snapshot(key: str, catalog: dict[str, Any], *, owner: str) -> dict[str, Any]:
    source = catalog.get("source") if isinstance(catalog.get("source"), dict) else {}
    return {
        "key": key,
        "owner": owner,
        "ref": source.get("ref") if isinstance(source.get("ref"), str) else f"{owner}:goal-catalog",
        "kind": source.get("kind") if isinstance(source.get("kind"), str) else "owner_catalog",
        "owner_source": copy.deepcopy(source),
        "state": _source_state(catalog),
        "currentness": _source_currentness(catalog),
        "items_admitted": len(catalog.get("items", [])) if isinstance(catalog.get("items"), list) else 0,
        "pagination": copy.deepcopy(catalog.get("pagination")) if isinstance(catalog.get("pagination"), dict) else _pagination(cursor=None, next_cursor=None, complete=False),
        "evidence_refs": copy.deepcopy(catalog.get("evidence_refs")) if isinstance(catalog.get("evidence_refs"), list) else [],
        "diagnostics": _as_strings(catalog.get("diagnostics")),
        "claim_limit": catalog.get("claim_limit") or FEDERATION_CLAIM_LIMIT,
    }


def _as_strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _as_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
