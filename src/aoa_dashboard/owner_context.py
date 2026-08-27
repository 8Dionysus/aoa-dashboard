"""Bounded read-only Goal, thread, and relation observations.

The Codex app-server owns Goal and Thread meaning.  This module only validates
one exact read and one page for each supported relation query, retaining the
owner method/query/currentness boundary for diagnostics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .codex_goal import (
    DASHBOARD_SCHEMA as GOAL_SCHEMA,
    CodexGoalUnavailable,
    UnixWebSocketRpc,
    _empty as empty_goal,
    _validate_goal,
    discover_control_socket,
)
from .quality import state_for_owner_error


SCHEMA_VERSION = "aoa_dashboard_codex_goal_thread_observation_v1"
THREAD_CONTEXT_SCHEMA = "codex_goal_thread_observation_v1"
THREAD_CLAIM_LIMIT = (
    "Read-only Codex Goal/Thread observations for one exact thread. "
    "Relations are scoped pages; they do not establish a complete branch, "
    "semantic trajectory, actor mandate, runtime health, proof, or acceptance."
)
RELATION_CLAIM_LIMIT = (
    "This is one owner API relation query page. Pagination and excluded relation "
    "classes remain incomplete; it is not a complete participant graph or branch lifecycle."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _string(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CodexGoalUnavailable(f"owner_thread_{field}_invalid")
    return value.strip()


def _integer(value: Any, field: str, *, required: bool = False) -> int | None:
    if value is None and not required:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CodexGoalUnavailable(f"owner_thread_{field}_invalid")
    return value


def _boolean(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise CodexGoalUnavailable(f"owner_thread_{field}_invalid")
    return value


def _section(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if isinstance(value, str):
        return _string(value, "section"), None
    if not isinstance(value, dict):
        raise CodexGoalUnavailable("owner_thread_section_invalid")
    section_id = _string(value.get("id"), "section_id", required=True)
    section_name = _string(value.get("name"), "section_name")
    return section_id, section_name


def _status(value: Any) -> tuple[str | None, dict[str, str] | None]:
    """Normalize the app-server's string and typed status shapes."""

    if value is None:
        return None, None
    if isinstance(value, str):
        return _string(value, "status"), None
    if not isinstance(value, dict):
        raise CodexGoalUnavailable("owner_thread_status_invalid")
    status_type = value.get("type", value.get("status"))
    if not isinstance(status_type, str) or not status_type.strip():
        raise CodexGoalUnavailable("owner_thread_status_invalid")
    detail = {"type": status_type.strip()}
    for key in ("reason", "message"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            detail[key] = item.strip()
    return status_type.strip(), detail


def _source(value: Any) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize string and structured app-server thread source metadata."""

    if value is None:
        return None, None
    if isinstance(value, str):
        return _string(value, "source"), None
    if not isinstance(value, dict):
        raise CodexGoalUnavailable("owner_thread_source_invalid")
    # Current app-server versions describe spawned threads as
    # subAgent.thread_spawn.  Keep only public relation metadata; notably do
    # not project the nested agent_path or any transcript/source path.
    sub_agent = value.get("subAgent")
    spawn = sub_agent.get("thread_spawn") if isinstance(sub_agent, dict) else None
    if isinstance(spawn, dict):
        detail: dict[str, Any] = {"kind": "subAgent"}
        for key in ("parent_thread_id", "depth", "agent_nickname", "agent_role"):
            item = spawn.get(key)
            if isinstance(item, str) and item.strip():
                detail[key] = item.strip()
            elif isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                detail[key] = item
        return "subAgent", detail
    # Preserve forward-compatible typed source envelopes without projecting
    # arbitrary nested content.  A future owner shape is still source
    # metadata, not an inferred participant or branch assignment.
    for kind, candidate in value.items():
        if not isinstance(kind, str) or not isinstance(candidate, dict):
            continue
        detail = {"kind": kind}
        for key in ("parent_thread_id", "depth", "agent_nickname", "agent_role"):
            item = candidate.get(key)
            if isinstance(item, str) and item.strip():
                detail[key] = item.strip()
            elif isinstance(item, int) and not isinstance(item, bool) and item >= 0:
                detail[key] = item
        return kind, detail
    raise CodexGoalUnavailable("owner_thread_source_invalid")


def _evidence(
    *,
    method: str,
    thread_id: str,
    observed_at: str,
    query: dict[str, Any],
    claim_limit: str = THREAD_CLAIM_LIMIT,
    socket_path: str | None = None,
) -> dict[str, Any]:
    query_value = "&".join(f"{key}={value}" for key, value in sorted(query.items()))
    result = {
        "label": f"Codex {method}",
        "kind": "owner_api_observation",
        "ref": f"codex-app-server:{method}:{thread_id}",
        "owner": "codex-app-server",
        "method": method,
        "transport": "websocket_unix",
        "query": query,
        "query_key": query_value,
        "observed_at": observed_at,
        "currentness": "current_at_read",
        "claim_limit": claim_limit,
    }
    if socket_path is not None:
        result["socket_path"] = socket_path
    return result


def _thread(value: Any, expected_thread_id: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CodexGoalUnavailable("owner_thread_response_invalid")
    thread_id = _string(value.get("id"), "id", required=True)
    if expected_thread_id is not None and thread_id != expected_thread_id:
        raise CodexGoalUnavailable("owner_thread_identity_mismatch")
    source, source_detail = _source(value.get("source"))
    status, status_detail = _status(value.get("status"))
    name = _string(value.get("name"), "name")
    model_provider = _string(value.get("modelProvider"), "model_provider")
    history_mode = _string(value.get("historyMode"), "history_mode")
    section, section_name = _section(value.get("section"))
    agent_nickname = _string(value.get("agentNickname"), "agent_nickname")
    agent_role = _string(value.get("agentRole"), "agent_role")
    if isinstance(source_detail, dict):
        agent_nickname = agent_nickname or _string(source_detail.get("agent_nickname"), "source_agent_nickname")
        agent_role = agent_role or _string(source_detail.get("agent_role"), "source_agent_role")
    return {
        "thread_id": thread_id,
        "session_id": _string(value.get("sessionId"), "session_id"),
        "parent_thread_id": _string(value.get("parentThreadId"), "parent_thread_id"),
        "forked_from_id": _string(value.get("forkedFromId"), "forked_from_id"),
        "source": source,
        "source_detail": source_detail,
        "thread_source": _string(value.get("threadSource"), "thread_source"),
        "agent_nickname": agent_nickname,
        "agent_role": agent_role,
        "status": status,
        "status_detail": status_detail,
        "name": name,
        "model_provider": model_provider,
        "history_mode": history_mode,
        "section": section,
        "section_name": section_name,
        "created_at": _integer(value.get("createdAt"), "created_at"),
        "updated_at": _integer(value.get("updatedAt"), "updated_at"),
        "recency_at": _integer(value.get("recencyAt"), "recency_at"),
        "ephemeral": _boolean(value.get("ephemeral"), "ephemeral"),
        "can_accept_direct_input": _boolean(value.get("canAcceptDirectInput"), "can_accept_direct_input"),
    }


def _empty_thread(state: str, reason: str, *, thread_id: str | None) -> dict[str, Any]:
    return {
        "state": state,
        "currentness": state,
        "thread_id": thread_id,
        "thread": None,
        "source": None,
        "evidence_refs": [],
        "diagnostics": [reason],
        "claim_limit": THREAD_CLAIM_LIMIT,
    }


def _empty_relation(state: str, reason: str, *, thread_id: str, query_kind: str, relation_kind: str) -> dict[str, Any]:
    return {
        "state": state,
        "currentness": state,
        "relation_kind": relation_kind,
        "query_kind": query_kind,
        "anchor_thread_id": thread_id,
        "cursor": None,
        "next_cursor": None,
        "complete_for_query": False,
        "items": [],
        "source": None,
        "evidence_refs": [],
        "diagnostics": [reason],
        "claim_limit": RELATION_CLAIM_LIMIT,
    }


def _goal_projection(
    goal: dict[str, Any],
    thread_id: str,
    observed_at: str,
    *,
    socket_path: str | None = None,
) -> dict[str, Any]:
    source_ref = f"codex-app-server:thread/goal/get:{thread_id}"
    evidence = _evidence(
        method="thread/goal/get",
        thread_id=thread_id,
        observed_at=observed_at,
        query={"threadId": thread_id},
        claim_limit="Exact Goal state returned for this thread at projection read time.",
        socket_path=socket_path,
    )
    return {
        "schema_version": GOAL_SCHEMA,
        "state": "bound",
        "currentness": "current_at_read",
        "thread_id": thread_id,
        "goal": goal,
        "source": {
            "owner": "codex-app-server",
            "ref": source_ref,
            "method": "thread/goal/get",
            "transport": "websocket_unix",
            "query": {"threadId": thread_id},
            "currentness": "current_at_read",
            **({"socket_path": socket_path} if socket_path is not None else {}),
        },
        "evidence_refs": [evidence],
        "diagnostics": [],
        "claim_limit": "Read-only observation of Codex Goal state for one exact thread.",
    }


def _relation_page(
    rpc: Any,
    *,
    thread_id: str,
    query_key: str,
    relation_kind: str,
    observed_at: str,
    socket_path: str | None = None,
) -> dict[str, Any]:
    query = {query_key: thread_id}
    result = rpc.call("thread/list", query)
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise CodexGoalUnavailable("owner_thread_relation_response_invalid")
    next_cursor = result.get("nextCursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise CodexGoalUnavailable("owner_thread_relation_cursor_invalid")
    items = [_thread(item) for item in result["data"]]
    evidence = _evidence(
        method="thread/list",
        thread_id=thread_id,
        observed_at=observed_at,
        query=query,
        claim_limit=RELATION_CLAIM_LIMIT,
        socket_path=socket_path,
    )
    complete = next_cursor is None
    return {
        "state": "bound" if complete else "deferred",
        "currentness": "current_at_read",
        "relation_kind": relation_kind,
        "query_kind": query_key,
        "anchor_thread_id": thread_id,
        "cursor": None,
        "next_cursor": next_cursor,
        "complete_for_query": complete,
        "items": items,
        "source": {
            "owner": "codex-app-server",
            "method": "thread/list",
            "transport": "websocket_unix",
            "query": query,
            "currentness": "current_at_read",
            **({"socket_path": socket_path} if socket_path is not None else {}),
        },
        "evidence_refs": [evidence],
        "diagnostics": [] if complete else ["owner_thread_relation_pagination_incomplete"],
        "claim_limit": RELATION_CLAIM_LIMIT,
    }


def _initialize_rpc(rpc: Any) -> None:
    rpc.call(
        "initialize",
        {
            "clientInfo": {
                "name": "aoa_dashboard",
                "title": "AoA Dashboard read-only Goal and Thread projection",
                "version": "1",
            },
            "capabilities": {"experimentalApi": True},
        },
    )
    rpc.notify("initialized")


def _thread_observations(
    rpc: Any,
    *,
    thread_id: str,
    observed_at: str,
    socket_path: str,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    diagnostics: list[str] = []
    sources: list[dict[str, Any]] = []
    try:
        thread_result = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = _thread(thread_result.get("thread") if isinstance(thread_result, dict) else None, thread_id)
        thread_evidence = _evidence(
            method="thread/read",
            thread_id=thread_id,
            observed_at=observed_at,
            query={"threadId": thread_id, "includeTurns": False},
            socket_path=socket_path,
        )
        thread_view = {
            "state": "bound",
            "currentness": "current_at_read",
            "thread_id": thread_id,
            "thread": thread,
            "source": {
                "owner": "codex-app-server",
                "method": "thread/read",
                "transport": "websocket_unix",
                "query": {"threadId": thread_id, "includeTurns": False},
                "currentness": "current_at_read",
                "socket_path": socket_path,
            },
            "evidence_refs": [thread_evidence],
            "diagnostics": [],
            "claim_limit": THREAD_CLAIM_LIMIT,
        }
        sources.append(thread_evidence)
    except (CodexGoalUnavailable, OSError, TimeoutError) as exc:
        diagnostics.append(str(exc) or "owner_thread_read_unavailable")
        thread_view = _empty_thread("invalid" if "mismatch" in str(exc) else "unknown", str(exc), thread_id=thread_id)

    relations: dict[str, dict[str, Any]] = {}
    for relation_kind, query_key in (
        ("spawn_parent", "parentThreadId"),
        ("history_fork", "ancestorThreadId"),
    ):
        try:
            relation = _relation_page(
                rpc,
                thread_id=thread_id,
                query_key=query_key,
                relation_kind=relation_kind,
                observed_at=observed_at,
                socket_path=socket_path,
            )
            relations[relation_kind] = relation
            sources.extend(relation["evidence_refs"])
            diagnostics.extend(relation["diagnostics"])
        except (CodexGoalUnavailable, OSError, TimeoutError) as exc:
            relation = _empty_relation(
                "invalid" if "invalid" in str(exc) or "mismatch" in str(exc) else "unknown",
                str(exc),
                thread_id=thread_id,
                query_kind=query_key,
                relation_kind=relation_kind,
            )
            relations[relation_kind] = relation
            diagnostics.extend(relation["diagnostics"])
    return thread_view, relations, sources, diagnostics


def _context_empty(state: str, reason: str, *, thread_id: str | None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "owner_schema_version": THREAD_CONTEXT_SCHEMA,
        "state": state,
        "currentness": state,
        "observed_at": None,
        "goal_ref": {"thread_id": thread_id, "owner": "codex-app-server"},
        "goal_projection": empty_goal(state, reason, thread_id=thread_id),
        "thread": _empty_thread(state, reason, thread_id=thread_id),
        "relations": {
            "spawn_parent": _empty_relation(state, reason, thread_id=thread_id or "unresolved", query_kind="parentThreadId", relation_kind="spawn_parent"),
            "history_fork": _empty_relation(state, reason, thread_id=thread_id or "unresolved", query_kind="ancestorThreadId", relation_kind="history_fork"),
        },
        "sources": [],
        "evidence_refs": [],
        "diagnostics": [reason],
        "claim_limit": THREAD_CLAIM_LIMIT,
    }


def observe_codex_goal_context(
    config: dict[str, Any],
    *,
    rpc_factory: Callable[[Any], Any] = UnixWebSocketRpc,
) -> dict[str, Any]:
    """Read one exact Goal, Thread, and bounded relation pages from Codex."""

    goal_binding = config.get("owner_goal_source")
    if not isinstance(goal_binding, dict) or goal_binding.get("enabled") is not True:
        return _context_empty("missing", "owner_binding_disabled", thread_id=None)
    correlation = config.get("current_correlation")
    thread_id = correlation.get("master_thread_id") if isinstance(correlation, dict) else None
    if not isinstance(thread_id, str) or not thread_id:
        return _context_empty("missing", "owner_thread_missing", thread_id=None)
    thread_binding = config.get("owner_thread_source")
    if thread_binding is None:
        thread_binding = {"enabled": True}
    thread_enabled = isinstance(thread_binding, dict) and thread_binding.get("enabled") is True
    thread_disabled_reason = "owner_thread_binding_disabled" if not thread_enabled else None

    observed_at = _now()
    try:
        goal_endpoint = discover_control_socket(config, source_key="owner_goal_source")
        with rpc_factory(goal_endpoint) as goal_rpc:
            _initialize_rpc(goal_rpc)
            goal = _validate_goal(goal_rpc.call("thread/goal/get", {"threadId": thread_id}), thread_id)
            goal_projection = _goal_projection(
                goal,
                thread_id,
                observed_at,
                socket_path=str(goal_endpoint),
            )
            diagnostics: list[str] = []
            sources: list[dict[str, Any]] = list(goal_projection["evidence_refs"])

            if not thread_enabled:
                diagnostics.append(thread_disabled_reason or "owner_thread_binding_disabled")
                thread_view = _empty_thread("missing", thread_disabled_reason or "owner_thread_binding_disabled", thread_id=thread_id)
                relations = {
                    relation_kind: _empty_relation(
                        "missing",
                        thread_disabled_reason or "owner_thread_binding_disabled",
                        thread_id=thread_id,
                        query_kind=query_key,
                        relation_kind=relation_kind,
                    )
                    for relation_kind, query_key in (
                        ("spawn_parent", "parentThreadId"),
                        ("history_fork", "ancestorThreadId"),
                    )
                }
            else:
                try:
                    thread_endpoint = discover_control_socket(config, source_key="owner_thread_source")
                    if thread_endpoint == goal_endpoint:
                        thread_view, relations, thread_sources, thread_diagnostics = _thread_observations(
                            goal_rpc,
                            thread_id=thread_id,
                            observed_at=observed_at,
                            socket_path=str(thread_endpoint),
                        )
                    else:
                        with rpc_factory(thread_endpoint) as thread_rpc:
                            _initialize_rpc(thread_rpc)
                            thread_view, relations, thread_sources, thread_diagnostics = _thread_observations(
                                thread_rpc,
                                thread_id=thread_id,
                                observed_at=observed_at,
                                socket_path=str(thread_endpoint),
                            )
                    sources.extend(thread_sources)
                    diagnostics.extend(thread_diagnostics)
                except (CodexGoalUnavailable, OSError, TimeoutError) as exc:
                    reason = str(exc) or "owner_thread_source_unavailable"
                    diagnostics.append(reason)
                    state = "invalid" if "invalid" in reason or "mismatch" in reason else "unknown"
                    thread_view = _empty_thread(state, reason, thread_id=thread_id)
                    relations = {
                        relation_kind: _empty_relation(
                            state,
                            reason,
                            thread_id=thread_id,
                            query_kind=query_key,
                            relation_kind=relation_kind,
                        )
                        for relation_kind, query_key in (
                            ("spawn_parent", "parentThreadId"),
                            ("history_fork", "ancestorThreadId"),
                        )
                    }

    except (OSError, TimeoutError, CodexGoalUnavailable) as exc:
        reason = str(exc) if str(exc).startswith("owner_") else "owner_transport_unavailable"
        return _context_empty(state_for_owner_error(reason), reason, thread_id=thread_id)

    relation_states = {relation["state"] for relation in relations.values()}
    if thread_view["state"] == "invalid" or "invalid" in relation_states:
        state = "invalid"
    elif thread_view["state"] != "bound" or any(value in {"unknown", "missing"} for value in relation_states):
        state = "deferred"
    elif "deferred" in relation_states:
        state = "deferred"
    else:
        state = "bound"
    return {
        "schema_version": SCHEMA_VERSION,
        "owner_schema_version": THREAD_CONTEXT_SCHEMA,
        "state": state,
        "currentness": "current_at_read",
        "observed_at": observed_at,
        "goal_ref": {
            "thread_id": thread_id,
            "owner": "codex-app-server",
            "source": goal_projection["source"]["ref"],
        },
        "goal_projection": goal_projection,
        "thread": thread_view,
        "relations": relations,
        "sources": sources,
        "evidence_refs": sources,
        "diagnostics": sorted(set(diagnostics)),
        "claim_limit": THREAD_CLAIM_LIMIT,
    }
