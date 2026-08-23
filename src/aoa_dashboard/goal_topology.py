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
# The master owns the state vocabulary.  Current task-local states can embed
# node references (for example ``armed_after_GS32_GS33``), so the adapter only
# validates a bounded opaque token instead of guessing a dashboard enum.
STATE_RE = re.compile(r"^[a-z][A-Za-z0-9_-]{0,95}$")
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
        "branches": [],
        "trajectories": [],
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


def _dependency_closure(node_id: str, by_id: dict[str, dict[str, Any]]) -> list[str]:
    """Return one deterministic dependency closure without inventing a path."""

    ordered: list[str] = []
    visited: set[str] = set()

    def visit(current: str) -> None:
        if current in visited:
            return
        visited.add(current)
        for dependency in by_id[current]["depends_on"]:
            visit(dependency)
        ordered.append(current)

    visit(node_id)
    return ordered


def _branch_projection(
    node: dict[str, Any],
    *,
    evidence_refs: list[dict[str, Any]],
    claim_limit: str,
) -> dict[str, Any]:
    return {
        "ref": f"dag:{node['id']}",
        "kind": "planning_node",
        "node_id": node["id"],
        "title": node["title"],
        "state": node["source_state"],
        "source_state": node["source_state"],
        "observation_state": "bound",
        "identity_state": "unknown",
        "identity_reason": "canonical_branch_owner_not_published",
        "owner": node.get("owner"),
        "scope": node.get("scope"),
        "user_facing": node["user_facing"],
        "depends_on": [f"dag:{item}" for item in node["depends_on"]],
        "evidence_refs": evidence_refs,
        "claim_limit": claim_limit,
    }


def _trajectory_projections(
    nodes: list[dict[str, Any]],
    root_ids: list[str],
    *,
    evidence_refs: list[dict[str, Any]],
    claim_limit: str,
) -> list[dict[str, Any]]:
    by_id = {node["id"]: node for node in nodes}
    trajectories: list[dict[str, Any]] = []
    for root_id in root_ids:
        closure = _dependency_closure(root_id, by_id)
        trajectories.append(
            {
                "ref": f"trajectory:{root_id}",
                "kind": "planning_dependency_closure",
                "frontier_ref": f"dag:{root_id}",
                "node_refs": [f"dag:{item}" for item in closure],
                "state": "bound",
                "complete": True,
                "identity_state": "unknown",
                "identity_reason": "canonical_trajectory_owner_not_published",
                "evidence_refs": evidence_refs,
                "claim_limit": claim_limit,
            }
        )
    return trajectories


def observe_goal_topology(config: dict[str, Any]) -> dict[str, Any]:
    binding = config.get("goal_topology_source")
    if not isinstance(binding, dict) or binding.get("enabled") is not True:
        return _empty("missing", "topology_binding_disabled")
    try:
        path = _source_path(config, binding)
    except ValueError as exc:
        return _empty("invalid", str(exc))
    expected_digest = binding.get("expected_sha256")
    snapshot = read_file_snapshot(
        path,
        expected_digest=expected_digest if isinstance(expected_digest, str) else None,
        parser="json",
    )
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
    if snapshot.currentness == "stale":
        return _empty("stale", "topology_source_stale", evidence)
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
    claim_limit_value = claim_limit
    branches = [
        _branch_projection(node, evidence_refs=[evidence], claim_limit=claim_limit_value)
        for node in nodes
    ]
    trajectories = _trajectory_projections(
        nodes,
        root_ids,
        evidence_refs=[evidence],
        claim_limit=claim_limit_value,
    )
    return {
        "schema_version": DASHBOARD_SCHEMA,
        "state": "bound",
        "currentness": "current_at_read",
        "updated_at": updated_at,
        "nodes": nodes,
        "root_ids": root_ids,
        "branches": branches,
        "trajectories": trajectories,
        "source": {
            "owner": "master-thread",
            "ref": str(path),
            "owner_schema_version": OWNER_SCHEMA,
            "currentness": "current_at_read",
        },
        "evidence_refs": [evidence],
        "diagnostics": [],
        "claim_limit": claim_limit_value,
    }
