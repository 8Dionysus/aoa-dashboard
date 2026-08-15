from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from .model import LIFECYCLE_STATES, OBSERVATION_QUALITY, STATUS_VOCABULARY, Projection
from .sources import observe_all, observe_owner_surfaces, utc_now
from .state_store import action_intent_summary, annotation_summary


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "bootstrap.json"


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    config_path = Path(path or os.environ.get("AOA_DASHBOARD_CONFIG", DEFAULT_CONFIG))
    with config_path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("dashboard config must be a JSON object")
    return value


def _ref_for(source: dict[str, Any]) -> list[dict[str, Any]]:
    return source.get("evidence_refs", [])


def _node_state(node_id: str, config: dict[str, Any], source_index: dict[str, dict[str, Any]]) -> tuple[str, str]:
    root = Path(__file__).resolve().parents[2]
    checks: dict[str, tuple[bool, str, str]] = {
        "G0": (source_index["goal-anchor"]["state"] == "bound", "Goal Anchor is bound", "goal-anchor"),
        "D1": ((root / "docs" / "BOUNDARIES.md").exists(), "dashboard ownership boundary is present", "dashboard:docs/BOUNDARIES.md"),
        "D2": ((root / "contracts" / "goal_space_projection.schema.json").exists(), "projection contract is present", "dashboard:contracts"),
        "D3": ((root / "src" / "aoa_dashboard" / "sources.py").exists(), "owner adapters are present", "dashboard:src/aoa_dashboard/sources.py"),
        "D4": ((root / "src" / "aoa_dashboard" / "projection.py").exists(), "correlation projection is present", "dashboard:src/aoa_dashboard/projection.py"),
        "D5": (source_index["aoa-session-memory"].get("runtime_state") == "running", "session source is observed as running", ".aoa:session-source"),
        "D6": ((root / "web" / "index.html").exists(), "operator UI is present", "dashboard:web"),
        "D7": ((root / "docs" / "BOUNDARIES.md").exists(), "trust and action boundary is documented", "dashboard:docs/BOUNDARIES.md"),
        "D8": (
            source_index["goal-anchor"]["state"] == "bound" and source_index["aoa-session-memory"].get("runtime_state") == "running",
            "the current Goal and its session source are both visible",
            "goal-anchor + .aoa/session-memory",
        ),
        "D9": (False, "independent evaluator packet is not connected", "aoa-evals:independent-proof-packet"),
        "P∞": (False, "pressure intake is deferred to a future owner route", "dashboard:pressure-inbox:deferred"),
    }
    passed, observation, ref = checks.get(node_id, (False, "node is not mapped", "dashboard:unknown-node"))
    if passed:
        state = "running" if node_id in {"D3", "D4", "D5", "D6", "D8"} else "bound"
    else:
        state = "missing" if node_id == "D9" else "deferred"
    return state, f"{observation}; source {ref}."


def _lifecycle(config: dict[str, Any], source_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    anchor_bound = source_index["goal-anchor"]["state"] == "bound"
    session = source_index["aoa-session-memory"]
    actor_manifest_exists = Path(config["actor_manifest_path"]).exists()
    step_state: dict[str, tuple[str, str, list[dict[str, Any]]]] = {
        "planned": (
            "planned" if anchor_bound else "missing",
            "Goal Anchor names this obligation." if anchor_bound else "Goal Anchor is missing.",
            _ref_for(source_index["goal-anchor"]),
        ),
        "bound": (
            "bound" if actor_manifest_exists else "missing",
            "The actor incarnation binding is present at its configured path." if actor_manifest_exists else "No actor incarnation binding is readable.",
            [_ref_for(source_index["goal-anchor"])[0], {"label": "actor manifest", "kind": "source_path", "ref": config["actor_manifest_path"], "path": config["actor_manifest_path"], "claim_limit": "Binding metadata does not prove execution."}],
        ),
        "running": (
            "running" if session.get("runtime_state") == "running" else "missing",
            "The current session source is readable; this is not a process-health claim." if session.get("runtime_state") == "running" else "No current session source is readable.",
            _ref_for(session),
        ),
        "paused": (
            "paused" if config.get("parent_posture") == "paused" else "unknown",
            "Parent/master posture is recorded as paused for this handoff boundary." if config.get("parent_posture") == "paused" else "Parent posture is not known to this projection.",
            [{"label": "parent posture", "kind": "operator_context", "ref": "goal:parent-posture", "claim_limit": "Posture is not a runtime health or acceptance signal."}],
        ),
        "returned": (
            "deferred",
            "No goal-scoped return receipt is connected; return remains deferred rather than inferred.",
            [_ref_for(source_index["actor-responsibility-receipts"])[0]],
        ),
        "reviewed": (
            "missing",
            "No independent reviewed eval packet for this Goal is connected.",
            _ref_for(source_index["aoa-evals-surface"]),
        ),
        "accepted": (
            "missing",
            "No owner-acceptance record is connected.",
            [{"label": "owner acceptance", "kind": "owner_event", "ref": "owner-acceptance:not-connected", "claim_limit": "Dashboard cannot issue owner acceptance."}],
        ),
        "wake requested": (
            "missing",
            "Wake delivery is not yet represented in the projection; the final handoff command is a later boundary.",
            [{"label": "wake delivery", "kind": "handoff", "ref": "wake-master:not-yet-requested", "claim_limit": "No wake request is claimed before delivery."}],
        ),
        "reentered": (
            "missing",
            "No master re-entry event is connected.",
            [{"label": "master re-entry", "kind": "owner_event", "ref": "master-reentry:not-connected", "claim_limit": "Re-entry cannot be inferred from a local process."}],
        ),
    }
    return [
        {
            "step": step,
            "state": values[0],
            "observation": values[1],
            "evidence_refs": values[2],
            "claim_limit": "Lifecycle label and observation quality remain separate; absence is not a success value.",
        }
        for step, values in step_state.items()
    ]


def build_projection(config_path: str | os.PathLike[str] | None = None) -> Projection:
    config = load_config(config_path)
    sources, source_index = observe_all(config)
    # Keep the unconnected eval source addressable by the lifecycle adapter.
    source_index["aoa-evals-surface"] = next(item for item in sources if item["id"] == "aoa-evals-surface")
    lifecycle = _lifecycle(config, source_index)
    dag: list[dict[str, Any]] = []
    for node in config.get("dag", []):
        state, observation = _node_state(node["id"], config, source_index)
        dag.append(
            {
                "id": node["id"],
                "title": node["title"],
                "pressure": node["pressure"],
                "state": state,
                "observation": observation,
                "claim_limit": "DAG state is a dashboard observation, not owner acceptance or proof.",
                "evidence_refs": [{"label": "node observation", "kind": "derived", "ref": observation, "claim_limit": "Derived node status is bounded to the listed source."}],
            }
        )

    counts = Counter(item["state"] for item in lifecycle)
    counts.update(item["state"] for item in dag)
    counts.update(item["state"] for item in sources)
    state_inventory = [
        {
            "state": state,
            "category": "lifecycle" if state in LIFECYCLE_STATES else "observation_quality",
            "observed_count": counts.get(state, 0),
            "observation": "Observed in this projection." if counts.get(state, 0) else "Not observed; this value remains distinct and is not folded into another state.",
        }
        for state in STATUS_VOCABULARY
    ]
    goal_source = source_index["goal-anchor"]
    goal_metadata = goal_source.get("metadata", {})
    return {
        "schema_version": "aoa_dashboard_projection_v1",
        "generated_at": utc_now(),
        "goal": {
            "goal_id": config["goal_id"],
            "title": config["title"],
            "state": goal_source["state"],
            "anchor_digest": goal_metadata.get("anchor_digest"),
            "source_refs": goal_source.get("evidence_refs", []),
            "claim_limit": "The Goal Anchor is source binding; the dashboard does not own Goal semantics or acceptance.",
        },
        "dag": dag,
        "lifecycle": lifecycle,
        "state_inventory": state_inventory,
        "sources": sources,
        "owner_surfaces": observe_owner_surfaces(config),
        "annotations": annotation_summary(),
        "action_intents": action_intent_summary(),
        "claim_limits": config.get("claim_limits", []),
        "operator_posture": {
            "read_model": "derived",
            "action_execution": "disabled",
            "currentness": "per-source",
            "unknown_is_not_zero": True,
        },
    }
