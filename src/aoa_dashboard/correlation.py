from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, TypedDict

from .wake_receipts import (
    CODEX_WAKE_RECEIPT_SCHEMA_VERSION,
    TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION,
    make_wake_provenance,
    normalize_handoff_sha256,
    validate_codex_wake_owner_binding,
    validate_codex_wake_receipt_v1,
    wake_source_family,
    wake_source_kind,
)


CORRELATION_SCHEMA_VERSION = "aoa_dashboard_correlation_envelope_v1"
CORRELATION_PROJECTION_VERSION = "aoa_dashboard_correlation_projection_v1"
WAKE_RECEIPT_SCHEMA_VERSION = TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION
DELIVERY_OUTCOMES = frozenset({"handoff_delivered_pending_master_filter"})
SHA256_LENGTH = 64


CorrelationState = Literal["reentered", "returned", "missing", "deferred", "invalid"]


class CorrelationRef(TypedDict):
    label: str
    kind: str
    ref: str
    sha256: str | None
    observed_at: str | None
    freshness: str
    degradation: list[str]
    authority: str
    claim_limit: str


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
    new_obligations: list[str]
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


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "top-level JSON value is not an object"
    return value, None


def _sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


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
    degradation: list[str] | None = None,
    claim_limit: str,
) -> CorrelationRef:
    return {
        "label": label,
        "kind": kind,
        "ref": str(path),
        "sha256": digest,
        "observed_at": observed_at,
        "freshness": freshness,
        "degradation": list(degradation or []),
        "authority": "aoa-dashboard:derived",
        "claim_limit": claim_limit,
    }


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


def _file_ref(
    label: str,
    kind: str,
    path: Path,
    *,
    observed_at: str | None,
    freshness: str,
    degradation: list[str] | None = None,
    claim_limit: str,
) -> CorrelationRef:
    return _ref(
        label,
        kind,
        path,
        digest=_sha256(path),
        observed_at=observed_at,
        freshness=freshness,
        degradation=degradation,
        claim_limit=claim_limit,
    )


def _missing_ref(label: str, kind: str, path: Path | str, claim_limit: str) -> CorrelationRef:
    return _ref(
        label,
        kind,
        path,
        digest=None,
        observed_at=None,
        freshness="missing",
        degradation=["source_missing"],
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
    owner_contract: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    schema_version = wake.get("schema_version")
    raw_handoff_digest = wake.get("handoff_sha256")
    normalized_handoff_digest = normalize_handoff_sha256(
        raw_handoff_digest, schema_version=schema_version
    )

    if schema_version == CODEX_WAKE_RECEIPT_SCHEMA_VERSION:
        errors.extend(validate_codex_wake_owner_binding(owner_contract))
        errors.extend(validate_codex_wake_receipt_v1(wake))
        if wake.get("master_thread_id") != expected_thread:
            errors.append("codex v1 wake receipt master_thread_id mismatch")
        if wake.get("handoff_ref") != expected_handoff_ref:
            errors.append("codex v1 wake receipt handoff_ref mismatch")
        if normalized_handoff_digest is None:
            errors.append("codex v1 wake receipt handoff_sha256 is not normalizable")
        elif normalized_handoff_digest != expected_handoff_digest:
            errors.append("codex v1 wake receipt normalized handoff_sha256 mismatch")
        if wake.get("outcome") != "handoff_delivered_pending_master_filter":
            errors.append("codex v1 wake receipt delivery failed; no wake admission claim")
        delivery = {
            "schema_version": schema_version,
            "source_family": wake_source_family(schema_version),
            "outcome": wake.get("outcome"),
            "delivery_route": wake.get("delivery_route"),
            "route": wake.get("route"),
            "stage": wake.get("stage"),
            "request_id": wake.get("request_id"),
            "client_user_message_id": wake.get("client_user_message_id"),
            "handoff_delivery": wake.get("outcome") == "handoff_delivered_pending_master_filter",
            "handoff_message_submitted": None,
            "accepted_turn_id": wake.get("accepted_turn_id"),
            "goal_resume_requested": None,
            "observed_at": wake.get("attempted_at") or wake.get("generated_at"),
            "attempts": wake.get("attempts"),
            "responsibility_state": wake.get("responsibility_state"),
            "failure": wake.get("failure"),
            "raw_handoff_sha256": raw_handoff_digest,
            "normalized_handoff_sha256": normalized_handoff_digest,
        }
        return errors, delivery

    if schema_version == WAKE_RECEIPT_SCHEMA_VERSION:
        observed = wake.get("observed") if isinstance(wake.get("observed"), dict) else {}
        actions = wake.get("actions") if isinstance(wake.get("actions"), dict) else {}
        if wake.get("thread_id") != expected_thread:
            errors.append("wake receipt thread_id mismatch")
        if wake.get("handoff_ref") != expected_handoff_ref:
            errors.append("wake receipt handoff_ref mismatch")
        if normalized_handoff_digest != expected_handoff_digest:
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
            "schema_version": schema_version,
            "source_family": wake_source_family(schema_version),
            "outcome": wake.get("outcome"),
            "delivery_route": observed.get("delivery_route"),
            "route": None,
            "stage": None,
            "request_id": None,
            "client_user_message_id": None,
            "handoff_delivery": observed.get("handoff_delivery")
            if isinstance(observed.get("handoff_delivery"), bool)
            else None,
            "handoff_message_submitted": actions.get("handoff_message_submitted")
            if isinstance(actions.get("handoff_message_submitted"), bool)
            else None,
            "accepted_turn_id": observed.get("accepted_turn_id"),
            "goal_resume_requested": actions.get("goal_resume_requested")
            if isinstance(actions.get("goal_resume_requested"), bool)
            else None,
            "observed_at": wake.get("attempted_at") or wake.get("generated_at"),
            "attempts": None,
            "responsibility_state": None,
            "failure": None,
            "raw_handoff_sha256": raw_handoff_digest,
            "normalized_handoff_sha256": normalized_handoff_digest,
        }
        return errors, delivery

    errors.append(f"unsupported wake receipt schema_version: {schema_version!r}")
    if wake.get("master_thread_id", wake.get("thread_id")) != expected_thread:
        errors.append("unsupported wake receipt master/thread id mismatch")
    if wake.get("handoff_ref") != expected_handoff_ref:
        errors.append("unsupported wake receipt handoff_ref mismatch")
    if normalized_handoff_digest != expected_handoff_digest:
        errors.append("unsupported wake receipt handoff_sha256 mismatch")
    return errors, {
        "schema_version": schema_version,
        "source_family": wake_source_family(schema_version),
        "outcome": wake.get("outcome"),
        "delivery_route": wake.get("delivery_route"),
        "route": wake.get("route"),
        "stage": wake.get("stage"),
        "request_id": wake.get("request_id"),
        "client_user_message_id": wake.get("client_user_message_id"),
        "handoff_delivery": None,
        "handoff_message_submitted": None,
        "accepted_turn_id": None,
        "goal_resume_requested": None,
        "observed_at": wake.get("attempted_at") or wake.get("generated_at"),
        "attempts": wake.get("attempts"),
        "responsibility_state": wake.get("responsibility_state"),
        "failure": wake.get("failure"),
        "raw_handoff_sha256": raw_handoff_digest,
        "normalized_handoff_sha256": normalized_handoff_digest,
    }


def _master_filter_summary(
    value: dict[str, Any],
    filter_path: Path,
    digest: str | None,
    dag: list[dict[str, str]],
    entries: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    claim_limit = (
        "The master filter is task-local disposition evidence. It is not proof, owner acceptance, "
        "or permission to execute a runtime action."
    )
    return {
        "schema_version": value.get("schema_version"),
        "ref": _file_ref(
            "master return filter",
            "task_local_master_filter",
            filter_path,
            observed_at=value.get("reviewed_at"),
            freshness="current_at_read",
            claim_limit=claim_limit,
        ),
        "reviewed_at": value.get("reviewed_at"),
        "return_ids": [item.get("id") for item in entries.values() if _non_empty_string(item.get("id"))],
        "goal_ref": value.get("goal_ref"),
        "goal_dag": dag,
        "new_required_obligations": [
            item for item in value.get("new_required_obligations", []) if isinstance(item, str)
        ],
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
    handoff: dict[str, Any] | None,
    handoff_error: str | None,
    wake_path: Path | None,
    wake: dict[str, Any] | None,
    wake_error: str | None,
    wake_candidates: list[tuple[Path, dict[str, Any] | None, str | None]] | None = None,
    owner_contract: dict[str, Any] | None = None,
) -> CorrelationEnvelope:
    claim_limit = _base_claim_limit()
    expected_handoff_ref = filter_entry.get("handoff_ref")
    expected_handoff_digest = filter_entry.get("handoff_sha256")
    handoff_ref = (
        _file_ref(
            "Luna handoff",
            "task_local_handoff",
            handoff_path,
            observed_at=(handoff or {}).get("summary", {}).get("snapshot_utc")
            if isinstance((handoff or {}).get("summary"), dict)
            else None,
            freshness="current_at_read",
            claim_limit="The handoff is a task-local return artifact; its contents do not become owner truth.",
        )
        if handoff_path is not None
        else _missing_ref(
            "Luna handoff",
            "task_local_handoff",
            expected_handoff_ref or "unresolved:handoff",
            "The handoff ref is listed by the master filter but the file is absent or unreadable.",
        )
    )
    wake_schema_version = wake.get("schema_version") if isinstance(wake, dict) else None
    wake_kind = wake_source_kind(wake_schema_version)
    wake_ref = (
        _file_ref(
            "wake receipt",
            wake_kind,
            wake_path,
            observed_at=(wake or {}).get("attempted_at") or (wake or {}).get("generated_at"),
            freshness="current_at_read",
            claim_limit="Wake delivery is transport evidence only; it does not prove acceptance or semantic continuation.",
        )
        if wake_path is not None
        else _missing_ref(
            "wake receipt",
            wake_kind,
            filter_entry.get("wake_receipt_ref") or "unresolved:wake-receipt",
            "The master filter names a wake receipt that is absent or unreadable.",
        )
    )
    candidate_values = list(wake_candidates or [])
    if not candidate_values and wake_path is not None:
        candidate_values = [(wake_path, wake, wake_error)]
    candidate_refs: list[dict[str, Any]] = []
    for candidate_path, candidate_value, candidate_error in candidate_values:
        candidate_schema = candidate_value.get("schema_version") if isinstance(candidate_value, dict) else None
        candidate_digest = _sha256(candidate_path)
        candidate_ref = _file_ref(
            "wake receipt candidate",
            wake_source_kind(candidate_schema),
            candidate_path,
            observed_at=(candidate_value or {}).get("attempted_at") or (candidate_value or {}).get("generated_at"),
            freshness="invalid" if candidate_error else "current_at_read",
            degradation=["receipt_unreadable"] if candidate_error else [],
            claim_limit="Candidate identity is preserved for collision review; it does not establish a delivery or re-entry claim.",
        )
        candidate_refs.append(
            {
                "schema_version": candidate_schema,
                "source_family": wake_source_family(candidate_schema),
                "raw_owner_ref": str(candidate_path),
                "raw_owner_content_sha256": candidate_digest,
                "ref": candidate_ref,
                "error": candidate_error,
            }
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
        actual_digest = _sha256(handoff_path) if handoff_path else None
        if actual_digest != expected_handoff_digest:
            errors.append("handoff SHA-256 does not match master filter")
    wake_missing = wake is None and wake_error == "wake receipt is absent from the bounded directory"
    if wake_error and not wake_missing:
        errors.append(f"wake receipt: {wake_error}")
    if len(candidate_values) > 1:
        candidate_schemas = [
            candidate_value.get("schema_version") if isinstance(candidate_value, dict) else None
            for _, candidate_value, _ in candidate_values
        ]
        errors.append(
            "wake receipt collision: multiple receipts for one handoff "
            + ", ".join(str(schema) for schema in candidate_schemas)
        )

    delivery: dict[str, Any] = {
        "schema_version": None,
        "source_family": wake_source_family(None),
        "outcome": None,
        "delivery_route": None,
        "route": None,
        "stage": None,
        "request_id": None,
        "client_user_message_id": None,
        "handoff_delivery": None,
        "handoff_message_submitted": None,
        "accepted_turn_id": None,
        "goal_resume_requested": None,
        "observed_at": None,
        "attempts": None,
        "responsibility_state": None,
        "failure": None,
        "raw_handoff_sha256": None,
        "normalized_handoff_sha256": None,
    }
    wake_errors: list[str] = []
    if wake is None:
        if not wake_missing:
            errors.append("wake receipt payload is missing")
    else:
        wake_errors, delivery = _validate_wake(
            wake,
            expected_thread=expected_thread,
            expected_handoff_ref=str(expected_handoff_ref),
            expected_handoff_digest=expected_handoff_digest,
            owner_contract=owner_contract,
        )
        errors.extend(wake_errors)
        if wake_path is not None and wake_ref["sha256"] is None:
            errors.append("wake receipt digest is unavailable")
        if wake_path is not None and str(wake_path) != str(filter_entry.get("wake_receipt_ref")):
            errors.append("wake receipt path does not match master filter wake_receipt_ref")
    wake_source_errors = list(wake_errors)
    if len(candidate_values) > 1:
        wake_source_errors.append("wake receipt collision")
    wake_freshness = "missing" if wake_missing else ("invalid" if wake_source_errors or wake_error else "current_at_read")
    wake_missingness = "missing" if wake_missing else ("present_but_invalid" if wake_source_errors or wake_error else "present")
    wake_ref["freshness"] = wake_freshness
    if wake_source_errors:
        wake_ref["degradation"] = list(wake_ref.get("degradation", [])) + wake_source_errors
    provenance = make_wake_provenance(
        schema_version=delivery["schema_version"],
        raw_ref=(
            str(wake_path)
            if wake_path is not None
            else (filter_entry.get("wake_receipt_ref") if _non_empty_string(filter_entry.get("wake_receipt_ref")) else None)
        ),
        raw_content_sha256=wake_ref.get("sha256"),
        freshness=wake_freshness,
        missingness=wake_missingness,
        owner_contract=owner_contract,
    )

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

    handoff_metadata = {
        "return_id": filter_entry.get("id") or (handoff_path.stem if handoff_path else None),
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
        "source_schema_version": delivery["schema_version"],
        "source_family": delivery["source_family"],
        "adapter_version": provenance["adapter_version"],
        "provenance": provenance,
        "freshness": wake_freshness,
        "missingness": wake_missingness,
        "authority": "aoa-dashboard:derived_task_local_correlation",
        "outcome": delivery["outcome"],
        "delivery_route": delivery["delivery_route"],
        "route": delivery["route"],
        "stage": delivery["stage"],
        "request_id": delivery["request_id"],
        "client_user_message_id": delivery["client_user_message_id"],
        "handoff_delivery": delivery["handoff_delivery"],
        "handoff_message_submitted": delivery["handoff_message_submitted"],
        "observed_at": delivery["observed_at"],
        "attempts": delivery["attempts"],
        "responsibility_state": delivery["responsibility_state"],
        "failure": delivery["failure"],
        "raw_handoff_sha256": delivery["raw_handoff_sha256"],
        "normalized_handoff_sha256": delivery["normalized_handoff_sha256"],
        "candidate_receipts": candidate_refs,
        "claim_limit": (
            f"{provenance['claim_limit']} Delivery is not proof, acceptance, "
            "or semantic continuation."
        ),
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
    wake_schema_label = delivery["schema_version"] or "unknown wake source"
    lifecycle = {
        "returned": _empty_lifecycle(
            return_state,
            "The handoff is listed by the master filter and its thread/hash checks are retained." if return_state == "returned" else "The return cannot be treated as valid.",
            [handoff_ref, filter_summary["ref"]],
            lifecycle_claim,
        ),
        "wake_requested": _empty_lifecycle(
            wake_state,
            (
                f"Wake delivery is observed from the dashboard-validated {wake_schema_label} source receipt."
                if wake_state == "wake requested"
                else "No validated wake delivery is available."
            ),
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


def observe_current_correlation(config: dict[str, Any]) -> dict[str, Any]:
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
    anchor_digest = _sha256(goal_anchor_path_obj)
    goal_anchor_ref = _file_ref(
        "Goal Anchor",
        "goal_anchor",
        goal_anchor_path_obj,
        observed_at=_utc_now() if anchor_digest else None,
        freshness="current_at_read" if anchor_digest else "missing",
        claim_limit="Goal Anchor ref and digest bind this projection; they do not prove execution, review, or acceptance.",
    ) if anchor_digest else _missing_ref(
        "Goal Anchor",
        "goal_anchor",
        goal_anchor_path_obj,
        "Goal Anchor is absent; correlation cannot claim a current Goal binding.",
    )
    directory_ref = _file_ref(
        "task-local correlation directory",
        "task_local_directory",
        task_root,
        observed_at=_utc_now() if task_root.exists() else None,
        freshness="current_at_read" if task_root.is_dir() else "missing",
        claim_limit="Directory presence is a binding observation, not runtime health or acceptance.",
    ) if task_root.exists() else _missing_ref(
        "task-local correlation directory",
        "task_local_directory",
        task_root,
        "Task-local receipt directory is absent; no current return/wake claim is made.",
    )
    filter_ref = _file_ref(
        "master return filter",
        "task_local_master_filter",
        filter_path,
        observed_at=None,
        freshness="current_at_read",
        claim_limit="The master filter is task-local disposition evidence, not proof or owner acceptance.",
    ) if filter_path.is_file() else _missing_ref(
        "master return filter",
        "task_local_master_filter",
        filter_path,
        "Master filter is absent; filtered disposition and re-entry correlation remain missing.",
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
    filter_value, filter_error = _read_json(filter_path)
    if filter_error or filter_value is None:
        return _source(
            state="missing" if not filter_path.exists() else "invalid",
            freshness="missing" if not filter_path.exists() else "invalid",
            observation="Master filter is absent." if not filter_path.exists() else f"Master filter is unreadable: {filter_error}",
            metadata={
                "schema_version": CORRELATION_PROJECTION_VERSION,
                "master_thread_id": expected_thread,
                "current_holder": holder,
                "master_filter": {"ref": filter_ref, "state": "missing" if not filter_path.exists() else "invalid", "claim_limit": claim_limit},
                "envelopes": [],
                "new_obligations": [],
                "rejected_or_deferred_claims": [],
                "summary": {"handoff_files": None, "wake_files": None, "envelopes": None},
                "observed_at": None,
                "freshness": "missing" if not filter_path.exists() else "invalid",
                "degradation": ["master_filter_missing" if not filter_path.exists() else "master_filter_unreadable"],
                "authority": "aoa-dashboard:derived_task_local_correlation",
                "claim_limit": claim_limit,
            },
            refs=base_refs,
            degradation=["master_filter_missing" if not filter_path.exists() else "master_filter_unreadable"],
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
    filter_summary = _master_filter_summary(filter_value, filter_path, _sha256(filter_path), dag, filter_entries)
    if filter_summary["ref"]["observed_at"] is None:
        filter_summary["ref"]["observed_at"] = filter_value.get("reviewed_at")
    handoff_glob = current.get("handoff_glob", "*-luna-handoff.json")
    wake_glob = current.get("wake_glob", "*.wake-receipt.json")
    owner_contract = current.get("codex_wake_receipt_owner")
    if not isinstance(owner_contract, dict):
        owner_contract = None
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
    handoffs: dict[str, tuple[Path, dict[str, Any] | None, str | None]] = {}
    for path in handoff_paths:
        value, error = _read_json(path)
        handoffs[str(path)] = (path, value, error)
    wakes: dict[str, list[tuple[Path, dict[str, Any] | None, str | None]]] = {}
    anomalies: list[str] = []
    for path in wake_paths:
        value, error = _read_json(path)
        handoff_ref_value = value.get("handoff_ref") if value else None
        handoff_ref_path, ref_error = _direct_child(task_root, handoff_ref_value)
        if ref_error:
            anomalies.append(f"wake {path.name}: {ref_error}")
            continue
        assert handoff_ref_path is not None
        wakes.setdefault(str(handoff_ref_path), []).append((path, value, error))
    envelopes: list[CorrelationEnvelope] = []
    for handoff_ref, entry in filter_entries.items():
        handoff_path, handoff_value, handoff_error = handoffs.get(
            handoff_ref,
            (Path(handoff_ref), None, "handoff file is absent from the bounded directory"),
        )
        wake_candidates = wakes.get(handoff_ref, [])
        if len(wake_candidates) > 1:
            anomalies.append(f"duplicate wake receipts for {handoff_ref}")
        expected_wake_path, expected_wake_ref_error = _direct_child(task_root, entry.get("wake_receipt_ref"))
        selected_candidate = next(
            (candidate for candidate in wake_candidates if expected_wake_path is not None and candidate[0] == expected_wake_path),
            wake_candidates[0] if wake_candidates else None,
        )
        if selected_candidate is not None:
            wake_path, wake_value, wake_error = selected_candidate
        else:
            if expected_wake_path is not None and expected_wake_path.is_file():
                wake_path = expected_wake_path
                wake_value, wake_error = _read_json(expected_wake_path)
                if expected_wake_ref_error:
                    wake_error = expected_wake_ref_error
            else:
                wake_path, wake_value, wake_error = None, None, "wake receipt is absent from the bounded directory"
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
                handoff=handoff_value,
                handoff_error=effective_handoff_error,
                wake_path=wake_path,
                wake=wake_value,
                wake_error=wake_error if len(wake_candidates) <= 1 else "duplicate wake receipts",
                wake_candidates=wake_candidates or ([(wake_path, wake_value, wake_error)] if wake_path is not None else []),
                owner_contract=owner_contract,
            )
        )
    filter_ref_set = set(filter_entries)
    deferred_candidates: list[str] = []
    for path, handoff_value, handoff_error in handoffs.values():
        if str(path) in filter_ref_set:
            continue
        deferred_candidates.append(f"unfiltered handoff candidate: {path}")
        if handoff_value is not None and handoff_value.get("master_thread_id") == expected_thread:
            extra_wakes = wakes.get(str(path), [])
            if extra_wakes:
                extra_wake_path, extra_wake_value, extra_wake_error = extra_wakes[0]
                extra_wake_ref = str(extra_wake_path)
            else:
                extra_wake_path, extra_wake_value, extra_wake_error = None, None, "wake receipt is absent from the bounded directory"
                extra_wake_ref = "unresolved:unfiltered"
            filter_entry = {
                "id": path.stem.removesuffix("-luna-handoff"),
                "handoff_ref": str(path),
                "handoff_sha256": _sha256(path),
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
                    handoff=handoff_value,
                    handoff_error=handoff_error,
                    wake_path=extra_wake_path,
                    wake=extra_wake_value,
                    wake_error=extra_wake_error,
                    wake_candidates=extra_wakes or ([(extra_wake_path, extra_wake_value, extra_wake_error)] if extra_wake_path is not None else []),
                    owner_contract=owner_contract,
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
    observed_wake_schemas = sorted(
        {
            item["wake_observation"].get("source_schema_version")
            for item in envelopes
            if item["wake_observation"].get("source_schema_version")
        }
    )
    wake_schema_summary = ", ".join(observed_wake_schemas) or "no wake receipt schema"
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
            f"Validated {summary['reentered']} filtered return correlations from {wake_schema_summary} "
            f"for master thread {expected_thread}."
            if state == "bound"
            else "Correlation is degraded; invalid, mismatched, or absent evidence remains visible."
        ),
        metadata=projection,
        refs=base_refs,
        degradation=degradation,
        claim_limit=claim_limit,
    )
