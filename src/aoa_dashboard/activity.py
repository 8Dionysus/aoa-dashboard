from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


ACTIVITY_SCHEMA_VERSION = "aoa_dashboard_actor_activity_v1"
MAX_SAFE_TEXT = 256
ACTIVITY_CLAIM_LIMIT = (
    "This is a dashboard-owned summary of allowlisted task-local metadata. "
    "It does not establish process health, runtime success, role meaning, proof, "
    "review, acceptance, or semantic continuation. Missing and unknown fields are "
    "not converted to zero."
)
FIELD_CLAIM_LIMIT = (
    "The value is retained only when an allowlisted scalar field is present in the "
    "task-local payload; it remains an observation, not owner truth."
)


def _lookup(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _candidate_paths(paths: Iterable[str]) -> list[str]:
    direct = list(paths)
    roots = ("actor_activity", "activity", "runtime_activity", "execution", "runtime")
    return [*direct, *(f"{root}.{path}" for root in roots for path in direct)]


def _safe_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:MAX_SAFE_TEXT]
    return None


def _safe_identifier(value: Any) -> str | None:
    text = _safe_text(value)
    if text is not None:
        return text
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _safe_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or value < 0:
        return None
    return value


def _first_text(payloads: list[dict[str, Any]], paths: Iterable[str]) -> str | None:
    for payload in payloads:
        for path in _candidate_paths(paths):
            value = _lookup(payload, path)
            result = _safe_text(value)
            if result is not None:
                return result
    return None


def _first_identifier(payloads: list[dict[str, Any]], paths: Iterable[str]) -> str | None:
    for payload in payloads:
        for path in _candidate_paths(paths):
            value = _lookup(payload, path)
            result = _safe_identifier(value)
            if result is not None:
                return result
    return None


def _first_number(
    payloads: list[dict[str, Any]], paths: Iterable[str]
) -> tuple[int | float | None, bool, bool]:
    found = False
    invalid = False
    for payload in payloads:
        for path in _candidate_paths(paths):
            value = _lookup(payload, path)
            if value is None:
                continue
            found = True
            result = _safe_number(value)
            if result is not None:
                return result, True, invalid
            invalid = True
    return None, found, invalid


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _bounded_path(task_root: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        return None
    root = task_root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if resolved.parent != root:
        return None
    return resolved


def _read_payload(
    task_root: Path, ref: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, Path | None, str | None]:
    if isinstance(ref, dict) and (
        ref.get("freshness") == "missing"
        or "source_missing" in ref.get("degradation", [])
    ):
        return None, None, "payload is missing"
    ref_value = ref.get("ref") if isinstance(ref, dict) else None
    path = _bounded_path(task_root, ref_value)
    if path is None:
        return None, None, "reference is missing or outside the bounded task-local directory"
    if not path.is_file():
        return None, path, "payload is missing"
    expected_digest = ref.get("sha256") if isinstance(ref, dict) else None
    actual_digest = _sha256(path)
    if expected_digest and actual_digest != expected_digest:
        return None, path, "payload changed after correlation read"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, path, "payload is unreadable"
    if not isinstance(value, dict):
        return None, path, "payload is not an object"
    return value, path, None


def _unique_refs(*refs: dict[str, Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = (str(ref.get("kind", "")), str(ref.get("ref", "")))
        if key in seen:
            continue
        seen.add(key)
        result.append(ref)
    return result


def _group_state(payloads: list[dict[str, Any]], errors: list[str], observed: bool) -> str:
    if any(error != "handoff payload missing" and error != "wake payload missing" for error in errors):
        return "invalid"
    if not payloads:
        return "missing"
    return "observed" if observed else "unknown"


def _build_actor(
    envelope: dict[str, Any],
    payloads: list[dict[str, Any]],
    payload_errors: list[str],
) -> dict[str, Any]:
    return_observation = envelope.get("return_observation") if isinstance(envelope.get("return_observation"), dict) else {}
    wake_observation = envelope.get("wake_observation") if isinstance(envelope.get("wake_observation"), dict) else {}
    lifecycle = envelope.get("lifecycle") if isinstance(envelope.get("lifecycle"), dict) else {}
    master_filter = envelope.get("master_filter") if isinstance(envelope.get("master_filter"), dict) else {}
    return_id = _safe_identifier(return_observation.get("return_id"))
    actor_id = _first_identifier(
        payloads,
        ("actor_id", "identity.actor_id", "identity.identity_key", "child_agent_id"),
    )
    actor_label = _first_text(
        payloads,
        ("actor.name", "responsibility_state.holder", "owner.name", "reviewer.name"),
    )
    incarnation_id = _first_identifier(
        payloads,
        ("incarnation_id", "incarnation", "identity.incarnation_id", "actor.incarnation_id"),
    )
    role_id = _first_identifier(
        payloads,
        (
            "role_id",
            "role.id",
            "identity.role_id",
            "desired_role",
            "actor.role",
            "actor.kind",
            "owner.role",
            "reviewer.role",
        ),
    )
    mandate_id = _first_identifier(payloads, ("mandate_id", "mandate.id", "identity.mandate_id"))
    obligation_id = _first_identifier(payloads, ("obligation_id", "obligation.id", "identity.obligation_id"))
    actor_key = actor_id or incarnation_id or (f"return:{return_id}" if return_id else "actor:unknown")

    process_id = _first_identifier(payloads, ("process_id", "process.id", "process_pid", "pid"))
    process_posture = _first_text(payloads, ("process_state", "process.state", "process.status", "runtime_state"))
    session_id = _first_identifier(
        payloads,
        ("session_id", "session.id", "runtime_session_id", "actor.session_id", "active_d3.session_id"),
    )
    session_posture = _first_text(payloads, ("session_state", "session.state", "session.status"))
    terminal_id = _first_identifier(payloads, ("terminal_id", "terminal.id"))
    terminal_posture = _first_text(
        payloads,
        (
            "terminal_state",
            "terminal.state",
            "terminal.status",
            "terminal_wake_state_before_command",
            "wake_terminal_state",
        ),
    )
    exit_code = _first_number(payloads, ("exit_code", "terminal.exit_code"))

    input_tokens, input_found, input_invalid = _first_number(
        payloads,
        ("usage.input_tokens", "usage.prompt_tokens", "usage.tokens.input", "token_usage.input_tokens"),
    )
    output_tokens, output_found, output_invalid = _first_number(
        payloads,
        ("usage.output_tokens", "usage.completion_tokens", "usage.tokens.output", "token_usage.output_tokens"),
    )
    total_tokens, total_found, total_invalid = _first_number(
        payloads,
        ("usage.total_tokens", "usage.tokens.total", "token_usage.total_tokens"),
    )
    tool_calls, tool_calls_found, tool_calls_invalid = _first_number(
        payloads,
        ("usage.tool_calls", "usage.tools", "metrics.tool_calls"),
    )
    duration_seconds, duration_found, duration_invalid = _first_number(
        payloads,
        ("usage.duration_seconds", "usage.duration", "metrics.duration_seconds"),
    )
    usage_observation = _first_text(
        payloads,
        ("usage_observation.status", "return_summary.usage_observation.status"),
    )
    usage_invalid = any(
        (
            input_found and input_invalid,
            output_found and output_invalid,
            total_found and total_invalid,
            tool_calls_found and tool_calls_invalid,
            duration_found and duration_invalid,
        )
    )

    responsibility_state = _first_text(
        payloads,
        ("responsibility_state", "responsibility_state.state", "responsibility.state"),
    )
    responsibility_holder = _first_text(
        payloads,
        ("responsibility_state.holder", "responsibility.holder", "actor.responsibility"),
    )
    return_ref = return_observation.get("ref") if isinstance(return_observation.get("ref"), dict) else None
    wake_ref = wake_observation.get("ref") if isinstance(wake_observation.get("ref"), dict) else None
    filter_ref = master_filter.get("ref") if isinstance(master_filter.get("ref"), dict) else None
    evidence_refs = _unique_refs(return_ref, wake_ref, filter_ref)
    actor_state = envelope.get("state") if envelope.get("state") in {"reentered", "returned", "missing", "deferred", "invalid"} else "unknown"
    payload_state = (
        "invalid"
        if actor_state == "invalid" or any(error != "handoff payload missing" and error != "wake payload missing" for error in payload_errors)
        else ("observed" if payloads else "missing")
    )

    return {
        "actor_key": actor_key,
        "state": actor_state,
        "identity": {
            "state": "observed" if any((actor_id, actor_label, incarnation_id, role_id)) else ("missing" if not payloads else "unknown"),
            "actor_id": actor_id,
            "incarnation_id": incarnation_id,
            "role_id": role_id,
            "label": actor_label or actor_id or incarnation_id or (f"return {return_id}" if return_id else "actor identity unknown"),
            "claim_limit": FIELD_CLAIM_LIMIT,
        },
        "responsibility": {
            "state": "observed" if responsibility_state or responsibility_holder else ("missing" if not payloads else "unknown"),
            "responsibility_state": responsibility_state,
            "holder": responsibility_holder,
            "mandate_id": mandate_id,
            "obligation_id": obligation_id,
            "claim_limit": "Responsibility values are task-local return observations and do not redefine aoa-agents meaning.",
        },
        "process": {
            "state": _group_state(payloads, payload_errors, bool(process_id or process_posture)),
            "process_id": process_id,
            "posture": process_posture,
            "claim_limit": "Process fields are observations only; the dashboard does not assert process health.",
        },
        "session": {
            "state": _group_state(payloads, payload_errors, bool(session_id or session_posture)),
            "session_id": session_id,
            "posture": session_posture,
            "claim_limit": "Session fields identify a task-local observation only; they do not establish transcript freshness or semantic continuation.",
        },
        "terminal": {
            "state": _group_state(payloads, payload_errors, bool(terminal_id or terminal_posture or exit_code[1])),
            "terminal_id": terminal_id,
            "posture": terminal_posture,
            "exit_code": exit_code[0],
            "claim_limit": "Terminal fields are observed metadata and are not a deployment or runtime verdict.",
        },
        "wake_return": {
            "state": "observed" if lifecycle else "unknown",
            "return_state": lifecycle.get("returned", {}).get("state") if isinstance(lifecycle.get("returned"), dict) else None,
            "wake_state": lifecycle.get("wake_requested", {}).get("state") if isinstance(lifecycle.get("wake_requested"), dict) else None,
            "master_filter_state": lifecycle.get("master_filtered", {}).get("state") if isinstance(lifecycle.get("master_filtered"), dict) else None,
            "reentry_state": lifecycle.get("reentered", {}).get("state") if isinstance(lifecycle.get("reentered"), dict) else None,
            "accepted_turn_id": envelope.get("accepted_turn", {}).get("accepted_turn_id") if isinstance(envelope.get("accepted_turn"), dict) else None,
            "filter_disposition": master_filter.get("disposition"),
            "claim_limit": "Wake, return, and re-entry values are bounded transport/correlation observations, not acceptance or semantic continuation.",
        },
        "usage": {
            "state": "invalid" if usage_invalid else _group_state(
                payloads,
                payload_errors,
                any(value is not None for value in (input_tokens, output_tokens, total_tokens, tool_calls, duration_seconds, usage_observation)),
            ),
            "observation_status": usage_observation,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "tool_calls": tool_calls,
            "duration_seconds": duration_seconds,
            "claim_limit": "Usage is displayed only when an allowlisted scalar observation is present; absence is not zero and does not establish billing, quality, or completion.",
        },
        "payload_state": payload_state,
        "payload_errors": payload_errors,
        "evidence_refs": evidence_refs,
        "claim_limit": ACTIVITY_CLAIM_LIMIT,
    }


def _empty_activity(
    *,
    state: str,
    refs: list[dict[str, Any]],
    degradation: list[str],
    observation: str,
) -> dict[str, Any]:
    return {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "state": state,
        "actors": [],
        "summary": {
            "actor_count": None,
            "envelopes": None,
            "with_identity": None,
            "with_process": None,
            "with_session": None,
            "with_terminal": None,
            "with_usage": None,
        },
        "observed_at": None,
        "freshness": state,
        "degradation": degradation,
        "observation": observation,
        "evidence_refs": refs,
        "claim_limit": ACTIVITY_CLAIM_LIMIT,
    }


def observe_actor_activity(config: dict[str, Any], correlation: dict[str, Any]) -> dict[str, Any]:
    current = config.get("current_correlation")
    correlation_refs = correlation.get("evidence_refs", []) if isinstance(correlation, dict) else []
    if not isinstance(current, dict) or not isinstance(current.get("task_local_dir"), str):
        activity = _empty_activity(
            state="invalid",
            refs=correlation_refs,
            degradation=["current_correlation_config_incomplete"],
            observation="Actor activity cannot bind because the current task-local directory is not configured.",
        )
        return _as_source(activity)

    metadata = correlation.get("metadata") if isinstance(correlation.get("metadata"), dict) else {}
    envelopes = metadata.get("envelopes")
    correlation_state = correlation.get("state")
    if not isinstance(envelopes, list):
        activity = _empty_activity(
            state="invalid" if correlation_state == "invalid" else "missing",
            refs=correlation_refs,
            degradation=["correlation_envelopes_missing"],
            observation="No admitted task-local actor envelope is available; actor count remains unknown.",
        )
        return _as_source(activity)
    if not envelopes:
        activity = _empty_activity(
            state="missing" if correlation_state in {"missing", None} else "deferred",
            refs=correlation_refs,
            degradation=["actor_envelopes_empty"],
            observation="The task-local correlation surface has no actor envelopes; actor count remains unknown.",
        )
        return _as_source(activity)

    task_root = Path(current["task_local_dir"]).resolve(strict=False)
    actors: list[dict[str, Any]] = []
    degradation: list[str] = []
    for envelope in envelopes:
        if not isinstance(envelope, dict):
            degradation.append("actor_envelope_not_object")
            continue
        return_observation = envelope.get("return_observation") if isinstance(envelope.get("return_observation"), dict) else {}
        wake_observation = envelope.get("wake_observation") if isinstance(envelope.get("wake_observation"), dict) else {}
        return_ref = return_observation.get("ref") if isinstance(return_observation.get("ref"), dict) else None
        wake_ref = wake_observation.get("ref") if isinstance(wake_observation.get("ref"), dict) else None
        handoff, _, handoff_error = _read_payload(task_root, return_ref)
        wake, _, wake_error = _read_payload(task_root, wake_ref)
        payloads = [payload for payload in (handoff, wake) if payload is not None]
        payload_errors = [error for error in (handoff_error, wake_error) if error and error != "payload is missing"]
        if handoff_error == "payload is missing":
            payload_errors.append("handoff payload missing")
        if wake_error == "payload is missing":
            payload_errors.append("wake payload missing")
        if payload_errors:
            degradation.append("actor_payload_evidence_degraded")
        actors.append(_build_actor(envelope, payloads, payload_errors))

    if not actors:
        activity = _empty_activity(
            state="invalid",
            refs=correlation_refs,
            degradation=[*degradation, "no_object_actor_envelopes"],
            observation="Task-local activity evidence did not contain usable actor envelopes.",
        )
        return _as_source(activity)

    group_names = ("identity", "responsibility", "process", "session", "terminal", "usage")
    has_invalid = correlation_state == "invalid" or any(
        actor["state"] == "invalid" or any(actor[name]["state"] == "invalid" for name in group_names) for actor in actors
    )
    has_degraded = correlation_state in {"deferred", "missing"} or any(
        actor[name]["state"] in {"missing", "unknown"} for actor in actors for name in group_names
    )
    state = "invalid" if has_invalid else ("deferred" if has_degraded else "bound")
    summary = {
        "actor_count": len(actors),
        "envelopes": len(envelopes),
        "with_identity": sum(actor["identity"]["state"] == "observed" for actor in actors),
        "with_process": sum(actor["process"]["state"] == "observed" for actor in actors),
        "with_session": sum(actor["session"]["state"] == "observed" for actor in actors),
        "with_terminal": sum(actor["terminal"]["state"] == "observed" for actor in actors),
        "with_usage": sum(actor["usage"]["state"] == "observed" for actor in actors),
    }
    activity = {
        "schema_version": ACTIVITY_SCHEMA_VERSION,
        "state": state,
        "actors": actors,
        "summary": summary,
        "observed_at": metadata.get("observed_at"),
        "freshness": "current_at_read" if state == "bound" else state,
        "degradation": sorted(set(degradation)),
        "observation": (
            f"Observed {len(actors)} task-local actor envelope(s); process, session, terminal, wake/return, usage, and unknown fields remain separate."
            if state == "bound"
            else f"Observed {len(actors)} task-local actor envelope(s) with bounded missing, unknown, deferred, or invalid activity fields."
        ),
        "evidence_refs": correlation_refs,
        "claim_limit": ACTIVITY_CLAIM_LIMIT,
    }
    return _as_source(activity)


def _as_source(activity: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": "task-local-actor-activity",
        "owner": "aoa-dashboard",
        "state": activity["state"],
        "freshness": activity["freshness"],
        "degradation": activity["degradation"],
        "observation": activity["observation"],
        "metadata": activity,
        "evidence_refs": activity["evidence_refs"],
        "claim_limit": activity["claim_limit"],
    }
