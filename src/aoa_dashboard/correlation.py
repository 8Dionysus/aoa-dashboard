from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Literal, TypedDict

from .source_binding import FileSnapshot, read_file_snapshot, snapshot_ref


CORRELATION_SCHEMA_VERSION = "aoa_dashboard_correlation_envelope_v1"
CORRELATION_PROJECTION_VERSION = "aoa_dashboard_correlation_projection_v1"
WAKE_RECEIPT_SCHEMA_VERSION = "task_local_actor_wake_receipt_v2"
DELIVERY_OUTCOMES = frozenset({"handoff_delivered_pending_master_filter"})
SHA256_LENGTH = 64


CorrelationState = Literal["reentered", "returned", "missing", "deferred", "invalid"]


class CorrelationRef(TypedDict):
    label: str
    kind: str
    ref: str
    sha256: str | None
    observed_at: str | None
    currentness: str
    freshness: str
    degradation: list[str]
    owner: str
    access_scope: str
    authority: str
    claim_policy: str
    expected_sha256: str | None
    snapshot_role: str
    claim_limit: str
    missing_fields: list[str]


class CorrelationLifecycleItem(TypedDict):
    state: str
    observation: str
    evidence_refs: list[CorrelationRef]
    claim_limit: str


class CorrelationEnvelope(TypedDict):
    schema_version: str
    correlation_id: str
    state: CorrelationState
    goal: dict[str, Any]
    return_observation: dict[str, Any]
    wake_observation: dict[str, Any]
    accepted_turn: dict[str, Any]
    master_filter: dict[str, Any]
    dag_disposition: dict[str, Any]
    lifecycle: dict[str, CorrelationLifecycleItem]
    authority: str
    claim_limits: list[str]


class CorrelationProjection(TypedDict):
    schema_version: str
    state: str
    master_thread_id: str
    current_holder: dict[str, Any]
    master_filter: dict[str, Any]
    envelopes: list[CorrelationEnvelope]
    new_obligations: list[dict[str, Any]]
    rejected_or_deferred_claims: list[str]
    summary: dict[str, Any]
    observed_at: str | None
    freshness: str
    degradation: list[str]
    authority: str
    claim_limit: str


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _ref(
    label: str,
    kind: str,
    path: Path | str,
    *,
    digest: str | None = None,
    observed_at: str | None = None,
    freshness: str = "unknown",
    currentness: str | None = None,
    degradation: list[str] | None = None,
    owner: str = "aoa-dashboard",
    access_scope: str = "dashboard_local",
    authority: str = "aoa-dashboard:derived",
    claim_policy: str = "dashboard_derived_read_model",
    expected_sha256: str | None = None,
    snapshot_role: str = "derived_binding",
    missing_fields: list[str] | None = None,
    claim_limit: str,
) -> CorrelationRef:
    result: dict[str, Any] = {
        "label": label,
        "kind": kind,
        "ref": str(path),
        "sha256": digest,
        "observed_at": observed_at,
        "currentness": currentness or freshness,
        "freshness": freshness,
        "degradation": list(degradation or []),
        "owner": owner,
        "access_scope": access_scope,
        "authority": authority,
        "claim_policy": claim_policy,
        "claim_limit": claim_limit,
        "snapshot_role": snapshot_role,
    }
    if expected_sha256 is not None:
        result["expected_sha256"] = expected_sha256
    if missing_fields:
        result["missing_fields"] = list(missing_fields)
    return result  # type: ignore[return-value]


def _direct_child(root: Path, value: Any) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, "reference is missing"
    candidate = Path(value)
    if not candidate.is_absolute():
        return None, "reference is not absolute"
    resolved_root = root.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if resolved.parent != resolved_root:
        return None, "reference is outside the bounded task-local directory"
    if str(resolved) != value:
        return None, "reference is not the exact canonical path"
    return resolved, None


def _base_claim_limit() -> str:
    return (
        "This envelope is a dashboard-owned correlation of task-local metadata. "
        "It does not establish actor meaning, runtime health, owner acceptance, proof, "
        "semantic continuation, or human acceptance."
    )


_LEGACY_OBLIGATION_CLAIM_LIMIT = (
    "Legacy obligation text remains source-owned. The dashboard exposes only a digest-linked redaction "
    "until an allowed owner scope supplies a structured pressure record."
)


def _redacted_obligation(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) and "redacted" in value and "claim_limit" in value:
        digest = value.get("sha256")
        return {
            "sha256": digest if _is_sha256(digest) else None,
            "redacted": f"[redacted legacy obligation; sha256={digest}]" if _is_sha256(digest) else "[redacted legacy obligation; digest unavailable]",
            "claim_limit": _LEGACY_OBLIGATION_CLAIM_LIMIT,
        }
    if not isinstance(value, str):
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return {
        "sha256": digest,
        "redacted": f"[redacted legacy obligation; sha256={digest}]",
        "claim_limit": _LEGACY_OBLIGATION_CLAIM_LIMIT,
    }


def _redacted_obligations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for raw in value if (item := _redacted_obligation(raw)) is not None]


def _file_ref(
    label: str,
    kind: str,
    snapshot: FileSnapshot,
    *,
    observed_at: str | None,
    owner: str,
    access_scope: str,
    authority: str,
    claim_policy: str,
    claim_limit: str,
) -> CorrelationRef:
    return snapshot_ref(
        snapshot,
        label=label,
        kind=kind,
        owner=owner,
        access_scope=access_scope,
        authority=authority,
        claim_policy=claim_policy,
        claim_limit=claim_limit,
        observed_at=observed_at,
    )  # type: ignore[return-value]


def _missing_ref(label: str, kind: str, path: Path | str, claim_limit: str) -> CorrelationRef:
    return _ref(
        label,
        kind,
        path,
        digest=None,
        observed_at=None,
        currentness="missing",
        freshness="missing",
        degradation=["source_missing"],
        owner="aoa-dashboard",
        access_scope="dashboard_local",
        authority="aoa-dashboard:derived",
        claim_policy="dashboard_derived_read_model",
        snapshot_role="missing_binding",
        claim_limit=claim_limit,
    )


def _empty_lifecycle(
    state: str,
    observation: str,
    refs: list[CorrelationRef],
    claim_limit: str,
) -> CorrelationLifecycleItem:
    return {
        "state": state,
        "observation": observation,
        "evidence_refs": refs,
        "claim_limit": claim_limit,
    }


def _validate_filter(
    value: dict[str, Any],
    *,
    expected_thread: str,
    expected_goal_ref: str,
) -> tuple[list[str], dict[str, dict[str, Any]], list[dict[str, str]]]:
    errors: list[str] = []
    entries: dict[str, dict[str, Any]] = {}
    dag: list[dict[str, str]] = []
    if value.get("schema_version") != "aoa_dashboard_master_return_disposition_v1":
        errors.append("master filter schema_version is not supported")
    if value.get("master_thread_id") != expected_thread:
        errors.append("master filter master_thread_id mismatch")
    if value.get("goal_ref") != expected_goal_ref:
        errors.append("master filter goal_ref mismatch")
    if not _non_empty_string(value.get("reviewed_at")):
        errors.append("master filter reviewed_at is missing")

    raw_returns = value.get("returns")
    if not isinstance(raw_returns, list):
        errors.append("master filter returns is not a list")
    else:
        seen_ids: set[str] = set()
        seen_refs: set[str] = set()
        for index, item in enumerate(raw_returns):
            if not isinstance(item, dict):
                errors.append(f"master filter return {index} is not an object")
                continue
            return_id = item.get("id")
            handoff_ref = item.get("handoff_ref")
            wake_ref = item.get("wake_receipt_ref")
            if not _non_empty_string(return_id):
                errors.append(f"master filter return {index} has no id")
            elif return_id in seen_ids:
                errors.append(f"master filter duplicate return id: {return_id}")
            else:
                seen_ids.add(return_id)
            if not _non_empty_string(handoff_ref):
                errors.append(f"master filter return {index} has no handoff_ref")
            elif handoff_ref in seen_refs:
                errors.append(f"master filter duplicate handoff_ref: {handoff_ref}")
            else:
                seen_refs.add(handoff_ref)
            if not _is_sha256(item.get("handoff_sha256")):
                errors.append(f"master filter return {index} has invalid handoff_sha256")
            if not _non_empty_string(wake_ref):
                errors.append(f"master filter return {index} has no wake_receipt_ref")
            if not _non_empty_string(item.get("disposition")):
                errors.append(f"master filter return {index} has no disposition")
            if _non_empty_string(return_id) and _non_empty_string(handoff_ref) and handoff_ref not in entries:
                entries[handoff_ref] = item

    raw_dag = value.get("goal_dag")
    if not isinstance(raw_dag, list):
        errors.append("master filter goal_dag is not a list")
    else:
        seen_dag: set[str] = set()
        for index, item in enumerate(raw_dag):
            if not isinstance(item, dict):
                errors.append(f"master filter goal_dag item {index} is not an object")
                continue
            node_id = item.get("id")
            node_state = item.get("state")
            next_step = item.get("next")
            if not all(_non_empty_string(value) for value in (node_id, node_state, next_step)):
                errors.append(f"master filter goal_dag item {index} is incomplete")
                continue
            if node_id in seen_dag:
                errors.append(f"master filter duplicate goal_dag id: {node_id}")
                continue
            seen_dag.add(node_id)
            dag.append({"id": node_id, "state": node_state, "next": next_step})
    return errors, entries, dag


def _validate_wake(
    wake: dict[str, Any],
    *,
    expected_thread: str,
    expected_handoff_ref: str,
    expected_handoff_digest: str | None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    observed = wake.get("observed") if isinstance(wake.get("observed"), dict) else {}
    actions = wake.get("actions") if isinstance(wake.get("actions"), dict) else {}
    if wake.get("schema_version") != WAKE_RECEIPT_SCHEMA_VERSION:
        errors.append("wake receipt is not task_local_actor_wake_receipt_v2")
    if wake.get("thread_id") != expected_thread:
        errors.append("wake receipt thread_id mismatch")
    if wake.get("handoff_ref") != expected_handoff_ref:
        errors.append("wake receipt handoff_ref mismatch")
    if wake.get("handoff_sha256") != expected_handoff_digest:
        errors.append("wake receipt handoff_sha256 mismatch")
    if wake.get("outcome") not in DELIVERY_OUTCOMES:
        errors.append("wake receipt delivery outcome is not admitted")
    if observed.get("handoff_delivery") is not True:
        errors.append("wake receipt observed.handoff_delivery is not true")
    if actions.get("handoff_message_submitted") is not True:
        errors.append("wake receipt actions.handoff_message_submitted is not true")
    if not _non_empty_string(observed.get("accepted_turn_id")):
        errors.append("wake receipt accepted_turn_id is missing")
    if not _non_empty_string(wake.get("attempted_at")) and not _non_empty_string(wake.get("generated_at")):
        errors.append("wake receipt observed_at is missing")
    delivery = {
        "schema_version": wake.get("schema_version"),
        "outcome": wake.get("outcome"),
        "delivery_route": observed.get("delivery_route"),
        "handoff_delivery": observed.get("handoff_delivery") is True,
        "handoff_message_submitted": actions.get("handoff_message_submitted") is True,
        "accepted_turn_id": observed.get("accepted_turn_id"),
        "goal_resume_requested": actions.get("goal_resume_requested") is True,
        "observed_at": wake.get("attempted_at") or wake.get("generated_at"),
    }
    return errors, delivery


def _master_filter_summary(
    value: dict[str, Any],
    filter_ref: CorrelationRef,
    dag: list[dict[str, str]],
    entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    claim_limit = (
        "The master filter is task-local disposition evidence. It is not proof, owner acceptance, "
        "or permission to execute a runtime action."
    )
    return {
        "schema_version": value.get("schema_version"),
        "ref": copy.deepcopy(filter_ref),
        "reviewed_at": value.get("reviewed_at"),
        "return_ids": [item.get("id") for item in entries.values() if _non_empty_string(item.get("id"))],
        "goal_ref": value.get("goal_ref"),
        "goal_dag": dag,
        "new_required_obligations": _redacted_obligations(value.get("new_required_obligations", [])),
        "rejected_or_deferred_claims": [
            item for item in value.get("rejected_or_deferred_claims", []) if isinstance(item, str)
        ],
        "claim_limit": claim_limit,
    }


def _envelope(
    *,
    expected_thread: str,
    goal_id: str,
    goal_anchor_ref: CorrelationRef,
    filter_summary: dict[str, Any],
    filter_entry: dict[str, Any],
    handoff_path: Path | None,
    handoff_snapshot: FileSnapshot | None,
    handoff: dict[str, Any] | None,
    handoff_error: str | None,
    wake_path: Path | None,
    wake_snapshot: FileSnapshot | None,
    wake: dict[str, Any] | None,
    wake_error: str | None,
    filter_currentness: str,
    goal_currentness: str,
) -> CorrelationEnvelope:
    claim_limit = _base_claim_limit()
    expected_handoff_ref = filter_entry.get("handoff_ref")
    expected_handoff_digest = filter_entry.get("handoff_sha256")
    handoff_ref = (
        _file_ref(
            "Luna handoff",
            "task_local_handoff",
            handoff_snapshot,
            observed_at=handoff_snapshot.observed_at,
            owner="aoa-agents",
            access_scope="owner_bounded",
            authority="source_owner",
            claim_policy="actor_return_metadata",
            claim_limit="The handoff is a task-local return artifact; its contents do not become owner truth.",
        )
        if handoff_snapshot is not None
        else _missing_ref(
            "Luna handoff",
            "task_local_handoff",
            expected_handoff_ref or "unresolved:handoff",
            "The handoff ref is listed by the master filter but the file is absent or unreadable.",
        )
    )
    wake_ref = (
        _file_ref(
            "wake receipt",
            "task_local_wake_receipt",
            wake_snapshot,
            observed_at=wake_snapshot.observed_at,
            owner="aoa-agents",
            access_scope="owner_bounded",
            authority="source_owner",
            claim_policy="actor_return_metadata",
            claim_limit="Wake delivery is transport evidence only; it does not prove acceptance or semantic continuation.",
        )
        if wake_snapshot is not None
        else _missing_ref(
            "wake receipt",
            "task_local_wake_receipt",
            filter_entry.get("wake_receipt_ref") or "unresolved:wake-receipt",
            "The master filter names a wake receipt that is absent or unreadable.",
        )
    )
    errors: list[str] = []
    handoff_missing = handoff is None and handoff_error == "handoff file is absent from the bounded directory"
    if handoff_error and not handoff_missing:
        errors.append(f"handoff: {handoff_error}")
    if handoff is None:
        if not handoff_missing:
            errors.append("handoff payload is missing")
    else:
        if handoff.get("master_thread_id") != expected_thread:
            errors.append("handoff master_thread_id mismatch")
        actual_digest = handoff_snapshot.digest if handoff_snapshot else None
        if actual_digest != expected_handoff_digest:
            errors.append("handoff SHA-256 does not match master filter")
    wake_missing = wake is None and wake_error == "wake receipt is absent from the bounded directory"
    if wake_error and not wake_missing:
        errors.append(f"wake receipt: {wake_error}")

    delivery: dict[str, Any] = {
        "schema_version": None,
        "outcome": None,
        "delivery_route": None,
        "handoff_delivery": False,
        "handoff_message_submitted": False,
        "accepted_turn_id": None,
        "goal_resume_requested": False,
        "observed_at": None,
    }
    if wake is None:
        if not wake_missing:
            errors.append("wake receipt payload is missing")
    else:
        wake_errors, delivery = _validate_wake(
            wake,
            expected_thread=expected_thread,
            expected_handoff_ref=str(expected_handoff_ref),
            expected_handoff_digest=expected_handoff_digest,
        )
        errors.extend(wake_errors)
        if wake_snapshot is not None and wake_ref["sha256"] is None:
            errors.append("wake receipt digest is unavailable")
        if wake_snapshot is not None and str(wake_snapshot.path) != str(filter_entry.get("wake_receipt_ref")):
            errors.append("wake receipt path does not match master filter wake_receipt_ref")

    return_state: str = "returned"
    wake_state = "wake requested"
    master_state = "reentered"
    reentry_state: str = "reentered"
    is_filtered = filter_entry.get("disposition") != "not_listed_by_master_filter"
    if handoff_missing or wake_missing:
        return_state = "missing"
    if handoff is None and not handoff_missing:
        return_state = "missing"
    if errors:
        return_state = "invalid"
        wake_state = "invalid"
        master_state = "invalid"
        reentry_state = "invalid"
    elif handoff_missing:
        wake_state = "missing"
        master_state = "missing"
        reentry_state = "missing"
    elif wake_missing:
        return_state = "returned"
        wake_state = "missing"
        master_state = "deferred"
        reentry_state = "missing"
    elif not is_filtered:
        return_state = "deferred"
        master_state = "deferred"
        reentry_state = "missing"

    # A configured digest is an attestation boundary, not a label that can be
    # carried forward after the bytes changed.  Keep the parsed evidence
    # visible, but withhold a re-entry claim when either source snapshot is not
    # attested current at this read.
    if not errors and (filter_currentness != "current_at_read" or goal_currentness != "current_at_read"):
        if filter_currentness in {"invalid", "missing"} or goal_currentness in {"invalid", "missing"}:
            return_state = "missing" if "missing" in {filter_currentness, goal_currentness} else "invalid"
            wake_state = "deferred"
            master_state = "deferred"
            reentry_state = "missing"
        else:
            master_state = "deferred"
            reentry_state = "deferred"
            if return_state == "returned":
                return_state = "deferred"

    handoff_metadata = {
        "return_id": filter_entry.get("id") or (handoff_snapshot.path.stem if handoff_snapshot else None),
        "source_schema_version": handoff.get("schema_version") if handoff else None,
        "responsibility_state": handoff.get("responsibility_state") if handoff else None,
        "master_thread_id": handoff.get("master_thread_id") if handoff else None,
        "ref": handoff_ref,
        "filter_disposition": filter_entry.get("disposition"),
        "errors": errors,
        "claim_limit": "Return metadata is retained for correlation only; it is not a domain verdict.",
    }
    wake_metadata = {
        "ref": wake_ref,
        "schema_version": delivery["schema_version"],
        "outcome": delivery["outcome"],
        "delivery_route": delivery["delivery_route"],
        "handoff_delivery": delivery["handoff_delivery"],
        "handoff_message_submitted": delivery["handoff_message_submitted"],
        "observed_at": delivery["observed_at"],
        "claim_limit": "Delivery is not proof, acceptance, or semantic continuation.",
    }
    accepted_turn = {
        "accepted_turn_id": delivery["accepted_turn_id"],
        "state": "transport_accepted" if delivery["accepted_turn_id"] and not errors else "missing",
        "basis_ref": wake_ref,
        "observed_at": delivery["observed_at"],
        "claim_limit": "accepted_turn_id identifies transport admission of a turn only; it does not prove the parent resumed semantically.",
    }
    filter_entry_view = {
        "return_id": filter_entry.get("id"),
        "disposition": filter_entry.get("disposition"),
        "handoff_sha256": filter_entry.get("handoff_sha256"),
        "wake_receipt_ref": filter_entry.get("wake_receipt_ref"),
        "ref": filter_summary["ref"],
        "reviewed_at": filter_summary["reviewed_at"],
        "claim_limit": filter_summary["claim_limit"],
    }
    dag_view = {
        "ref": filter_summary["ref"],
        "nodes": filter_summary["goal_dag"],
        "relevant_node_ids": ["D2", "D3", "D4", "D5", "D8"],
        "claim_limit": "DAG disposition is the master's task-local filter evidence, not dashboard owner acceptance.",
    }
    lifecycle_claim = "Lifecycle correlation remains weaker than owner events, proof, acceptance, and semantic continuation."
    lifecycle = {
        "returned": _empty_lifecycle(
            return_state,
            "The handoff is listed by the master filter and its thread/hash checks are retained." if return_state == "returned" else "The return cannot be treated as valid.",
            [handoff_ref, filter_summary["ref"]],
            lifecycle_claim,
        ),
        "wake_requested": _empty_lifecycle(
            wake_state,
            "Wake delivery is observed from the validated v2 receipt." if wake_state == "wake requested" else "No validated wake delivery is available.",
            [wake_ref],
            "Wake delivery is not proof, acceptance, or semantic continuation.",
        ),
        "master_filtered": _empty_lifecycle(
            master_state,
            "The exact handoff ref and digest are present in the master filter." if master_state == "reentered" else "The master filter does not yield a valid filtered disposition.",
            [filter_summary["ref"], handoff_ref],
            "The filter is task-local disposition evidence, not owner acceptance.",
        ),
        "reentered": _empty_lifecycle(
            reentry_state,
            "Bounded re-entry correlation exists from exact accepted_turn_id plus the master filter." if reentry_state == "reentered" else "Re-entry is withheld without exact accepted_turn_id plus a valid master filter.",
            [wake_ref, filter_summary["ref"]],
            "This is a bounded re-entry correlation only; it does not prove semantic continuation or parent runtime health.",
        ),
    }
    claim_limits = [
        claim_limit,
        "Wake delivery is transport evidence only; it does not prove owner acceptance or semantic continuation.",
        "Reentered is emitted only when exact accepted_turn_id and the master filter correlate; it is not a runtime event.",
    ]
    if errors:
        claim_limits.append("Invalid or mismatched task-local evidence remains invalid and is not converted to success or zero.")
    elif wake is None:
        claim_limits.append("Missing wake evidence remains missing; a returned handoff is not promoted to re-entry.")
    envelope_state: CorrelationState = reentry_state  # type: ignore[assignment]
    if not errors and not is_filtered:
        envelope_state = "deferred"
    return {
        "schema_version": CORRELATION_SCHEMA_VERSION,
        "correlation_id": f"goal:{goal_id}/thread:{expected_thread}/return:{filter_entry.get('id') or 'unresolved'}",
        "state": envelope_state,
        "goal": {
            "goal_id": goal_id,
            "master_thread_id": expected_thread,
            "anchor_ref": goal_anchor_ref,
            "claim_limit": "Goal and thread identity are bindings for this derived view; dashboard does not own Goal semantics.",
        },
        "return_observation": handoff_metadata,
        "wake_observation": wake_metadata,
        "accepted_turn": accepted_turn,
        "master_filter": filter_entry_view,
        "dag_disposition": dag_view,
        "lifecycle": lifecycle,
        "authority": "aoa-dashboard:derived_task_local_correlation",
        "claim_limits": claim_limits,
    }


def _source(
    *,
    state: str,
    freshness: str,
    observation: str,
    metadata: dict[str, Any],
    refs: list[CorrelationRef],
    degradation: list[str],
    claim_limit: str,
) -> dict[str, Any]:
    return {
        "id": "task-local-correlation",
        "owner": "aoa-dashboard",
        "state": state,
        "freshness": freshness,
        "degradation": degradation,
        "observation": observation,
        "metadata": metadata,
        "evidence_refs": refs,
        "claim_limit": claim_limit,
    }


def observe_current_correlation(
    config: dict[str, Any],
    *,
    goal_anchor_snapshot: FileSnapshot | None = None,
) -> dict[str, Any]:
    current = config.get("current_correlation")
    if not isinstance(current, dict):
        return _source(
            state="invalid",
            freshness="invalid",
            observation="Current correlation config is missing or not an object.",
            metadata={"schema_version": CORRELATION_PROJECTION_VERSION, "envelopes": []},
            refs=[],
            degradation=["current_correlation_config_invalid"],
            claim_limit=_base_claim_limit(),
        )
    expected_thread = current.get("master_thread_id")
    task_root_value = current.get("task_local_dir")
    filter_path_value = current.get("master_filter_path")
    goal_id = config.get("goal_id")
    goal_anchor_path = config.get("goal_anchor_path")
    if not all(_non_empty_string(value) for value in (expected_thread, task_root_value, filter_path_value, goal_id, goal_anchor_path)):
        return _source(
            state="invalid",
            freshness="invalid",
            observation="Current correlation config lacks a complete Goal/thread/task-local binding.",
            metadata={"schema_version": CORRELATION_PROJECTION_VERSION, "envelopes": []},
            refs=[],
            degradation=["current_correlation_config_incomplete"],
            claim_limit=_base_claim_limit(),
        )
    task_root = Path(task_root_value).resolve(strict=False)
    filter_path = Path(filter_path_value).resolve(strict=False)
    goal_anchor_path_obj = Path(goal_anchor_path).resolve(strict=False)
    holder_label = current.get("current_holder") if _non_empty_string(current.get("current_holder")) else "current task-local holder"
    holder = {
        "label": holder_label,
        "scope": "current_task_local_correlation",
        "master_thread_id": expected_thread,
        "bootstrap_binding": "historical_only",
        "claim_limit": "Current holder label is a task-local correlation binding, not role or runtime authority.",
    }
    goal_anchor_snapshot = goal_anchor_snapshot or read_file_snapshot(
        goal_anchor_path_obj,
        expected_digest=config.get("goal_anchor_expected_sha256"),
        parser="text",
    )
    filter_snapshot = read_file_snapshot(
        filter_path,
        expected_digest=current.get("master_filter_expected_sha256"),
        parser="json",
    )
    anchor_digest = goal_anchor_snapshot.digest
    goal_anchor_ref = _file_ref(
        "Goal Anchor",
        "goal_anchor",
        goal_anchor_snapshot,
        observed_at=goal_anchor_snapshot.observed_at,
        owner="goal-anchor",
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="source_owner_metadata",
        claim_limit="Goal Anchor ref and digest bind this projection; they do not prove execution, review, or acceptance.",
    )
    directory_ref = _ref(
        "task-local correlation directory",
        "task_local_directory",
        task_root,
        digest=None,
        observed_at=_utc_now() if task_root.exists() else None,
        currentness="current_at_read" if task_root.is_dir() else "missing",
        freshness="current_at_read" if task_root.is_dir() else "missing",
        owner="task-local-runtime",
        access_scope="owner_bounded",
        authority="source_owner",
        claim_policy="runtime_binding",
        snapshot_role="directory_binding",
        degradation=[] if task_root.is_dir() else ["source_missing"],
        claim_limit="Directory presence is a binding observation, not runtime health or acceptance.",
    )
    filter_ref = _file_ref(
        "master return filter",
        "task_local_master_filter",
        filter_snapshot,
        observed_at=filter_snapshot.observed_at,
        owner="master-thread",
        access_scope="owner_bounded",
        authority="master_decision",
        claim_policy="master_decision_disposition",
        claim_limit="The master filter is task-local disposition evidence, not proof or owner acceptance.",
    )
    base_refs = [goal_anchor_ref, directory_ref, filter_ref]
    claim_limit = _base_claim_limit()
    if not task_root.exists():
        return _source(
            state="missing",
            freshness="missing",
            observation="Current task-local correlation directory is absent.",
            metadata={
                "schema_version": CORRELATION_PROJECTION_VERSION,
                "master_thread_id": expected_thread,
                "current_holder": holder,
                "master_filter": {"ref": filter_ref, "state": "missing", "claim_limit": claim_limit},
                "envelopes": [],
                "new_obligations": [],
                "rejected_or_deferred_claims": [],
                "summary": {"handoff_files": None, "wake_files": None, "envelopes": None},
                "observed_at": None,
                "freshness": "missing",
                "degradation": ["task_local_directory_missing"],
                "authority": "aoa-dashboard:derived_task_local_correlation",
                "claim_limit": claim_limit,
            },
            refs=base_refs,
            degradation=["task_local_directory_missing"],
            claim_limit=claim_limit,
        )
    if not task_root.is_dir():
        return _source(
            state="invalid",
            freshness="invalid",
            observation="Current task-local correlation binding is not a directory.",
            metadata={"schema_version": CORRELATION_PROJECTION_VERSION, "master_thread_id": expected_thread, "envelopes": []},
            refs=base_refs,
            degradation=["task_local_binding_not_directory"],
            claim_limit=claim_limit,
        )
    filter_value = filter_snapshot.parsed
    filter_error = filter_snapshot.parse_error or filter_snapshot.read_error
    if filter_error or filter_value is None:
        return _source(
            state="missing" if filter_snapshot.currentness == "missing" else "invalid",
            freshness="missing" if filter_snapshot.currentness == "missing" else "invalid",
            observation="Master filter is absent." if filter_snapshot.currentness == "missing" else f"Master filter is unreadable: {filter_error}",
            metadata={
                "schema_version": CORRELATION_PROJECTION_VERSION,
                "master_thread_id": expected_thread,
                "current_holder": holder,
                "master_filter": {"ref": filter_ref, "state": "missing" if filter_snapshot.currentness == "missing" else "invalid", "claim_limit": claim_limit},
                "envelopes": [],
                "new_obligations": [],
                "rejected_or_deferred_claims": [],
                "summary": {"handoff_files": None, "wake_files": None, "envelopes": None},
                "observed_at": None,
                "freshness": "missing" if filter_snapshot.currentness == "missing" else "invalid",
                "degradation": ["master_filter_missing" if filter_snapshot.currentness == "missing" else "master_filter_unreadable"],
                "authority": "aoa-dashboard:derived_task_local_correlation",
                "claim_limit": claim_limit,
            },
            refs=base_refs,
            degradation=["master_filter_missing" if filter_snapshot.currentness == "missing" else "master_filter_unreadable"],
            claim_limit=claim_limit,
        )

    filter_errors, filter_entries, dag = _validate_filter(
        filter_value,
        expected_thread=expected_thread,
        expected_goal_ref=str(Path(goal_anchor_path).resolve(strict=False)),
    )
    for handoff_ref, entry in filter_entries.items():
        _, handoff_ref_error = _direct_child(task_root, handoff_ref)
        if handoff_ref_error:
            filter_errors.append(f"master filter handoff_ref is not exact/bounded: {handoff_ref_error}")
        _, wake_ref_error = _direct_child(task_root, entry.get("wake_receipt_ref"))
        if wake_ref_error:
            filter_errors.append(f"master filter wake_receipt_ref is not exact/bounded: {wake_ref_error}")
    filter_summary = _master_filter_summary(filter_value, filter_ref, dag, filter_entries)
    handoff_glob = current.get("handoff_glob", "*-luna-handoff.json")
    wake_glob = current.get("wake_glob", "*.wake-receipt.json")
    ignored_names = set(current.get("ignored_handoff_names", [])) if isinstance(current.get("ignored_handoff_names", []), list) else set()
    ignored_wake_names = set(current.get("ignored_wake_names", [])) if isinstance(current.get("ignored_wake_names", []), list) else set()
    handoff_paths = sorted(
        (path.resolve(strict=False) for path in task_root.glob(handoff_glob) if path.is_file() and path.name not in ignored_names),
        key=str,
    )
    wake_paths = sorted(
        (path.resolve(strict=False) for path in task_root.glob(wake_glob) if path.is_file() and path.name not in ignored_wake_names),
        key=str,
    )
    handoffs: dict[str, tuple[Path, FileSnapshot, dict[str, Any] | None, str | None]] = {}
    for path in handoff_paths:
        snapshot = read_file_snapshot(path, parser="json")
        value = snapshot.parsed if isinstance(snapshot.parsed, dict) else None
        error = "handoff file is absent from the bounded directory" if snapshot.currentness == "missing" else (snapshot.parse_error or snapshot.read_error)
        handoffs[str(path)] = (path, snapshot, value, error)
    wakes: dict[str, list[tuple[Path, FileSnapshot, dict[str, Any] | None, str | None]]] = {}
    anomalies: list[str] = []
    for path in wake_paths:
        snapshot = read_file_snapshot(path, parser="json")
        value = snapshot.parsed if isinstance(snapshot.parsed, dict) else None
        error = "wake receipt is absent from the bounded directory" if snapshot.currentness == "missing" else (snapshot.parse_error or snapshot.read_error)
        handoff_ref_value = value.get("handoff_ref") if value else None
        handoff_ref_path, ref_error = _direct_child(task_root, handoff_ref_value)
        if ref_error:
            anomalies.append(f"wake {path.name}: {ref_error}")
            continue
        assert handoff_ref_path is not None
        wakes.setdefault(str(handoff_ref_path), []).append((path, snapshot, value, error))
    envelopes: list[CorrelationEnvelope] = []
    for handoff_ref, entry in filter_entries.items():
        handoff_item = handoffs.get(handoff_ref)
        if handoff_item is None:
            handoff_path = Path(handoff_ref)
            handoff_snapshot = read_file_snapshot(handoff_path, parser="json")
            handoff_value = handoff_snapshot.parsed if isinstance(handoff_snapshot.parsed, dict) else None
            handoff_error = handoff_snapshot.parse_error or handoff_snapshot.read_error
            if handoff_snapshot.currentness == "missing":
                handoff_error = "handoff file is absent from the bounded directory"
        else:
            handoff_path, handoff_snapshot, handoff_value, handoff_error = handoff_item
        wake_candidates = wakes.get(handoff_ref, [])
        if len(wake_candidates) > 1:
            anomalies.append(f"duplicate wake receipts for {handoff_ref}")
        if wake_candidates:
            wake_path, wake_snapshot, wake_value, wake_error = wake_candidates[0]
        else:
            expected_wake_path, expected_wake_ref_error = _direct_child(task_root, entry.get("wake_receipt_ref"))
            if expected_wake_path is not None:
                wake_path = expected_wake_path
                wake_snapshot = read_file_snapshot(expected_wake_path, parser="json")
                wake_value = wake_snapshot.parsed if isinstance(wake_snapshot.parsed, dict) else None
                wake_error = wake_snapshot.parse_error or wake_snapshot.read_error
                if expected_wake_ref_error:
                    wake_error = expected_wake_ref_error
                elif wake_snapshot.currentness == "missing":
                    wake_error = "wake receipt is absent from the bounded directory"
            else:
                wake_path, wake_snapshot, wake_value, wake_error = None, None, None, "wake receipt is absent from the bounded directory"
        effective_handoff_error = handoff_error
        if filter_errors:
            filter_detail = "master filter validation failed: " + "; ".join(filter_errors)
            effective_handoff_error = f"{filter_detail}; {handoff_error}" if handoff_error else filter_detail
        envelopes.append(
            _envelope(
                expected_thread=expected_thread,
                goal_id=goal_id,
                goal_anchor_ref=goal_anchor_ref,
                filter_summary=filter_summary,
                filter_entry=entry,
                handoff_path=handoff_path if handoff_value is not None else None,
                handoff_snapshot=handoff_snapshot,
                handoff=handoff_value,
                handoff_error=effective_handoff_error,
                wake_path=wake_path,
                wake_snapshot=wake_snapshot,
                wake=wake_value,
                wake_error=wake_error if len(wake_candidates) <= 1 else "duplicate wake receipts",
                filter_currentness=filter_snapshot.currentness,
                goal_currentness=goal_anchor_snapshot.currentness,
            )
        )
    filter_ref_set = set(filter_entries)
    deferred_candidates: list[str] = []
    for path, handoff_snapshot, handoff_value, handoff_error in handoffs.values():
        if str(path) in filter_ref_set:
            continue
        deferred_candidates.append(f"unfiltered handoff candidate: {path}")
        if handoff_value is not None and handoff_value.get("master_thread_id") == expected_thread:
            extra_wakes = wakes.get(str(path), [])
            if extra_wakes:
                extra_wake_path, extra_wake_snapshot, extra_wake_value, extra_wake_error = extra_wakes[0]
                extra_wake_ref = str(extra_wake_path)
            else:
                extra_wake_path, extra_wake_snapshot, extra_wake_value, extra_wake_error = None, None, None, "wake receipt is absent from the bounded directory"
                extra_wake_ref = "unresolved:unfiltered"
            filter_entry = {
                "id": path.stem.removesuffix("-luna-handoff"),
                "handoff_ref": str(path),
                "handoff_sha256": handoff_snapshot.digest,
                "wake_receipt_ref": extra_wake_ref,
                "disposition": "not_listed_by_master_filter",
            }
            envelopes.append(
                _envelope(
                    expected_thread=expected_thread,
                    goal_id=goal_id,
                    goal_anchor_ref=goal_anchor_ref,
                    filter_summary=filter_summary,
                    filter_entry=filter_entry,
                    handoff_path=path,
                    handoff_snapshot=handoff_snapshot,
                    handoff=handoff_value,
                    handoff_error=handoff_error,
                    wake_path=extra_wake_path,
                    wake_snapshot=extra_wake_snapshot,
                    wake=extra_wake_value,
                    wake_error=extra_wake_error,
                    filter_currentness=filter_snapshot.currentness,
                    goal_currentness=goal_anchor_snapshot.currentness,
                )
            )
    for wake_ref, candidates in wakes.items():
        if wake_ref not in filter_ref_set:
            deferred_candidates.append(f"unfiltered wake receipt: {wake_ref}")

    if filter_errors:
        state = "invalid"
    elif anomalies or any(item["state"] == "invalid" for item in envelopes):
        state = "invalid"
    elif not envelopes:
        state = "missing"
    elif deferred_candidates or any(item["state"] == "deferred" for item in envelopes):
        state = "deferred"
    elif any(item["state"] == "missing" for item in envelopes):
        state = "deferred"
    else:
        state = "bound"
    degradation = ["transport_delivery_only", "reentry_is_correlation_only"]
    if filter_errors:
        degradation.extend(filter_errors)
    degradation.extend(anomalies)
    degradation.extend(deferred_candidates)
    if not anchor_digest:
        state = "invalid"
        degradation.append("goal_anchor_missing")
    if filter_snapshot.currentness != "current_at_read":
        degradation.append(f"master_filter_currentness:{filter_snapshot.currentness}")
        if filter_snapshot.currentness in {"invalid", "missing"}:
            state = "invalid" if filter_snapshot.currentness == "invalid" else "missing"
        elif state == "bound":
            state = "deferred"
    if goal_anchor_snapshot.currentness != "current_at_read":
        degradation.append(f"goal_anchor_currentness:{goal_anchor_snapshot.currentness}")
        if goal_anchor_snapshot.currentness in {"invalid", "missing"}:
            state = "invalid" if goal_anchor_snapshot.currentness == "invalid" else "missing"
        elif state == "bound":
            state = "deferred"
    observed_at = filter_value.get("reviewed_at") if _non_empty_string(filter_value.get("reviewed_at")) else None
    summary = {
        "handoff_files": len(handoff_paths),
        "wake_files": len(wake_paths),
        "envelopes": len(envelopes),
        "reentered": sum(item["state"] == "reentered" for item in envelopes),
        "invalid": sum(item["state"] == "invalid" for item in envelopes),
        "missing": sum(item["state"] == "missing" for item in envelopes),
        "filtered_return_ids": len(filter_entries),
        "anomalies": len(anomalies) + len(filter_errors),
        "deferred_candidates": len(deferred_candidates),
    }
    projection: CorrelationProjection = {
        "schema_version": CORRELATION_PROJECTION_VERSION,
        "state": state,
        "master_thread_id": expected_thread,
        "current_holder": holder,
        "master_filter": filter_summary,
        "envelopes": envelopes,
        "new_obligations": filter_summary["new_required_obligations"],
        "rejected_or_deferred_claims": filter_summary["rejected_or_deferred_claims"],
        "summary": summary,
        "observed_at": observed_at,
        "freshness": "current_at_read" if state == "bound" else state,
        "degradation": degradation,
        "authority": "aoa-dashboard:derived_task_local_correlation",
        "claim_limit": claim_limit,
    }
    return _source(
        state=state,
        freshness=projection["freshness"],
        observation=(
            f"Validated {summary['reentered']} task-local filtered return correlations for master thread {expected_thread}."
            if state == "bound"
            else "Task-local correlation is degraded; invalid, mismatched, or absent evidence remains visible."
        ),
        metadata=projection,
        refs=base_refs,
        degradation=degradation,
        claim_limit=claim_limit,
    )
