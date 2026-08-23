"""Project independently degraded participant dimensions.

This is a dashboard adapter envelope.  It does not mint an aoa-agents role,
select an aoa-models realization, or turn task-local runtime observations into
health or acceptance.
"""

from __future__ import annotations

import re
from typing import Any

from .quality import (
    combine_quality_states,
    normalize_quality_state,
    propagate_quality_state,
    strongest_degradation,
)


SCHEMA_VERSION = "aoa_dashboard_participant_envelope_v1"
DIMENSION_STATES = frozenset({"present", "missing", "unknown", "stale", "deferred", "invalid"})
LIFECYCLE_STATES = frozenset({"planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "reentered"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RELATION_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
RELATION_KEYS = frozenset({"kind", "state", "source", "owner", "parent", "fork", "thread", "branch", "trajectory", "relationship", "relations", "goal"})
CLAIM_LIMIT = (
    "Participant context is a dashboard adapter over bounded owner/task-local "
    "observations. It does not establish human identity, role authority, model "
    "fit or activation, runtime health, proof, review, acceptance, or Goal completion."
)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _refs(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _source(refs: list[dict[str, Any]], *, currentness: str | None, claim_limit: str) -> dict[str, Any]:
    return {
        "owner": "aoa-dashboard",
        "ref": "task-local-actor-activity",
        "currentness": currentness or "unknown",
        "evidence_refs": refs,
        "claim_limit": claim_limit,
    }


def _state(value: Any, fallback: str = "unknown") -> str:
    return normalize_quality_state(value, fallback=fallback)


def _model_subject(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    kind = _string(value.get("kind"))
    source = _string(value.get("source"))
    digest = _string(value.get("digest"))
    if not kind or not source or not digest or not SHA256_RE.fullmatch(digest):
        return None
    return {"kind": kind, "source": source, "digest": digest}


def _safe_relations(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if not isinstance(value, dict) or depth > 2:
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not RELATION_KEY_RE.fullmatch(key):
            continue
        if key not in RELATION_KEYS and not key.endswith(("_id", "_ref")):
            continue
        if isinstance(item, dict):
            nested = _safe_relations(item, depth=depth + 1)
            if nested:
                result[key] = nested
        elif isinstance(item, list):
            values = [str(entry).strip() for entry in item[:32] if isinstance(entry, (str, int)) and str(entry).strip()]
            if values:
                result[key] = values
        elif isinstance(item, (str, int, float, bool)):
            result[key] = item.strip() if isinstance(item, str) else item
    return result


def _owner_diagnostics(owner_goal_context: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for container in (
        owner_goal_context,
        _dict(owner_goal_context.get("goal_projection")),
        _dict(owner_goal_context.get("thread")),
    ):
        diagnostics = container.get("diagnostics")
        if isinstance(diagnostics, list):
            values.extend(item for item in diagnostics if isinstance(item, str) and item)
    return sorted(set(values))


def _task_context(
    actor: dict[str, Any],
    owner_goal_context: dict[str, Any],
    inherited_quality: str | None = None,
) -> dict[str, Any]:
    task = _dict(actor.get("task"))
    correlation = _dict(actor.get("correlation"))
    task_id = _string(task.get("task_id"))
    task_ref = _string(task.get("task_ref")) or task_id
    summary = _string(task.get("summary")) or _string(task.get("title"))
    task_observation_state = "present" if task_id or summary else ("missing" if actor.get("payload_state") == "missing" else "unknown")
    goal_ref = _dict(owner_goal_context.get("goal_ref"))
    exact_thread_id = _string(goal_ref.get("thread_id"))
    observed_thread_id = _string(correlation.get("master_thread_id"))
    thread_view = _dict(owner_goal_context.get("thread"))
    owner_invalid = strongest_degradation(
        owner_goal_context.get("state"),
        owner_goal_context.get("goal_projection", {}).get("state") if isinstance(owner_goal_context.get("goal_projection"), dict) else None,
        thread_view.get("state"),
    ) == "invalid"
    actor_correlation_invalid = normalize_quality_state(correlation.get("state")) == "invalid"
    invalid_reasons: list[str] = []
    if actor_correlation_invalid:
        invalid_reasons.append("participant_actor_correlation_invalid")
    if inherited_quality == "invalid":
        invalid_reasons.append("participant_activity_invalid")
    if owner_invalid:
        invalid_reasons.extend(_owner_diagnostics(owner_goal_context))
        if not _owner_diagnostics(owner_goal_context):
            invalid_reasons.append("participant_owner_context_invalid")

    if invalid_reasons:
        join_state = "invalid"
        join_reason = sorted(set(invalid_reasons))[0]
        joined_thread_id = None
    elif not observed_thread_id:
        join_state = "unknown"
        join_reason = "participant_goal_thread_binding_missing"
        joined_thread_id = None
    elif not exact_thread_id:
        join_state = "unknown"
        join_reason = "participant_goal_thread_owner_context_missing"
        joined_thread_id = None
    elif observed_thread_id != exact_thread_id:
        join_state = "invalid"
        join_reason = "participant_goal_thread_correlation_mismatch"
        joined_thread_id = None
    elif thread_view.get("state") != "bound":
        join_state = "deferred"
        join_reason = "participant_goal_thread_observation_deferred"
        joined_thread_id = None
    else:
        join_state = "present"
        join_reason = None
        joined_thread_id = exact_thread_id
    if join_state == "invalid":
        state = "invalid"
    elif task_observation_state == "present" and join_state == "present":
        state = "present"
    elif task_observation_state == "missing" and join_state in {"missing", "unknown"}:
        state = "missing"
    elif join_state in {"deferred", "unknown"} or task_observation_state == "unknown":
        state = "unknown" if join_state == "unknown" and task_observation_state != "present" else "deferred"
    else:
        state = task_observation_state
    state = propagate_quality_state(state, actor.get("freshness"), inherited_quality)
    return {
        "state": state,
        "observation_state": task_observation_state,
        "task_id": task_id,
        "task_ref": task_ref,
        "title": summary,
        "summary": summary,
        "goal_thread": {
            "state": join_state,
            "thread_id": joined_thread_id,
            "owner": "codex-app-server" if joined_thread_id else None,
            "reason": join_reason,
            "diagnostics": sorted(set(invalid_reasons)),
        },
        "source": _source(
            _refs(actor.get("evidence_refs")),
            currentness=actor.get("freshness"),
            claim_limit="Task and Goal/thread joins remain bounded adapter observations; they do not establish assignment or semantic continuation.",
        ),
        "diagnostics": sorted(set(invalid_reasons)),
        "claim_limit": "Task context retains task-local fields and an explicit exact-thread comparison only; it is not an owner mandate or branch verdict.",
    }


def _identity(actor: dict[str, Any], inherited_quality: str | None = None) -> dict[str, Any]:
    identity = _dict(actor.get("identity"))
    role_id = _string(identity.get("role_id"))
    specialization_id = _string(identity.get("specialization_id"))
    tier_id = _string(identity.get("tier_id"))
    role_resolution_ref = _string(identity.get("role_resolution_ref"))
    obligation_ref = _string(identity.get("obligation_ref"))
    owner_display_name = _string(identity.get("display_name"))
    observed_name = _string(identity.get("name"))
    role_name = _string(identity.get("role_name"))
    candidate_label = _string(identity.get("label"))
    any_observation = any((role_id, specialization_id, tier_id, role_resolution_ref, obligation_ref, candidate_label, observed_name, role_name))
    if any_observation:
        state = "present"
    else:
        state = "missing" if actor.get("payload_state") == "missing" else "unknown"
    state = propagate_quality_state(state, actor.get("freshness"), inherited_quality)
    display_state = "present" if owner_display_name else "missing"
    name_state = "present" if observed_name else ("missing" if actor.get("payload_state") == "missing" else "unknown")
    role_state = "present" if role_id or role_name else ("missing" if actor.get("payload_state") == "missing" else "unknown")
    name_state = propagate_quality_state(name_state, actor.get("freshness"), inherited_quality)
    role_state = propagate_quality_state(role_state, actor.get("freshness"), inherited_quality)
    return {
        "state": state,
        "role_id": role_id,
        "specialization_id": specialization_id,
        "tier_id": tier_id,
        "role_resolution_ref": role_resolution_ref,
        "obligation_ref": obligation_ref,
        "display_name": owner_display_name,
        "display_name_state": display_state,
        "name": observed_name,
        "name_state": name_state,
        "role_name": role_name,
        "role_state": role_state,
        "candidate_label": candidate_label,
        "source": _source(
            _refs(actor.get("evidence_refs")),
            currentness=actor.get("freshness"),
            claim_limit="No canonical owner-published human participant display name was connected; candidate labels remain diagnostics-only.",
        ),
        "claim_limit": "Identity fields are bounded task-local observations unless an explicit owner ref is present; a holder suffix or label is not human identity or role acceptance.",
    }


def _model(actor: dict[str, Any], inherited_quality: str | None = None) -> dict[str, Any]:
    identity = _dict(actor.get("identity"))
    realization = _dict(actor.get("model_realization"))
    model_identity_ref = _string(realization.get("model_identity_ref"))
    model_realization_ref = _string(realization.get("model_realization_ref"))
    fit_projection_ref = _string(realization.get("fit_projection_ref"))
    runtime_subject = _model_subject(realization.get("runtime_subject"))
    candidate_model_id = _string(identity.get("model_id"))
    if model_identity_ref and model_realization_ref and runtime_subject:
        state = "present"
    elif candidate_model_id:
        state = "unknown"
        inherited_model_quality = strongest_degradation(actor.get("freshness"), inherited_quality)
        if inherited_model_quality is not None:
            state = propagate_quality_state("present", inherited_model_quality)
    else:
        state = "missing" if actor.get("payload_state") == "missing" else "unknown"
    state = propagate_quality_state(state, actor.get("freshness"), inherited_quality)
    return {
        "state": state,
        "model_identity_ref": model_identity_ref,
        "model_realization_ref": model_realization_ref,
        "fit_projection_ref": fit_projection_ref,
        "runtime_subject": runtime_subject,
        "candidate_model_id": candidate_model_id,
        "source": _source(
            _refs(actor.get("evidence_refs")),
            currentness=actor.get("freshness"),
            claim_limit="A model slug alone is not an aoa-models identity, fit, activation, or current runtime subject.",
        ),
        "claim_limit": "Model realization is present only with explicit identity, realization, and exact runtime subject refs; candidate values remain bounded diagnostics.",
    }


def _relationships(
    actor: dict[str, Any],
    owner_goal_context: dict[str, Any],
    inherited_quality: str | None = None,
) -> dict[str, Any]:
    task_local = _safe_relations(actor.get("relationships"))
    owner_relations = owner_goal_context.get("relations") if isinstance(owner_goal_context.get("relations"), dict) else {}
    owner_thread_view = _dict(owner_goal_context.get("thread"))
    owner_thread = owner_thread_view.get("thread") if isinstance(owner_thread_view.get("thread"), dict) else {}
    states = [
        normalize_quality_state(task_local.get("state"), fallback="missing" if not task_local else "present"),
        normalize_quality_state(owner_thread_view.get("state"), fallback="unknown"),
    ]
    states.extend(
        normalize_quality_state(_dict(value).get("state"), fallback="unknown")
        for value in owner_relations.values()
        if isinstance(value, dict)
    )
    state = combine_quality_states(*states, all_missing="missing")
    state = propagate_quality_state(state, actor.get("freshness"), inherited_quality)
    return {
        "state": state,
        "task_local": task_local,
        "owner_thread": {
            "state": owner_thread_view.get("state", "missing"),
            "thread_id": owner_thread.get("thread_id"),
            "parent_thread_id": owner_thread.get("parent_thread_id"),
            "forked_from_id": owner_thread.get("forked_from_id"),
            "name": owner_thread.get("name"),
        },
        "owner_relations": owner_relations,
        "claim_limit": "Relations are bounded owner/task-local observations; they do not establish complete branch, trajectory, or participant authority.",
    }


def _runtime(actor: dict[str, Any], inherited_quality: str | None = None) -> dict[str, Any]:
    groups = {name: _dict(actor.get(name)) for name in ("process", "session", "terminal", "wake_return", "usage")}
    states = [_state(group.get("state"), "unknown") for group in groups.values()]
    state = combine_quality_states(*states, all_missing="missing", stale_with_missing=True)
    state = propagate_quality_state(state, actor.get("freshness"), inherited_quality)
    return {
        "state": state,
        "process": groups["process"],
        "session": groups["session"],
        "terminal": groups["terminal"],
        "wake_return": groups["wake_return"],
        "usage": groups["usage"],
        "source": _source(
            _refs(actor.get("evidence_refs")),
            currentness=actor.get("freshness"),
            claim_limit="Runtime fields are observed task-local metadata and do not establish process health, deployment, return acceptance, or completion.",
        ),
        "claim_limit": "Process, session, terminal, wake/return, and usage fields remain independent observations; missing is not zero.",
    }


def _participant(
    actor: dict[str, Any],
    index: int,
    owner_goal_context: dict[str, Any],
    activity_quality: str | None = None,
) -> dict[str, Any]:
    inherited_quality = strongest_degradation(
        activity_quality,
        actor.get("quality_state"),
        actor.get("freshness"),
    )
    identity = _identity(actor, inherited_quality)
    task_context = _task_context(actor, owner_goal_context, inherited_quality)
    model = _model(actor, inherited_quality)
    relationships = _relationships(actor, owner_goal_context, inherited_quality)
    runtime = _runtime(actor, inherited_quality)
    dimensions = {
        "identity": identity["state"],
        "task_context": task_context["state"],
        "model_realization": model["state"],
        "runtime_evidence": runtime["state"],
    }
    quality = combine_quality_states(*dimensions.values(), all_missing="deferred")
    lifecycle_state = _string(actor.get("state")) or "unknown"
    diagnostics = set(task_context.get("diagnostics", []))
    if inherited_quality == "invalid" and activity_quality == "invalid":
        diagnostics.add("participant_activity_invalid")
    return {
        "ref": f"actor:{_string(actor.get('actor_key')) or index}",
        "lifecycle_state": lifecycle_state,
        "quality": quality,
        "dimension_states": dimensions,
        "identity": identity,
        "task_context": task_context,
        "model_realization": model,
        "relationships": relationships,
        "runtime_evidence": runtime,
        "evidence_refs": _refs(actor.get("evidence_refs")),
        "diagnostics": sorted(diagnostics),
        "claim_limit": CLAIM_LIMIT,
    }


def project_participant_context(
    actor_activity: dict[str, Any] | None,
    owner_goal_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the participant envelope without inventing missing dimensions."""

    activity = actor_activity if isinstance(actor_activity, dict) else {}
    owner_context = owner_goal_context if isinstance(owner_goal_context, dict) else {}
    actors = activity.get("actors")
    if not isinstance(actors, list):
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "missing",
            "freshness": "missing",
            "participants": [],
            "summary": {"participant_count": None, "dimension_counts": {}},
            "source": _source([], currentness="missing", claim_limit=CLAIM_LIMIT),
            "diagnostics": ["participant_activity_missing"],
            "claim_limit": CLAIM_LIMIT,
        }
    activity_quality = strongest_degradation(activity.get("state"), activity.get("freshness"))
    participants = [
        _participant(actor, index, owner_context, activity_quality)
        for index, actor in enumerate(actors)
        if isinstance(actor, dict)
    ]
    if not participants:
        return {
            "schema_version": SCHEMA_VERSION,
            "state": "missing",
            "freshness": "missing",
            "participants": [],
            "summary": {"participant_count": 0, "dimension_counts": {}},
            "source": _source(_refs(activity.get("evidence_refs")), currentness=activity.get("freshness"), claim_limit=CLAIM_LIMIT),
            "diagnostics": ["participant_activity_empty"],
            "claim_limit": CLAIM_LIMIT,
        }
    quality = combine_quality_states(*[item["quality"] for item in participants], all_missing="deferred")
    state = "bound" if quality == "present" else quality
    dimensions = ("identity", "task_context", "model_realization", "runtime_evidence")
    counts = {
        dimension: {
            value: sum(item["dimension_states"][dimension] == value for item in participants)
            for value in sorted(DIMENSION_STATES)
        }
        for dimension in dimensions
    }
    diagnostics = sorted(
        {
            reason
            for item in participants
            for reason in (
                *item.get("diagnostics", []),
                item["task_context"].get("goal_thread", {}).get("reason"),
            )
            if reason
        }
    )
    evidence_refs = _refs(activity.get("evidence_refs"))
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "freshness": activity.get("freshness") or state,
        "participants": participants,
        "summary": {"participant_count": len(participants), "dimension_counts": counts},
        "source": _source(evidence_refs, currentness=activity.get("freshness"), claim_limit=CLAIM_LIMIT),
        "evidence_refs": evidence_refs,
        "diagnostics": diagnostics,
        "claim_limit": CLAIM_LIMIT,
    }
