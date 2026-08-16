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
    correlation = source_index["task-local-correlation"]
    correlation_metadata = correlation.get("metadata", {})
    correlation_summary = correlation_metadata.get("summary", {}) if isinstance(correlation_metadata, dict) else {}
    correlation_bound = correlation.get("state") in {"bound", "deferred"} and bool(correlation_summary.get("reentered"))
    checks: dict[str, tuple[bool, str, str]] = {
        "G0": (source_index["goal-anchor"]["state"] == "bound", "Goal Anchor is bound", "goal-anchor"),
        "D1": ((root / "docs" / "BOUNDARIES.md").exists(), "dashboard ownership boundary is present", "dashboard:docs/BOUNDARIES.md"),
        "D2": ((root / "contracts" / "goal_space_projection.schema.json").exists(), "projection contract is present", "dashboard:contracts"),
        "D3": ((root / "src" / "aoa_dashboard" / "sources.py").exists(), "owner adapters are present", "dashboard:src/aoa_dashboard/sources.py"),
        "D4": ((root / "src" / "aoa_dashboard" / "projection.py").exists(), "correlation projection is present", "dashboard:src/aoa_dashboard/projection.py"),
        "D5": (correlation_bound, "task-local return/wake correlation is bound", "dashboard:task-local-correlation"),
        "D6": ((root / "web" / "index.html").exists(), "operator UI is present", "dashboard:web"),
        "D7": ((root / "docs" / "BOUNDARIES.md").exists(), "trust and action boundary is documented", "dashboard:docs/BOUNDARIES.md"),
        "D8": (
            source_index["goal-anchor"]["state"] == "bound" and correlation_bound,
            "the current Goal and task-local correlation surface are both visible",
            "goal-anchor + dashboard:task-local-correlation",
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
    correlation = source_index["task-local-correlation"]
    correlation_metadata = correlation.get("metadata", {})
    historical = config.get("historical_bootstrap", {})
    if not isinstance(historical, dict):
        historical = {}
    historical_manifest_path = historical.get("actor_manifest_path", config.get("actor_manifest_path", ""))
    correlation_refs = _ref_for(correlation)
    if not correlation_refs:
        correlation_refs = [{"label": "current correlation", "kind": "derived", "ref": "current-correlation:unresolved", "claim_limit": "Current correlation is unresolved."}]
    correlation_state = correlation.get("state", "missing")
    summary = correlation_metadata.get("summary", {}) if isinstance(correlation_metadata, dict) else {}
    wake_schema_versions = sorted(
        {
            envelope.get("wake_observation", {}).get("source_schema_version")
            for envelope in correlation_metadata.get("envelopes", [])
            if isinstance(envelope, dict)
            and isinstance(envelope.get("wake_observation"), dict)
            and envelope["wake_observation"].get("source_schema_version")
        }
    )
    wake_schema_label = ", ".join(wake_schema_versions) or "source-qualified"
    has_return = bool(summary.get("filtered_return_ids"))
    has_wake = bool(summary.get("reentered"))
    has_reentry = bool(summary.get("reentered"))
    bound_state = "bound" if correlation_state in {"bound", "deferred"} and has_reentry else correlation_state
    if correlation_state == "invalid":
        returned_state = wake_state = reentry_state = "invalid"
    elif has_return:
        returned_state = "returned"
        wake_state = "wake requested" if has_wake else "missing"
        reentry_state = "reentered" if has_reentry else "missing"
    else:
        returned_state = "missing" if correlation_state == "missing" else "deferred"
        wake_state = "missing" if correlation_state == "missing" else "deferred"
        reentry_state = "missing" if correlation_state == "missing" else "deferred"
    step_state: dict[str, tuple[str, str, list[dict[str, Any]]]] = {
        "planned": (
            "planned" if anchor_bound else "missing",
            "Goal Anchor names this obligation." if anchor_bound else "Goal Anchor is missing.",
            _ref_for(source_index["goal-anchor"]),
        ),
        "bound": (
            bound_state,
            "Current Goal/thread/task-local correlation is bound; one residual candidate remains deferred and the bootstrap incarnation remains historical." if bound_state == "bound" and correlation_state == "deferred" else ("Current Goal/thread/task-local correlation is bound; the bootstrap incarnation remains historical." if bound_state == "bound" else "Current Goal/thread correlation is not bound."),
            [_ref_for(source_index["goal-anchor"])[0], *correlation_refs],
        ),
        "running": (
            "deferred",
            "The configured bootstrap session is historical; no current holder process or runtime health is inferred from it.",
            _ref_for(session) + ([{"label": "historical actor manifest", "kind": "source_path", "ref": historical_manifest_path, "path": historical_manifest_path, "claim_limit": "Historical bootstrap binding is not the current holder or runtime health."}] if historical_manifest_path else []),
        ),
        "paused": (
            "paused" if config.get("parent_posture") == "paused" else "unknown",
            "Parent/master posture is recorded as paused for this handoff boundary." if config.get("parent_posture") == "paused" else "Parent posture is not known to this projection.",
            [{"label": "parent posture", "kind": "operator_context", "ref": "goal:parent-posture", "claim_limit": "Posture is not a runtime health or acceptance signal."}],
        ),
        "returned": (
            returned_state,
            "Master-filtered Luna return is correlated by exact handoff ref and SHA-256." if returned_state == "returned" else "No valid master-filtered return is available.",
            correlation_refs,
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
            wake_state,
            (
                f"Validated {wake_schema_label} wake delivery is represented as transport admission only."
                if wake_state == "wake requested"
                else "No validated wake delivery is available."
            ),
            correlation_refs,
        ),
        "reentered": (
            reentry_state,
            "Bounded master re-entry correlation uses exact accepted_turn_id plus the master filter; semantic continuation is not claimed." if reentry_state == "reentered" else "Re-entry is withheld without exact accepted_turn_id plus a valid master filter.",
            correlation_refs,
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
    correlation = source_index["task-local-correlation"].get("metadata", {})
    return {
        "schema_version": "aoa_dashboard_projection_v1",
        "generated_at": utc_now(),
        "goal": {
            "goal_id": config["goal_id"],
            "title": config["title"],
            "state": goal_source["state"],
            "anchor_digest": goal_metadata.get("anchor_digest"),
            "master_thread_id": config.get("current_correlation", {}).get("master_thread_id"),
            "source_refs": goal_source.get("evidence_refs", []),
            "claim_limit": "The Goal Anchor is source binding; the dashboard does not own Goal semantics or acceptance.",
        },
        "correlation": correlation,
        "current_holder": correlation.get("current_holder", {"scope": "current_correlation", "claim_limit": "Current holder is not runtime authority."}),
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
