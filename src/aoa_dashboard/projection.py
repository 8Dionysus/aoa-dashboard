from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from .cursor import (
    migrate_legacy_correlation_input,
    observations_from_correlation,
    redact_legacy_metadata,
    read_correlation_checkpoint,
    read_correlation_observation_log,
    rebuild_goal_local_projection,
)
from .model import LIFECYCLE_STATES, STATUS_VOCABULARY, Projection
from .pressure import build_pressure_inbox, migrate_legacy_pressure_candidates
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


def _typed_source_refs(value: Any, result: dict[tuple[str, str], dict[str, Any]]) -> None:
    """Collect already-attested typed refs without inventing a second source label."""

    if isinstance(value, dict):
        ref = value.get("ref")
        kind = value.get("kind")
        if isinstance(ref, str) and isinstance(kind, str) and "currentness" in value and "owner" in value:
            result.setdefault((ref, kind), value)
        for item in value.values():
            _typed_source_refs(item, result)
    elif isinstance(value, list):
        for item in value:
            _typed_source_refs(item, result)


def _attest_pressure_records(records: Any, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace configured source-shaped refs with the exact one-read source ref."""

    if not isinstance(records, list):
        return []
    source_map: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        _typed_source_refs(source, source_map)
    result: list[dict[str, Any]] = []
    for record in records:
        item = json.loads(json.dumps(record))

        def replace(value: Any) -> Any:
            if isinstance(value, dict):
                ref = value.get("ref")
                kind = value.get("kind")
                if isinstance(ref, str) and isinstance(kind, str) and (ref, kind) in source_map:
                    return json.loads(json.dumps(source_map[(ref, kind)]))
                return {key: replace(child) for key, child in value.items()}
            if isinstance(value, list):
                return [replace(child) for child in value]
            return value

        result.append(replace(item))
    return result


def _node_state(node_id: str, config: dict[str, Any], source_index: dict[str, dict[str, Any]]) -> tuple[str, str]:
    root = Path(__file__).resolve().parents[2]
    correlation = source_index["task-local-correlation"]
    goal_local = source_index.get("goal-local-correlation", {})
    pressure_inbox = source_index.get("pressure-inbox", {})
    correlation_metadata = correlation.get("metadata", {})
    correlation_summary = correlation_metadata.get("summary", {}) if isinstance(correlation_metadata, dict) else {}
    correlation_bound = correlation.get("state") in {"bound", "deferred"} and bool(correlation_summary.get("reentered"))
    checks: dict[str, tuple[bool, str, str]] = {
        "G0": (source_index["goal-anchor"]["state"] == "bound", "Goal Anchor is bound", "goal-anchor"),
        "D1": ((root / "docs" / "BOUNDARIES.md").exists(), "dashboard ownership boundary is present", "dashboard:docs/BOUNDARIES.md"),
        "D2": ((root / "contracts" / "goal_space_projection.schema.json").exists(), "projection contract is present", "dashboard:contracts"),
        "D3": ((root / "src" / "aoa_dashboard" / "sources.py").exists(), "owner adapters are present", "dashboard:src/aoa_dashboard/sources.py"),
        "D4": (
            (root / "src" / "aoa_dashboard" / "cursor.py").exists()
            and goal_local.get("status") in {"current", "conflicted"},
            "versioned cursor/checkpoint correlation projection is available" if goal_local.get("status") in {"current", "conflicted"} else "versioned cursor/checkpoint correlation projection is degraded",
            "dashboard:correlation_read_model",
        ),
        "D5": (correlation_bound, "task-local return/wake correlation is bound", "dashboard:task-local-correlation"),
        "D6": ((root / "web" / "index.html").exists(), "operator UI is present", "dashboard:web"),
        "D7": ((root / "docs" / "BOUNDARIES.md").exists(), "trust and action boundary is documented", "dashboard:docs/BOUNDARIES.md"),
        "D8": (
            source_index["goal-anchor"]["state"] == "bound" and correlation_bound,
            "the current Goal and task-local correlation surface are both visible",
            "goal-anchor + dashboard:task-local-correlation",
        ),
        "D9": (False, "independent evaluator packet is not connected", "aoa-evals:independent-proof-packet"),
        "P∞": (
            pressure_inbox.get("status") in {"current", "conflicted", "deferred"}
            and bool(pressure_inbox.get("items") or pressure_inbox.get("legacy_candidates")),
            "structured pressure inbox retains a bounded next route" if pressure_inbox.get("items") else "legacy pressure candidates remain deferred until required fields are supplied",
            "dashboard:pressure_inbox",
        ),
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
            "Validated v2 wake delivery is represented as transport admission only." if wake_state == "wake requested" else "No validated v2 wake delivery is available.",
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
    correlation_source = source_index["task-local-correlation"]
    current_correlation = config.get("current_correlation") if isinstance(config.get("current_correlation"), dict) else {}
    master_thread_id = current_correlation.get("master_thread_id")
    if not isinstance(master_thread_id, str) or not master_thread_id:
        master_thread_id = "unresolved-master-thread"
    live_observations = observations_from_correlation(
        correlation_source,
        goal_id=str(config.get("goal_id", "unresolved-goal")),
        master_thread_id=master_thread_id,
    )
    projection_config = config.get("correlation_projection") if isinstance(config.get("correlation_projection"), dict) else {}
    persisted_observations: list[dict[str, Any]] = []
    persistence_errors: list[str] = []
    checkpoint: dict[str, Any] | None = None
    observation_log_path = projection_config.get("observation_log_path")
    checkpoint_path = projection_config.get("checkpoint_path")
    if isinstance(observation_log_path, str) and observation_log_path:
        persisted_observations, log_errors = read_correlation_observation_log(observation_log_path)
        persistence_errors.extend(f"observation_log:{error}" for error in log_errors)
    if isinstance(checkpoint_path, str) and checkpoint_path:
        checkpoint, checkpoint_read_errors = read_correlation_checkpoint(checkpoint_path)
        persistence_errors.extend(f"checkpoint_file:{error}" for error in checkpoint_read_errors)
    goal_local_correlation = rebuild_goal_local_projection(
        goal_id=str(config.get("goal_id", "unresolved-goal")),
        master_thread_id=master_thread_id,
        observations=[*persisted_observations, *live_observations],
        checkpoint=checkpoint,
    )
    if persistence_errors:
        goal_local_correlation["status"] = "invalid"
        goal_local_correlation["rebuild"]["deterministic"] = False
        goal_local_correlation["rebuild"]["replay_safe"] = False
        goal_local_correlation["rebuild"]["errors"].extend(persistence_errors)
    goal_local_correlation["migration"] = migrate_legacy_correlation_input(config, correlation_source)
    goal_local_correlation["storage"] = {
        "observation_log_path": observation_log_path,
        "checkpoint_path": checkpoint_path,
        "durability": "locked_recoverable_log_ahead_checkpoint",
        "two_file_atomicity": False,
        "crash_recovery": "next_locked_invocation_rebuilds_from_valid_log_and_replaces_checkpoint",
        "claim_limit": "The dashboard never overwrites owner source; durable local retention requires an explicit bounded write route.",
    }
    legacy_pressure = migrate_legacy_pressure_candidates(config, correlation_source)
    pressure_records = _attest_pressure_records(
        config.get("pressure_inbox", []) if isinstance(config.get("pressure_inbox", []), list) else [],
        [source_index["goal-anchor"], correlation_source],
    )
    pressure_inbox = build_pressure_inbox(
        goal_id=str(config.get("goal_id", "unresolved-goal")),
        records=pressure_records,
        legacy_candidates=legacy_pressure,
    )
    source_index["goal-local-correlation"] = {"status": goal_local_correlation.get("status")}
    source_index["pressure-inbox"] = pressure_inbox
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
    correlation_source = source_index["task-local-correlation"]
    correlation = correlation_source.get("metadata", {})
    safe_correlation = redact_legacy_metadata(
        {
            **correlation,
            "state": correlation_source.get("state", "unknown"),
            "freshness": correlation_source.get("freshness", "unknown"),
            "degradation": correlation_source.get("degradation", []),
        }
    )
    safe_sources = redact_legacy_metadata(sources)
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
        "correlation": safe_correlation,
        "correlation_read_model": goal_local_correlation,
        "pressure_inbox": pressure_inbox,
        "current_holder": safe_correlation.get("current_holder", {"scope": "current_correlation", "claim_limit": "Current holder is not runtime authority."}),
        "dag": dag,
        "lifecycle": lifecycle,
        "state_inventory": state_inventory,
        "sources": safe_sources,
        "owner_surfaces": observe_owner_surfaces(config),
        "annotations": annotation_summary(),
        "action_intents": action_intent_summary(),
        "claim_limits": [
            *config.get("claim_limits", []),
            "The versioned Goal-local cursor is deterministic over canonical observations; cursor drift fails closed.",
            "Conflicting observations and their provenance remain visible with no dashboard-selected winner.",
            "Pressure Inbox routes are display-only and carry effect:none; an owner must decide and execute any action.",
        ],
        "operator_posture": {
            "read_model": "derived",
            "action_execution": "disabled",
            "currentness": "per-source",
            "unknown_is_not_zero": True,
        },
    }
