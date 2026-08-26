"""Shared content-addressed source snapshots and admission registries."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


KNOWN_CURRENTNESS = frozenset({"current", "current_at_read", "stale", "deferred", "missing", "unknown", "invalid"})
KNOWN_OWNERS = frozenset(
    {
        "aoa-agents",
        "aoa-dashboard",
        "aoa-evals",
        "aoa-kag",
        "aoa-memo",
        "aoa-session-memory",
        "aoa-sdk",
        "aoa-skills",
        "aoa-stats",
        "abyss-stack",
        "different-owner",
        "goal-anchor",
        "master-thread",
        "task-local-runtime",
        "test-owner",
        "test-owner-alt",
    }
)
KNOWN_CLAIM_POLICIES = frozenset(
    {
        "actor_return_metadata",
        "dashboard_derived_read_model",
        "deferred_legacy_redaction",
        "derived_navigation",
        "derived_stats",
        "historical_context",
        "master_decision_disposition",
        "runtime_binding",
        "source_owner_metadata",
        "test_metadata",
    }
)

DIAGNOSTIC_DIGEST_PREFIX = "diagnostic_digest:"
DIAGNOSTIC_INVALID_TYPE = "diagnostic_invalid_type"
MAX_DIAGNOSTIC_ITEMS = 64
MAX_DIAGNOSTIC_VALUE_LENGTH = 96
KNOWN_DIAGNOSTIC_CODES = frozenset(
    {
        "source_missing",
        "source_read_failed",
        "source_parse_failed",
        "expected_digest_mismatch",
        "legacy_snapshot_pin_ignored",
        "historical_bootstrap_only",
        "current_head_missing",
        "current_head_parse_failed",
        "current_head_schema_unsupported",
        "current_head_authority_missing",
        "current_head_authority_conflict",
        "current_head_filter_ref_mismatch",
        "current_head_digest_mismatch",
        "current_head_history_missing",
        "current_head_history_invalid",
        "current_head_history_conflict",
        "current_head_ambiguous",
        "current_head_rollback_detected",
        "current_head_rollback_attested",
        "current_head_rollback_target_missing",
        "current_head_sequence_invalid",
        "bytes",
        "digest",
        "parse_result",
        "currentness_attestation",
        "current",
        "current_at_read",
        "stale",
        "deferred",
        "missing",
        "unknown",
        "invalid",
        "task_local_binding_not_directory",
        "master_filter_missing",
        "master_filter_unreadable",
        "goal_anchor_missing",
        "goal_anchor_stale",
        "master_filter_stale",
        "duplicate_wake_receipts",
        "unfiltered_handoff_candidate",
        "unfiltered_wake_receipt",
        "metadata_admission_rejected",
        "correlation_envelope_not_object",
        "legacy_master_filter_ref_not_admitted_with_explicit_access_and_authority",
        "legacy_master_filter_metadata_admission_rejected",
        "correlation_envelope_metadata_admission_rejected",
        "pressure_inbox_records_not_a_list",
        "pressure_record_invalid",
        "legacy_candidate_invalid",
        "legacy_master_filter",
        "legacy_master_filter_requires_structured_pressure_fields",
        "non_string_object_key",
        "diagnostic_invalid_type",
        "separate_holder",
        "independent_holder",
        "separate_pressure_concern",
        "critical_route_master_filter",
        "configured_snapshot",
        "derived_pressure_identity",
        "live_observed",
        "directory_binding",
        "missing_binding",
        "derived_binding",
        "test_fixture",
        "affected_goal_criterion",
        "consequence_of_omission",
        "natural_owner",
        "checked_existing_surfaces",
        "independence_signals",
        "recommended_trigger_strength",
        "stop_line",
        "wake_condition",
        "next_route",
        "outcome",
        "ref",
        "sha256",
        "owner",
        "kind",
        "currentness",
        "access_scope",
        "authority",
        "claim_policy",
        "snapshot_role",
        "claim_limit",
    }
)

ClaimParser = Literal["json", "text"]


class DuplicateJsonObjectNameError(ValueError):
    """Raised when one JSON object contains the same member name twice."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"duplicate JSON object name: {name}")


def _reject_duplicate_object_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise DuplicateJsonObjectNameError(name)
        result[name] = value
    return result


def loads_json(value: str, *, reject_duplicate_keys: bool = False) -> Any:
    """Parse JSON with an optional fail-closed duplicate-member policy."""

    object_pairs_hook = _reject_duplicate_object_names if reject_duplicate_keys else None
    return json.loads(value, object_pairs_hook=object_pairs_hook)


def _normalized_parse_error(exc: Exception) -> str:
    """Return a bounded parse diagnostic without retaining source content."""

    if isinstance(exc, DuplicateJsonObjectNameError):
        return "duplicate JSON object name"
    if isinstance(exc, UnicodeError):
        return "source is not valid UTF-8"
    if isinstance(exc, json.JSONDecodeError):
        return f"invalid JSON document at line {exc.lineno}, column {exc.colno}"
    return "structured source parse failed"


def is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def is_known_owner(value: Any) -> bool:
    return isinstance(value, str) and value in KNOWN_OWNERS


def is_known_claim_policy(value: Any) -> bool:
    return isinstance(value, str) and value in KNOWN_CLAIM_POLICIES


def is_diagnostic_digest(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(DIAGNOSTIC_DIGEST_PREFIX):
        return False
    digest = value[len(DIAGNOSTIC_DIGEST_PREFIX) :]
    return len(value) <= MAX_DIAGNOSTIC_VALUE_LENGTH and is_sha256(digest) and digest == digest.lower()


def is_safe_diagnostic(value: Any) -> bool:
    return isinstance(value, str) and (
        value in KNOWN_DIAGNOSTIC_CODES or is_diagnostic_digest(value)
    )


def safe_diagnostic(value: Any) -> str:
    """Keep known codes and replace every other value with a digest-only code."""

    if is_safe_diagnostic(value):
        return value
    if not isinstance(value, str):
        return DIAGNOSTIC_INVALID_TYPE
    return f"{DIAGNOSTIC_DIGEST_PREFIX}{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def sanitize_diagnostic_list(value: Any) -> Any:
    """Sanitize diagnostic list members without making malformed structure valid."""

    if not isinstance(value, list):
        return value
    return [safe_diagnostic(item) if isinstance(item, str) else item for item in value]


_CONFUSABLES = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "і": "i",
        "о": "o",
        "р": "p",
        "с": "c",
        "т": "t",
        "у": "y",
        "х": "x",
        "Α": "a",
        "Β": "b",
        "Ε": "e",
        "Ι": "i",
        "Κ": "k",
        "Μ": "m",
        "Ν": "n",
        "Ο": "o",
        "Ρ": "p",
        "Τ": "t",
        "Χ": "x",
        "ρ": "p",
        "ϱ": "p",
        "ѕ": "s",
        "օ": "o",
        "ӏ": "l",
        "һ": "h",
    }
)


def key_skeleton(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().translate(_CONFUSABLES)


def has_forbidden_key(value: Any, forbidden_parts: tuple[str, ...]) -> bool:
    if not isinstance(value, str):
        return True
    skeleton = key_skeleton(value)
    return any(part in skeleton for part in forbidden_parts)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FileSnapshot:
    """One bytes/digest/parse/currentness decision for one source read."""

    path: Path
    raw_bytes: bytes | None
    digest: str | None
    parsed: Any
    currentness: str
    expected_digest: str | None
    parse_error: str | None
    read_error: str | None
    observed_at: str | None

    @property
    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if self.raw_bytes is None:
            missing.append("bytes")
        if self.digest is None:
            missing.append("digest")
        if self.parsed is None:
            missing.append("parse_result")
        if self.currentness in {"stale", "unknown", "invalid"} and self.expected_digest is not None:
            missing.append("currentness_attestation")
        return missing


def read_file_snapshot(
    path: str | Path,
    *,
    expected_digest: str | None = None,
    parser: ClaimParser = "json",
    reject_duplicate_keys: bool = True,
) -> FileSnapshot:
    """Read, hash, and parse one source with fail-closed JSON admission."""

    source = Path(path).resolve(strict=False)
    observed_at = utc_now()
    if expected_digest is not None and not is_sha256(expected_digest):
        expected_error = "configured expected digest is malformed"
    else:
        expected_error = None
    try:
        raw = source.read_bytes()
    except FileNotFoundError:
        return FileSnapshot(source, None, None, None, "missing", expected_digest, expected_error, "source is absent", observed_at)
    except (OSError, UnicodeError) as exc:
        return FileSnapshot(source, None, None, None, "invalid", expected_digest, expected_error, str(exc), observed_at)

    digest = hashlib.sha256(raw).hexdigest()
    parsed: Any = None
    parse_error: str | None = None
    try:
        text = raw.decode("utf-8")
        parsed = loads_json(text, reject_duplicate_keys=reject_duplicate_keys) if parser == "json" else text
        if parser == "json" and not isinstance(parsed, dict):
            parse_error = "top-level JSON value is not an object"
            parsed = None
    except (UnicodeError, ValueError) as exc:
        parse_error = _normalized_parse_error(exc)

    if expected_error or parse_error:
        currentness = "invalid"
    elif expected_digest is not None and digest != expected_digest:
        currentness = "stale"
    else:
        currentness = "current_at_read"
    return FileSnapshot(source, raw, digest, parsed, currentness, expected_digest, parse_error, None, observed_at)


def snapshot_ref(
    snapshot: FileSnapshot,
    *,
    label: str,
    kind: str,
    owner: str,
    access_scope: str,
    authority: str,
    claim_policy: str,
    claim_limit: str,
    snapshot_role: str = "live_observed",
    observed_at: str | None = None,
    currentness_override: str | None = None,
    freshness_override: str | None = None,
    extra_degradation: list[str] | None = None,
    extra_missing_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Create a rich typed ref without rereading or relabelling the source."""

    degradation: list[str] = []
    if snapshot.read_error:
        degradation.append("source_read_failed")
    if snapshot.parse_error:
        degradation.append("source_parse_failed")
    if snapshot.expected_digest is not None and snapshot.digest != snapshot.expected_digest:
        degradation.append("expected_digest_mismatch")
    if snapshot.currentness == "missing":
        degradation.append("source_missing")
    degradation.extend(extra_degradation or [])
    currentness = currentness_override or snapshot.currentness
    freshness = freshness_override or currentness
    result: dict[str, Any] = {
        "label": label,
        "kind": kind,
        "ref": str(snapshot.path),
        "sha256": snapshot.digest,
        "currentness": currentness,
        "freshness": freshness,
        "owner": owner,
        "access_scope": access_scope,
        "authority": authority,
        "claim_policy": claim_policy,
        "claim_limit": claim_limit,
        "degradation": degradation,
        "snapshot_role": snapshot_role,
        "observed_at": observed_at or snapshot.observed_at,
    }
    if snapshot.expected_digest is not None:
        result["expected_sha256"] = snapshot.expected_digest
    missing_fields = [*snapshot.missing_fields, *(extra_missing_fields or [])]
    if missing_fields:
        result["missing_fields"] = list(dict.fromkeys(missing_fields))
    return result
