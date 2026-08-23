"""Typed, read-only join for the current Goal, Master filter, and topology."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .quality import combine_freshness, combine_quality_states, normalize_quality_state


SCHEMA_VERSION = "aoa_dashboard_master_context_projection_v1"
CLAIM_LIMIT = (
    "Read-only dashboard join of exact Goal/thread metadata, task-local Master "
    "filter evidence, catalog currentness, and planning topology. It does not "
    "establish branch authority, actor assignment, runtime health, proof, "
    "acceptance, or action permission."
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _refs(*values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            key = (str(item.get("kind", "")), str(item.get("ref", "")))
            if key in seen:
                continue
            seen.add(key)
            result.append(deepcopy(item))
    return result


def project_master_context(
    owner_goal_context: dict[str, Any] | None,
    correlation: dict[str, Any] | None,
    goal_catalog: dict[str, Any] | None,
    goal_topology: dict[str, Any] | None,
) -> dict[str, Any]:
    """Join owner facts without promoting any source to another owner's truth."""

    owner = owner_goal_context if isinstance(owner_goal_context, dict) else {}
    correlation_view = correlation if isinstance(correlation, dict) else {}
    catalog = goal_catalog if isinstance(goal_catalog, dict) else {}
    topology = goal_topology if isinstance(goal_topology, dict) else {}
    owner_thread = _dict(owner.get("thread"))
    thread = owner_thread.get("thread") if isinstance(owner_thread.get("thread"), dict) else None
    goal_projection = _dict(owner.get("goal_projection"))
    goal = goal_projection.get("goal") if isinstance(goal_projection.get("goal"), dict) else None
    relations = owner.get("relations") if isinstance(owner.get("relations"), dict) else {}
    master_filter = correlation_view.get("master_filter")
    current_holder = correlation_view.get("current_holder")
    master_filter_currentness = _dict(master_filter).get("currentness")
    if isinstance(master_filter_currentness, dict):
        master_filter_currentness = master_filter_currentness.get("state")

    quality_values = [
        normalize_quality_state(owner.get("state")),
        normalize_quality_state(correlation_view.get("state")),
    ]
    if master_filter_currentness is not None:
        quality_values.append(normalize_quality_state(master_filter_currentness))
    quality_state = combine_quality_states(*quality_values, all_missing="missing")
    state = "bound" if quality_state == "present" else quality_state
    currentness = combine_freshness(
        owner.get("currentness"),
        correlation_view.get("freshness"),
        master_filter_currentness,
        fallback=state,
    )
    diagnostics = {
        item
        for value in (owner.get("diagnostics"), correlation_view.get("degradation"))
        if isinstance(value, list)
        for item in value
        if isinstance(item, str) and item
    }
    if isinstance(owner_thread.get("diagnostics"), list):
        diagnostics.update(item for item in owner_thread["diagnostics"] if isinstance(item, str) and item)

    sources = [
        {
            "owner": "codex-app-server",
            "ref": owner.get("goal_ref", {}).get("source") if isinstance(owner.get("goal_ref"), dict) else None,
            "currentness": owner.get("currentness"),
            "claim_limit": "Exact Goal/thread owner observation only.",
        },
        {
            "owner": "master-thread",
            "ref": _dict(master_filter).get("ref"),
            "currentness": _dict(master_filter).get("currentness"),
            "claim_limit": "Task-local Master filter disposition only.",
        },
        {
            "owner": "aoa-session-memory",
            "ref": _dict(catalog.get("source")).get("ref"),
            "currentness": catalog.get("currentness"),
            "claim_limit": "Goal catalog navigation currentness only.",
        },
        {
            "owner": "master-thread",
            "ref": _dict(topology.get("source")).get("ref"),
            "currentness": topology.get("currentness"),
            "claim_limit": "Planning topology only.",
        },
    ]
    sources = [item for item in sources if isinstance(item.get("ref"), str) and item.get("ref")]

    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "currentness": currentness,
        "goal_ref": deepcopy(owner.get("goal_ref")) if isinstance(owner.get("goal_ref"), dict) else {"thread_id": None, "owner": "codex-app-server"},
        "goal": deepcopy(goal),
        "thread": deepcopy(thread),
        "thread_observation": deepcopy(owner_thread),
        "relations": deepcopy(relations),
        "master_filter": deepcopy(master_filter) if isinstance(master_filter, dict) else None,
        "current_holder": deepcopy(current_holder) if isinstance(current_holder, dict) else None,
        "goal_catalog": {
            "state": catalog.get("state", "missing"),
            "currentness": catalog.get("currentness", "missing"),
            "source": deepcopy(catalog.get("source")),
            "claim_limit": "Goal catalog navigation remains owned by aoa-session-memory.",
        },
        "topology": {
            "state": topology.get("state", "missing"),
            "currentness": topology.get("currentness", "missing"),
            "frontier_refs": [f"dag:{item}" for item in topology.get("root_ids", []) if isinstance(item, str)],
            "branch_count": len(topology.get("branches", [])) if isinstance(topology.get("branches"), list) else 0,
            "trajectory_count": len(topology.get("trajectories", [])) if isinstance(topology.get("trajectories"), list) else 0,
            "claim_limit": "Planning topology is not canonical branch lifecycle or trajectory authority.",
        },
        "sources": sources,
        "evidence_refs": _refs(
            owner.get("evidence_refs"),
            correlation_view.get("evidence_refs"),
            catalog.get("evidence_refs"),
            topology.get("evidence_refs"),
        ),
        "diagnostics": sorted(diagnostics),
        "claim_limit": CLAIM_LIMIT,
    }
