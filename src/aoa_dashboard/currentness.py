"""Owner-authored current-head admission and explicit advancement procedure.

The master return disposition is intentionally mutable: every accepted return
may extend it.  The dashboard resolver does not turn that file into dashboard
authority; the explicit owner procedure below only derives a new attestation
from selected filter bytes and preserves append-only history.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .source_binding import FileSnapshot, is_sha256, read_file_snapshot, snapshot_ref


CURRENTNESS_BINDING_SCHEMA_VERSION = "aoa_dashboard_master_filter_currentness_binding_v1"
CURRENT_HEAD_SCHEMA_VERSION = "aoa_dashboard_master_filter_current_head_v1"
HISTORY_RECORD_SCHEMA_VERSION = "aoa_dashboard_master_filter_head_record_v1"

CURRENTNESS_CLAIM_LIMIT = (
    "Currentness is a dashboard-derived read of the master-thread owner's "
    "content-addressed head attestation. It is not proof, acceptance, semantic "
    "continuation, or permission to execute a Goal transition."
)
CURRENT_HEAD_CLAIM_LIMIT = (
    "The current-head and history files are master-thread owner evidence. "
    "The dashboard preserves their refs and digests but does not author, "
    "rewrite, or accept the master disposition."
)
LEGACY_SNAPSHOT_CLAIM_LIMIT = (
    "The former expected digest is retained as historical bootstrap evidence "
    "only. It is never used to decide currentness after migration."
)

_BINDING_FIELDS = frozenset(
    {
        "schema_version",
        "owner",
        "authority",
        "access_scope",
        "filter_ref",
        "current_head_ref",
        "history_ref",
        "claim_limit",
    }
)
_HEAD_FIELDS = frozenset(
    {
        "schema_version",
        "owner",
        "authority",
        "access_scope",
        "master_thread_id",
        "goal_ref",
        "filter_ref",
        "history_ref",
        "head_sha256",
        "sequence",
        "reviewed_at",
        "transition",
        "previous_head_sha256",
        "claim_limit",
    }
)
_TRANSITIONS = frozenset({"initial", "advance", "rollback"})
ADVANCEMENT_RECEIPT_SCHEMA_VERSION = "aoa_dashboard_currentness_advancement_receipt_v1"
ADVANCEMENT_CLAIM_LIMIT = (
    "This receipt records a bounded owner procedure that derived a current-head "
    "digest from selected filter bytes. It is not master acceptance, proof, "
    "semantic continuation, runtime health, or human acceptance."
)


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _canonical_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        return None
    candidate = Path(value).resolve(strict=False)
    if str(candidate) != value:
        return None
    return candidate


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return candidate != root


def _required_path(value: Path | str, *, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be an absolute path")
    resolved = path.resolve(strict=False)
    if str(resolved) != str(path):
        raise ValueError(f"{label} must be the exact canonical path")
    if not resolved.parent.is_dir():
        raise ValueError(f"{label} parent directory is missing")
    return resolved


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _atomic_replace(path: Path, payload: bytes) -> None:
    mode = path.stat().st_mode if path.exists() else None
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary_path, mode & 0o7777)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _head_record(
    *,
    schema_version: str,
    owner: str,
    authority: str,
    access_scope: str,
    master_thread_id: str,
    goal_ref: str,
    filter_ref: str,
    history_ref: str,
    head_sha256: str,
    sequence: int,
    reviewed_at: str,
    transition: str,
    previous_head_sha256: str | None,
    claim_limit: str,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "owner": owner,
        "authority": authority,
        "access_scope": access_scope,
        "master_thread_id": master_thread_id,
        "goal_ref": goal_ref,
        "filter_ref": filter_ref,
        "history_ref": history_ref,
        "head_sha256": head_sha256,
        "sequence": sequence,
        "reviewed_at": reviewed_at,
        "transition": transition,
        "previous_head_sha256": previous_head_sha256,
        "claim_limit": claim_limit,
    }


def _validate_lineage_tail(head: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if not records:
        return ["current_head_history_missing"]
    sequences = [record.get("sequence") for record in records]
    if sequences != list(range(len(records))):
        errors.append("current_head_history_conflict")
    last = records[-1]
    if head.get("sequence") != last.get("sequence") or head.get("head_sha256") != last.get("head_sha256"):
        errors.append("current_head_history_conflict")
    if head.get("sequence") == 0:
        if head.get("previous_head_sha256") is not None:
            errors.append("current_head_history_conflict")
    elif head.get("previous_head_sha256") != records[-2].get("head_sha256"):
        errors.append("current_head_history_conflict")
    return list(dict.fromkeys(errors))


def _advancement_receipt(
    *,
    status: str,
    changed: bool,
    filter_path: Path,
    filter_sha256: str,
    current_head_path: Path,
    history_path: Path,
    head: dict[str, Any],
    history_record_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": ADVANCEMENT_RECEIPT_SCHEMA_VERSION,
        "status": status,
        "changed": changed,
        "filter_ref": str(filter_path),
        "filter_sha256": filter_sha256,
        "current_head_ref": str(current_head_path),
        "history_ref": str(history_path),
        "head": _safe_head(head),
        "history_record_count": history_record_count,
        "claim_limit": ADVANCEMENT_CLAIM_LIMIT,
    }


def advance_master_filter_currentness(
    *,
    filter_path: Path | str,
    current_head_path: Path | str,
    history_path: Path | str,
    master_thread_id: str,
    goal_ref: str,
    reviewed_at: str,
    transition: str = "advance",
) -> dict[str, Any]:
    """Publish one content-derived owner current-head transition.

    The caller selects the owner-reviewed filter bytes and transition meaning;
    this procedure derives the filter digest, sequence, and previous digest.
    It never edits the filter or any runtime configuration. An existing
    invalid lineage is rejected so migration can bind a new lineage while
    retaining the old append-only material as evidence.
    """

    if transition not in _TRANSITIONS:
        raise ValueError(f"unsupported transition: {transition}")
    if not _non_empty(master_thread_id) or not _non_empty(goal_ref) or not _non_empty(reviewed_at):
        raise ValueError("master_thread_id, goal_ref, and reviewed_at are required")

    filter_path = _required_path(filter_path, label="filter_path")
    current_head_path = _required_path(current_head_path, label="current_head_path")
    history_path = _required_path(history_path, label="history_path")
    if not filter_path.is_file():
        raise ValueError("filter_path is missing")
    try:
        filter_bytes = filter_path.read_bytes()
        filter_value = json.loads(filter_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("filter_path is not readable JSON") from exc
    if not isinstance(filter_value, dict):
        raise ValueError("filter_path must contain a JSON object")
    filter_sha256 = hashlib.sha256(filter_bytes).hexdigest()

    current_head_exists = current_head_path.exists()
    history_exists = history_path.exists()
    if not current_head_exists and not history_exists:
        if transition != "initial":
            raise ValueError("a new lineage must start with initial")
        head = _head_record(
            schema_version=CURRENT_HEAD_SCHEMA_VERSION,
            owner="master-thread",
            authority="master_decision",
            access_scope="owner_bounded",
            master_thread_id=master_thread_id,
            goal_ref=goal_ref,
            filter_ref=str(filter_path),
            history_ref=str(history_path),
            head_sha256=filter_sha256,
            sequence=0,
            reviewed_at=reviewed_at,
            transition="initial",
            previous_head_sha256=None,
            claim_limit=CURRENT_HEAD_CLAIM_LIMIT,
        )
        history_record = dict(head)
        history_record["schema_version"] = HISTORY_RECORD_SCHEMA_VERSION
        history_line = json.dumps(history_record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        with history_path.open("ab") as stream:
            stream.write(history_line)
            stream.flush()
            os.fsync(stream.fileno())
        _atomic_replace(current_head_path, json.dumps(head, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        return _advancement_receipt(
            status="initialized",
            changed=True,
            filter_path=filter_path,
            filter_sha256=filter_sha256,
            current_head_path=current_head_path,
            history_path=history_path,
            head=head,
            history_record_count=1,
        )

    if not history_exists:
        raise ValueError("current-head exists without append-only history")

    history_snapshot = read_file_snapshot(history_path, parser="text")
    records, history_read_errors = _history_records(history_snapshot)
    if history_read_errors:
        raise ValueError("existing history is invalid: " + ", ".join(history_read_errors))
    history_errors, _ = _validate_history(
        records,
        expected_owner="master-thread",
        expected_thread=master_thread_id,
        expected_goal_ref=goal_ref,
        expected_filter_ref=str(filter_path),
        expected_history_ref=str(history_path),
    )
    if history_errors:
        raise ValueError("existing history is invalid: " + ", ".join(history_errors))

    if not current_head_exists:
        last = records[-1]
        if last.get("head_sha256") != filter_sha256:
            raise ValueError("current-head is missing and history does not attest the selected filter")
        head = dict(last)
        head["schema_version"] = CURRENT_HEAD_SCHEMA_VERSION
        _atomic_replace(current_head_path, json.dumps(head, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        return _advancement_receipt(
            status="recovered",
            changed=True,
            filter_path=filter_path,
            filter_sha256=filter_sha256,
            current_head_path=current_head_path,
            history_path=history_path,
            head=head,
            history_record_count=len(records),
        )

    head = _read_json_object(current_head_path, label="current_head_path")
    head_errors = _validate_head_shape(
        head,
        expected_owner="master-thread",
        expected_thread=master_thread_id,
        expected_goal_ref=goal_ref,
        expected_filter_ref=str(filter_path),
        expected_history_ref=str(history_path),
        schema_version=CURRENT_HEAD_SCHEMA_VERSION,
    )
    if head_errors:
        raise ValueError("current head is invalid: " + ", ".join(head_errors))

    lineage_errors = _validate_lineage_tail(head, records)
    if lineage_errors:
        raise ValueError("current head/history lineage is invalid: " + ", ".join(lineage_errors))

    if head["head_sha256"] == filter_sha256:
        return _advancement_receipt(
            status="unchanged",
            changed=False,
            filter_path=filter_path,
            filter_sha256=filter_sha256,
            current_head_path=current_head_path,
            history_path=history_path,
            head=head,
            history_record_count=len(records),
        )

    known_digests = {record["head_sha256"] for record in records}
    if filter_sha256 in known_digests and transition != "rollback":
        raise ValueError("selected filter is a prior head; declare rollback")
    if transition == "rollback" and filter_sha256 not in known_digests:
        raise ValueError("rollback target is absent from history")

    next_head = _head_record(
        schema_version=CURRENT_HEAD_SCHEMA_VERSION,
        owner=head["owner"],
        authority=head["authority"],
        access_scope=head["access_scope"],
        master_thread_id=master_thread_id,
        goal_ref=goal_ref,
        filter_ref=str(filter_path),
        history_ref=str(history_path),
        head_sha256=filter_sha256,
        sequence=head["sequence"] + 1,
        reviewed_at=reviewed_at,
        transition=transition,
        previous_head_sha256=head["head_sha256"],
        claim_limit=head["claim_limit"],
    )
    history_record = dict(next_head)
    history_record["schema_version"] = HISTORY_RECORD_SCHEMA_VERSION
    history_line = json.dumps(history_record, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
    with history_path.open("ab") as stream:
        stream.write(history_line)
        stream.flush()
        os.fsync(stream.fileno())
    _atomic_replace(current_head_path, json.dumps(next_head, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
    return _advancement_receipt(
        status="advanced",
        changed=True,
        filter_path=filter_path,
        filter_sha256=filter_sha256,
        current_head_path=current_head_path,
        history_path=history_path,
        head=next_head,
        history_record_count=len(records) + 1,
    )


def _safe_head(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        "sha256": value.get("head_sha256") if is_sha256(value.get("head_sha256")) else None,
        "sequence": value.get("sequence") if isinstance(value.get("sequence"), int) and not isinstance(value.get("sequence"), bool) else None,
        "reviewed_at": value.get("reviewed_at") if _non_empty(value.get("reviewed_at")) else None,
        "transition": value.get("transition") if value.get("transition") in _TRANSITIONS else None,
        "previous_head_sha256": value.get("previous_head_sha256") if is_sha256(value.get("previous_head_sha256")) else None,
    }


def _owner_ref(
    snapshot: FileSnapshot,
    *,
    label: str,
    kind: str,
) -> dict[str, Any]:
    return snapshot_ref(
        snapshot,
        label=label,
        kind=kind,
        owner="master-thread",
        access_scope="owner_bounded",
        authority="master_decision",
        claim_policy="master_decision_disposition",
        snapshot_role="owner_attested_currentness",
        claim_limit=CURRENT_HEAD_CLAIM_LIMIT,
    )


def _history_records(snapshot: FileSnapshot) -> tuple[list[dict[str, Any]], list[str]]:
    if snapshot.raw_bytes is None:
        return [], ["current_head_history_missing"]
    if snapshot.read_error or snapshot.parse_error:
        return [], ["current_head_history_invalid"]
    try:
        text = snapshot.raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return [], ["current_head_history_invalid"]
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append("current_head_history_invalid")
            continue
        if not isinstance(value, dict) or set(value) != _HEAD_FIELDS:
            errors.append("current_head_history_invalid")
            continue
        records.append(value)
    if not records and not errors:
        errors.append("current_head_history_missing")
    return records, errors


def _validate_head_shape(
    value: Any,
    *,
    expected_owner: str,
    expected_thread: str,
    expected_goal_ref: str,
    expected_filter_ref: str,
    expected_history_ref: str,
    schema_version: str,
) -> list[str]:
    if not isinstance(value, dict):
        return ["current_head_parse_failed"]
    errors: list[str] = []
    if set(value) != _HEAD_FIELDS:
        errors.append("current_head_schema_unsupported")
    if value.get("schema_version") != schema_version:
        errors.append("current_head_schema_unsupported")
    if value.get("owner") != expected_owner:
        errors.append("current_head_authority_conflict")
    if value.get("authority") != "master_decision" or value.get("access_scope") != "owner_bounded":
        errors.append("current_head_authority_conflict")
    if value.get("master_thread_id") != expected_thread or value.get("goal_ref") != expected_goal_ref:
        errors.append("current_head_authority_conflict")
    if value.get("filter_ref") != expected_filter_ref or value.get("history_ref") != expected_history_ref:
        errors.append("current_head_filter_ref_mismatch")
    if not is_sha256(value.get("head_sha256")):
        errors.append("current_head_digest_mismatch")
    sequence = value.get("sequence")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        errors.append("current_head_sequence_invalid")
    if not _non_empty(value.get("reviewed_at")):
        errors.append("current_head_schema_unsupported")
    if value.get("transition") not in _TRANSITIONS:
        errors.append("current_head_schema_unsupported")
    previous = value.get("previous_head_sha256")
    if previous is not None and not is_sha256(previous):
        errors.append("current_head_digest_mismatch")
    if not _non_empty(value.get("claim_limit")):
        errors.append("current_head_schema_unsupported")
    return list(dict.fromkeys(errors))


def _validate_history(
    records: list[dict[str, Any]],
    *,
    expected_owner: str,
    expected_thread: str,
    expected_goal_ref: str,
    expected_filter_ref: str,
    expected_history_ref: str,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    previous_sequence: int | None = None
    by_sequence: dict[int, str] = {}
    by_digest: dict[str, list[int]] = {}
    for record in records:
        errors.extend(
            _validate_head_shape(
                record,
                expected_owner=expected_owner,
                expected_thread=expected_thread,
                expected_goal_ref=expected_goal_ref,
                expected_filter_ref=expected_filter_ref,
                expected_history_ref=expected_history_ref,
                schema_version=HISTORY_RECORD_SCHEMA_VERSION,
            )
        )
        sequence = record.get("sequence")
        digest = record.get("head_sha256")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0 or not is_sha256(digest):
            continue
        if sequence in by_sequence:
            errors.append(
                "current_head_history_conflict"
                if by_sequence[sequence] != digest
                else "current_head_ambiguous"
            )
        by_sequence[sequence] = digest
        by_digest.setdefault(digest, []).append(sequence)
        if previous_sequence is not None and sequence <= previous_sequence:
            errors.append("current_head_history_conflict")
        previous_sequence = sequence
    summary = {
        "record_count": len(records),
        "first_sequence": min(by_sequence) if by_sequence else None,
        "last_sequence": max(by_sequence) if by_sequence else None,
        "head_digests": [
            {"sha256": digest, "sequences": sorted(sequences)}
            for digest, sequences in sorted(by_digest.items())
        ],
        "claim_limit": CURRENT_HEAD_CLAIM_LIMIT,
    }
    return list(dict.fromkeys(errors)), summary


def _legacy_snapshot(config: dict[str, Any], current: dict[str, Any]) -> dict[str, Any] | None:
    value = current.get("legacy_snapshot_binding")
    if not isinstance(value, dict):
        legacy_digest = current.get("master_filter_expected_sha256")
        if not is_sha256(legacy_digest):
            return None
        value = {"expected_sha256": legacy_digest}
    digest = value.get("expected_sha256")
    if not is_sha256(digest):
        return None
    return {
        "schema_version": value.get("schema_version", "aoa_dashboard_legacy_snapshot_binding_v1"),
        "expected_sha256": digest,
        "snapshot_role": "historical_bootstrap_only",
        "claim_limit": LEGACY_SNAPSHOT_CLAIM_LIMIT,
    }


def _result(
    *,
    state: str,
    filter_snapshot: FileSnapshot,
    attestation_snapshot: FileSnapshot | None,
    history_snapshot: FileSnapshot | None,
    errors: list[str],
    head: dict[str, Any] | None,
    history: dict[str, Any],
    binding: dict[str, Any] | None,
    legacy_snapshot: dict[str, Any] | None,
    filter_ref: str,
    current_head_ref: str | None,
    history_ref: str | None,
) -> dict[str, Any]:
    diagnostics = list(dict.fromkeys(errors))
    refs: list[dict[str, Any]] = []
    if attestation_snapshot is not None:
        refs.append(_owner_ref(attestation_snapshot, label="master current-head attestation", kind="master_filter_current_head"))
    if history_snapshot is not None:
        refs.append(_owner_ref(history_snapshot, label="master current-head history", kind="master_filter_current_head_history"))
    provenance = {
        "owner": "master-thread",
        "authority": "master_decision",
        "access_scope": "owner_bounded",
        "filter_ref": filter_ref,
        "filter_sha256": filter_snapshot.digest,
        "current_head_ref": current_head_ref,
        "current_head_sha256": attestation_snapshot.digest if attestation_snapshot is not None else None,
        "history_ref": history_ref,
        "history_sha256": history_snapshot.digest if history_snapshot is not None else None,
        "claim_limit": CURRENTNESS_CLAIM_LIMIT,
    }
    return {
        "schema_version": CURRENTNESS_BINDING_SCHEMA_VERSION,
        "state": state,
        "owner": binding.get("owner") if isinstance(binding, dict) else "master-thread",
        "authority": binding.get("authority") if isinstance(binding, dict) else "master_decision",
        "access_scope": binding.get("access_scope") if isinstance(binding, dict) else "owner_bounded",
        "filter_ref": filter_ref,
        "current_head_ref": current_head_ref,
        "history_ref": history_ref,
        "head": _safe_head(head),
        "history": history,
        "provenance": provenance,
        "evidence_refs": refs,
        "degradation": diagnostics,
        "legacy_snapshot_binding": legacy_snapshot,
        "claim_limit": CURRENTNESS_CLAIM_LIMIT,
    }


def resolve_master_filter_currentness(
    config: dict[str, Any],
    current: dict[str, Any],
    filter_snapshot: FileSnapshot,
    *,
    expected_thread: str,
    expected_goal_ref: str,
    task_root: Path,
) -> dict[str, Any]:
    """Resolve the owner currentness contract without trusting a config digest."""

    binding = current.get("master_filter_currentness")
    legacy_snapshot = _legacy_snapshot(config, current)
    if not isinstance(binding, dict):
        return _result(
            state=filter_snapshot.currentness,
            filter_snapshot=filter_snapshot,
            attestation_snapshot=None,
            history_snapshot=None,
            errors=[],
            head=None,
            history={"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT},
            binding=None,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=None,
            history_ref=None,
        )

    binding_errors: list[str] = []
    if set(binding) != _BINDING_FIELDS or binding.get("schema_version") != CURRENTNESS_BINDING_SCHEMA_VERSION:
        binding_errors.append("current_head_schema_unsupported")
    if binding.get("owner") != "master-thread":
        binding_errors.append("current_head_authority_conflict")
    if binding.get("authority") != "master_decision" or binding.get("access_scope") != "owner_bounded":
        binding_errors.append("current_head_authority_conflict")
    if not _non_empty(binding.get("claim_limit")):
        binding_errors.append("current_head_authority_missing")

    root = task_root.resolve(strict=False)
    configured_filter = _canonical_path(binding.get("filter_ref"))
    current_head_path = _canonical_path(binding.get("current_head_ref"))
    history_path = _canonical_path(binding.get("history_ref"))
    if configured_filter is None or configured_filter != filter_snapshot.path or not _within(root, configured_filter):
        binding_errors.append("current_head_filter_ref_mismatch")
    if current_head_path is None or not _within(root, current_head_path):
        binding_errors.append("current_head_authority_missing")
    if history_path is None or not _within(root, history_path):
        binding_errors.append("current_head_authority_missing")
    if "master_filter_expected_sha256" in current:
        binding_errors.append("legacy_snapshot_pin_ignored")
    if binding_errors:
        return _result(
            state="invalid",
            filter_snapshot=filter_snapshot,
            attestation_snapshot=None,
            history_snapshot=None,
            errors=binding_errors,
            head=None,
            history={"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT},
            binding=binding,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=str(current_head_path) if current_head_path else None,
            history_ref=str(history_path) if history_path else None,
        )

    assert current_head_path is not None
    assert history_path is not None
    attestation_snapshot = read_file_snapshot(current_head_path, parser="json")
    history_snapshot = read_file_snapshot(history_path, parser="text")
    if filter_snapshot.currentness == "missing":
        return _result(
            state="missing",
            filter_snapshot=filter_snapshot,
            attestation_snapshot=attestation_snapshot,
            history_snapshot=history_snapshot,
            errors=["master_filter_missing"],
            head=None,
            history={"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT},
            binding=binding,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=str(current_head_path),
            history_ref=str(history_path),
        )
    if filter_snapshot.currentness == "invalid" or filter_snapshot.parsed is None:
        return _result(
            state="invalid",
            filter_snapshot=filter_snapshot,
            attestation_snapshot=attestation_snapshot,
            history_snapshot=history_snapshot,
            errors=["master_filter_unreadable"],
            head=None,
            history={"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT},
            binding=binding,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=str(current_head_path),
            history_ref=str(history_path),
        )
    if attestation_snapshot.currentness == "missing":
        return _result(
            state="missing",
            filter_snapshot=filter_snapshot,
            attestation_snapshot=attestation_snapshot,
            history_snapshot=history_snapshot,
            errors=["current_head_missing"],
            head=None,
            history={"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT},
            binding=binding,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=str(current_head_path),
            history_ref=str(history_path),
        )
    if attestation_snapshot.parse_error or attestation_snapshot.parsed is None:
        return _result(
            state="invalid",
            filter_snapshot=filter_snapshot,
            attestation_snapshot=attestation_snapshot,
            history_snapshot=history_snapshot,
            errors=["current_head_parse_failed"],
            head=None,
            history={"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT},
            binding=binding,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=str(current_head_path),
            history_ref=str(history_path),
        )
    attestation = attestation_snapshot.parsed
    head_errors = _validate_head_shape(
        attestation,
        expected_owner="master-thread",
        expected_thread=expected_thread,
        expected_goal_ref=expected_goal_ref,
        expected_filter_ref=str(filter_snapshot.path),
        expected_history_ref=str(history_path),
        schema_version=CURRENT_HEAD_SCHEMA_VERSION,
    )
    if isinstance(attestation, dict) and isinstance(attestation.get("heads"), list):
        head_errors.append("current_head_ambiguous")
    records, history_errors = _history_records(history_snapshot)
    head_errors.extend(history_errors)
    history_summary = {"record_count": None, "claim_limit": CURRENT_HEAD_CLAIM_LIMIT}
    if records:
        history_errors, history_summary = _validate_history(
            records,
            expected_owner="master-thread",
            expected_thread=expected_thread,
            expected_goal_ref=expected_goal_ref,
            expected_filter_ref=str(filter_snapshot.path),
            expected_history_ref=str(history_path),
        )
        head_errors.extend(history_errors)
    head = attestation if isinstance(attestation, dict) else None
    if head is not None and not head_errors:
        sequence = head["sequence"]
        digest = head["head_sha256"]
        by_sequence = {
            record["sequence"]: record["head_sha256"]
            for record in records
            if isinstance(record.get("sequence"), int) and is_sha256(record.get("head_sha256"))
        }
        if sequence not in by_sequence or by_sequence.get(sequence) != digest:
            head_errors.append("current_head_history_conflict")
        elif sequence != history_summary.get("last_sequence"):
            head_errors.append("current_head_rollback_detected")
        elif sequence == history_summary.get("first_sequence") and head.get("previous_head_sha256") is not None:
            head_errors.append("current_head_history_conflict")
        elif sequence != history_summary.get("first_sequence"):
            previous_digest = by_sequence.get(sequence - 1)
            if previous_digest != head.get("previous_head_sha256"):
                head_errors.append("current_head_history_conflict")
        prior_sequences = [
            sequence_value
            for digest_value, sequence_values in (
                (item["sha256"], item["sequences"]) for item in history_summary.get("head_digests", [])
            )
            if digest_value == digest
            for sequence_value in sequence_values
            if sequence_value != sequence
        ]
        if prior_sequences:
            if head.get("transition") != "rollback":
                head_errors.append("current_head_rollback_detected")
            elif not _non_empty(head.get("claim_limit")):
                head_errors.append("current_head_rollback_target_missing")
    if head is not None and filter_snapshot.digest != head.get("head_sha256"):
        return _result(
            state="stale" if not head_errors else "invalid",
            filter_snapshot=filter_snapshot,
            attestation_snapshot=attestation_snapshot,
            history_snapshot=history_snapshot,
            errors=[*head_errors, "current_head_digest_mismatch"],
            head=head,
            history=history_summary,
            binding=binding,
            legacy_snapshot=legacy_snapshot,
            filter_ref=str(filter_snapshot.path),
            current_head_ref=str(current_head_path),
            history_ref=str(history_path),
        )
    state = "current_at_read" if not head_errors else "invalid"
    if head is not None and head.get("transition") == "rollback" and state == "current_at_read":
        head_errors.append("current_head_rollback_attested")
    return _result(
        state=state,
        filter_snapshot=filter_snapshot,
        attestation_snapshot=attestation_snapshot,
        history_snapshot=history_snapshot,
        errors=head_errors,
        head=head,
        history=history_summary,
        binding=binding,
        legacy_snapshot=legacy_snapshot,
        filter_ref=str(filter_snapshot.path),
        current_head_ref=str(current_head_path),
        history_ref=str(history_path),
    )


def filter_currentness_for_ref(observation: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    """Map protocol state to source-ref quality without claiming owner truth."""

    state = observation.get("state")
    if state == "current_at_read":
        return "current_at_read", [], []
    if state == "stale":
        return "stale", list(observation.get("degradation", [])), ["currentness_attestation"]
    if state == "missing":
        return "deferred", list(observation.get("degradation", [])), ["currentness_attestation"]
    if state == "deferred":
        return "deferred", list(observation.get("degradation", [])), ["currentness_attestation"]
    if state == "invalid":
        return "invalid", list(observation.get("degradation", [])), []
    if state in {"current", "unknown"}:
        return state, list(observation.get("degradation", [])), []
    return "unknown", ["current_head_authority_missing"], ["currentness_attestation"]
