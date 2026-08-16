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

ClaimParser = Literal["json", "text"]


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
) -> FileSnapshot:
    """Read bytes once, hash those bytes, parse those bytes, then decide currentness."""

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
        parsed = json.loads(text) if parser == "json" else text
        if parser == "json" and not isinstance(parsed, dict):
            parse_error = "top-level JSON value is not an object"
            parsed = None
    except (UnicodeError, json.JSONDecodeError) as exc:
        parse_error = str(exc)

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
    result: dict[str, Any] = {
        "label": label,
        "kind": kind,
        "ref": str(snapshot.path),
        "sha256": snapshot.digest,
        "currentness": snapshot.currentness,
        "freshness": snapshot.currentness,
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
    if snapshot.missing_fields:
        result["missing_fields"] = list(snapshot.missing_fields)
    return result
