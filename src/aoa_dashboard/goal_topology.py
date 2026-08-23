"""Fail-closed projection of the master-owned task-local Goal DAG."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .source_binding import read_file_snapshot, snapshot_ref


OWNER_SCHEMA = "aoa_dashboard_goal_space_task_dag_v1"
DASHBOARD_SCHEMA = "aoa_dashboard_goal_topology_projection_v1"
NODE_ID_RE = re.compile(r"^[A-Z][A-Z0-9-]{0,23}$")
STATE_RE = re.compile(r"^[a-z][a-z0-9_]{0,95}$")
TECHNICAL_TITLE_RE = re.compile(
    r"(?:^[/~.]|/(?:home|srv|tmp|var|run|etc|opt|usr)/|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
    r"\b(?:sha256:)?[0-9a-f]{40,64}\b|"
    r"\b(?:schema_version|artifact_type|thread_id|wake_receipt|luna_handoff)\b|"
    r"\.(?:jsonl?|toml|ya?ml|service|socket|target)(?:\b|$))",
    flags=re.IGNORECASE,
)


def _empty(state: str, reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": state,
        "currentness": state,
        "nodes": [],
        "root_ids": [],
        "source": None,
        "evidence_refs": [evidence] if evidence else [],
        "diagnostics": [reason],
        "claim_limit": "Master-owned task-local planning topology; no node is proof, acceptance or runtime health.",
    }


def _source_path(config: dict[str, Any], binding: dict[str, Any]) -> Path:
    correlation = config.get("current_correlation")
    task_local = correlation.get("task_local_dir") if isinstance(correlation, dict) else None
    relative = binding.get("relative_path")
    if not isinstance(task_local, str) or not task_local:
        raise ValueError("topology_task_local_missing")
    if not isinstance(relative, str) or not relative:
        raise ValueError("topology_relative_path_missing")
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("topology_relative_path_invalid")
    root = Path(task_local).resolve(strict=False)
    path = (root / relative_path).resolve(strict=False)
    if path != root and root not in path.parents:
        raise ValueError("topology_path_escape")
    return path


def _human(value: Any, field: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}_invalid")
    result = " ".join(value.split())
    if not result or len(result) > maximum or TECHNICAL_TITLE_RE.search(result):
        raise ValueError(f"{field}_invalid")
    return result


def _node(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("topology_node_invalid")
    node_id = value.get("id")
    state = value.get("state")
    if not isinstance(node_id, str) or not NODE_ID_RE.fullmatch(node_id):
        raise ValueError("topology_node_id_invalid")
    if not isinstance(state, str) or not STATE_RE.fullmatch(state):
        raise ValueError("topology_node_state_invalid")
    dependencies = value.get("depends_on", [])
    if (
        not isinstance(dependencies, list)
        or len(dependencies) > 32
        or any(not isinstance(item, str) or not NODE_ID_RE.fullmatch(item) for item in dependencies)
        or len(dependencies) != len(set(dependencies))
    ):
        raise ValueError("topology_dependencies_invalid")
    owner = value.get("owner")
    if owner is not None and (not isinstance(owner, str) or not owner or len(owner) > 160):
        raise ValueError("topology_owner_invalid")
    user_facing = value.get("user_facing", False)
    if not isinstance(user_facing, bool):
        raise ValueError("topology_user_facing_invalid")
    scope = value.get("scope")
    if scope is not None:
        scope = _human(scope, "topology_scope", maximum=480)
    return {
        "id": node_id,
        "title": _human(value.get("title"), "topology_title", maximum=112),
        "source_state": state,
        "depends_on": dependencies,
        "owner": owner,
        "scope": scope,
        "user_facing": user_facing,
    }


def _validate_graph(nodes: list[dict[str, Any]]) -> list[str]:
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        raise ValueError("topology_duplicate_node")
    for node in nodes:
        if node["id"] in node["depends_on"] or any(item not in by_id for item in node["depends_on"]):
            raise ValueError("topology_dependency_missing")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("topology_cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in by_id[node_id]["depends_on"]:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in by_id:
        visit(node_id)
    depended_on = {dependency for node in nodes for dependency in node["depends_on"]}
    return [node["id"] for node in nodes if node["id"] not in depended_on]


def observe_goal_topology(config: dict[str, Any]) -> dict[str, Any]:
    binding = config.get("goal_topology_source")
    if not isinstance(binding, dict) or binding.get("enabled") is not True:
        return _empty("missing", "topology_binding_disabled")
    try:
        path = _source_path(config, binding)
    except ValueError as exc:
        return _empty("invalid", str(exc))
    snapshot = read_file_snapshot(path, parser="json")
    evidence = snapshot_ref(
        snapshot,
        label="Current Goal topology",
        kind="goal_topology_snapshot",
        owner="master-thread",
        access_scope="owner_bounded",
        authority="master_decision",
        claim_policy="master_decision_disposition",
        claim_limit="Master-owned task-local planning topology; no node is proof, acceptance or runtime health.",
    )
    if snapshot.currentness == "missing":
        return _empty("missing", "topology_source_missing", evidence)
    if snapshot.currentness == "invalid" or not isinstance(snapshot.parsed, dict):
        return _empty("invalid", "topology_source_invalid", evidence)
    payload = snapshot.parsed
    try:
        correlation = config.get("current_correlation")
        thread_id = correlation.get("master_thread_id") if isinstance(correlation, dict) else None
        if payload.get("schema_version") != OWNER_SCHEMA:
            raise ValueError("topology_schema_unsupported")
        if not isinstance(thread_id, str) or payload.get("goal_ref") != thread_id:
            raise ValueError("topology_goal_mismatch")
        updated_at = payload.get("updated_at")
        if not isinstance(updated_at, str) or len(updated_at) > 40:
            raise ValueError("topology_updated_at_invalid")
        datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        claim_limit = _human(payload.get("claim_limit"), "topology_claim_limit", maximum=480)
        values = payload.get("nodes")
        if not isinstance(values, list) or not values or len(values) > 100:
            raise ValueError("topology_nodes_invalid")
        nodes = [_node(value) for value in values]
        root_ids = _validate_graph(nodes)
        if not root_ids:
            raise ValueError("topology_root_missing")
    except (ValueError, TypeError) as exc:
        return _empty("invalid", str(exc), evidence)
    evidence["currentness"] = "current_at_read"
    evidence["freshness"] = "current_at_read"
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": "bound",
        "currentness": "current_at_read",
        "updated_at": updated_at,
        "nodes": nodes,
        "root_ids": root_ids,
        "source": {
            "owner": "master-thread",
            "ref": str(path),
            "owner_schema_version": OWNER_SCHEMA,
            "currentness": "current_at_read",
        },
        "evidence_refs": [evidence],
        "diagnostics": [],
        "claim_limit": claim_limit,
    }
