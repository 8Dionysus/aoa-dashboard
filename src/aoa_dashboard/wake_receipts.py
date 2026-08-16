"""Versioned wake-receipt intake helpers owned by the dashboard adapter.

The dashboard consumes two deliberately different receipt families:

* ``task_local_actor_wake_receipt_v2`` is the existing task-local witness;
* ``aoa_codex_wake_receipt_v1`` is the runtime-neutral ``aoa-sdk`` owner
  contract.

This module validates only the bounded fields needed for a derived
correlation.  It never selects a route, controls a runtime, filters a return,
or turns transport delivery into semantic continuation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION = "task_local_actor_wake_receipt_v2"
CODEX_WAKE_RECEIPT_SCHEMA_VERSION = "aoa_codex_wake_receipt_v1"
WAKE_RECEIPT_ADAPTER_VERSION = "aoa_dashboard_wake_receipt_compat_v1"
CODEX_WAKE_OWNER_REPO = "aoa-sdk"
CODEX_WAKE_OWNER_REF = "d574ffea1f9dbe2aa08ca83a106be72996584934"
CODEX_WAKE_OWNER_CONTRACT_REF = (
    "aoa-sdk@d574ffea1f9dbe2aa08ca83a106be72996584934:"
    "src/aoa_sdk/runtime_adapters/codex_wake.py"
)
CODEX_WAKE_OWNER_AUTHORITY = "aoa-sdk:runtime-neutral Codex wake receipt contract"

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
_SHA256_TOKEN = re.compile(r"^sha256:([0-9a-f]{64})$")

_CODEX_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "master_thread_id",
        "handoff_ref",
        "handoff_sha256",
        "attempted_at",
        "generated_at",
        "route",
        "stage",
        "delivery_route",
        "client_user_message_id",
        "accepted_turn_id",
        "attempts",
        "before",
        "after",
        "outcome",
        "responsibility_state",
        "failure",
    }
)
_CODEX_RECEIPT_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "request_id",
        "master_thread_id",
        "handoff_ref",
        "handoff_sha256",
        "attempted_at",
        "generated_at",
        "route",
        "stage",
        "attempts",
        "before",
        "after",
        "outcome",
        "responsibility_state",
    }
)
_CODEX_FAILURE_FIELDS = frozenset({"stage", "error_type", "message"})
_CODEX_FAILURE_REQUIRED_FIELDS = _CODEX_FAILURE_FIELDS
_CODEX_ROUTES = frozenset({"app_server_remote_control", "tui_fallback", "none"})
_CODEX_OUTCOMES = frozenset(
    {"handoff_delivered_pending_master_filter", "wake_failed_with_receipt"}
)
_CODEX_RESPONSIBILITY_STATES = frozenset(
    {"delivered_to_master_pending_master_filter", "return_ready_wake_failed"}
)


def is_sha256_hex(value: Any) -> bool:
    """Return whether *value* is an unprefixed lowercase SHA-256 hex digest."""

    return isinstance(value, str) and _SHA256_HEX.fullmatch(value) is not None


def normalize_handoff_sha256(value: Any, *, schema_version: Any) -> str | None:
    """Normalize an owner handoff digest only under its explicit schema.

    ``aoa_codex_wake_receipt_v1`` owns the prefixed ``sha256:<hex>`` form.
    The task-local v2 witness owns the historical bare-hex form.  No other
    schema receives an implicit prefix strip or other digest coercion.
    """

    if schema_version == CODEX_WAKE_RECEIPT_SCHEMA_VERSION:
        match = _SHA256_TOKEN.fullmatch(value) if isinstance(value, str) else None
        return match.group(1) if match else None
    if schema_version == TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION:
        return value if is_sha256_hex(value) else None
    return None


def wake_source_family(schema_version: Any) -> str:
    if schema_version == CODEX_WAKE_RECEIPT_SCHEMA_VERSION:
        return "owner_runtime_neutral"
    if schema_version == TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION:
        return "task_local"
    return "unsupported"


def wake_source_kind(schema_version: Any) -> str:
    if schema_version == CODEX_WAKE_RECEIPT_SCHEMA_VERSION:
        return "aoa_sdk_codex_wake_receipt_v1"
    if schema_version == TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION:
        return "task_local_wake_receipt_v2"
    return "unsupported_wake_receipt"


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_string(value: Any) -> bool:
    return value is None or _non_empty_string(value)


def _bounded_string(value: Any, *, maximum: int, label: str, errors: list[str]) -> None:
    if isinstance(value, str) and len(value) > maximum:
        errors.append(f"codex v1 wake receipt {label} exceeds {maximum} characters")


def _validate_failure(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("codex v1 failure is not an object")
        return
    extra = sorted(set(value) - _CODEX_FAILURE_FIELDS)
    missing = sorted(_CODEX_FAILURE_REQUIRED_FIELDS - set(value))
    if extra:
        errors.append("codex v1 failure has unsupported fields: " + ", ".join(extra))
    if missing:
        errors.append("codex v1 failure is missing fields: " + ", ".join(missing))
    for field in _CODEX_FAILURE_FIELDS:
        if field in value and not _non_empty_string(value[field]):
            errors.append(f"codex v1 failure {field} is missing")
    _bounded_string(value.get("stage"), maximum=256, label="failure.stage", errors=errors)
    _bounded_string(value.get("error_type"), maximum=256, label="failure.error_type", errors=errors)
    _bounded_string(value.get("message"), maximum=2048, label="failure.message", errors=errors)


def validate_codex_wake_receipt_v1(value: Any) -> list[str]:
    """Validate the strict, source-shaped v1 receipt without importing SDK code."""

    errors: list[str] = []
    if not isinstance(value, dict):
        return ["codex v1 wake receipt is not an object"]

    extra = sorted(set(value) - _CODEX_RECEIPT_FIELDS)
    missing = sorted(_CODEX_RECEIPT_REQUIRED_FIELDS - set(value))
    if extra:
        errors.append("codex v1 wake receipt has unsupported fields: " + ", ".join(extra))
    if missing:
        errors.append("codex v1 wake receipt is missing fields: " + ", ".join(missing))

    for field in (
        "schema_version",
        "request_id",
        "master_thread_id",
        "handoff_ref",
        "attempted_at",
        "generated_at",
        "stage",
    ):
        if field in value and not _non_empty_string(value[field]):
            errors.append(f"codex v1 wake receipt {field} is missing")
    _bounded_string(value.get("request_id"), maximum=256, label="request_id", errors=errors)
    _bounded_string(value.get("master_thread_id"), maximum=256, label="master_thread_id", errors=errors)
    _bounded_string(value.get("handoff_ref"), maximum=4096, label="handoff_ref", errors=errors)
    _bounded_string(value.get("attempted_at"), maximum=128, label="attempted_at", errors=errors)
    _bounded_string(value.get("generated_at"), maximum=128, label="generated_at", errors=errors)
    _bounded_string(value.get("stage"), maximum=256, label="stage", errors=errors)
    if _non_empty_string(value.get("handoff_ref")) and not Path(value["handoff_ref"]).is_absolute():
        errors.append("codex v1 wake receipt handoff_ref is not absolute")
    if value.get("schema_version") != CODEX_WAKE_RECEIPT_SCHEMA_VERSION:
        errors.append("codex v1 wake receipt schema_version is unsupported")
    if "handoff_sha256" in value and normalize_handoff_sha256(
        value.get("handoff_sha256"), schema_version=CODEX_WAKE_RECEIPT_SCHEMA_VERSION
    ) is None:
        errors.append("codex v1 wake receipt handoff_sha256 is not sha256:<hex>")
    if value.get("route") not in _CODEX_ROUTES:
        errors.append("codex v1 wake receipt route is not admitted")
    if value.get("attempts") is not None and (
        isinstance(value.get("attempts"), bool)
        or not isinstance(value.get("attempts"), int)
        or not 0 <= value.get("attempts") <= 3
    ):
        errors.append("codex v1 wake receipt attempts is outside 0..3")
    if not isinstance(value.get("before"), dict):
        errors.append("codex v1 wake receipt before is not an object")
    if not isinstance(value.get("after"), dict):
        errors.append("codex v1 wake receipt after is not an object")
    for field in ("delivery_route", "client_user_message_id", "accepted_turn_id"):
        if field in value and not _optional_string(value[field]):
            errors.append(f"codex v1 wake receipt {field} is invalid")
    _bounded_string(value.get("delivery_route"), maximum=128, label="delivery_route", errors=errors)
    _bounded_string(value.get("client_user_message_id"), maximum=256, label="client_user_message_id", errors=errors)
    _bounded_string(value.get("accepted_turn_id"), maximum=256, label="accepted_turn_id", errors=errors)

    outcome = value.get("outcome")
    if outcome not in _CODEX_OUTCOMES:
        errors.append("codex v1 wake receipt outcome is not admitted")
    responsibility_state = value.get("responsibility_state")
    if responsibility_state not in _CODEX_RESPONSIBILITY_STATES:
        errors.append("codex v1 wake receipt responsibility_state is not admitted")
    if outcome == "handoff_delivered_pending_master_filter":
        if value.get("failure") is not None:
            errors.append("codex v1 success receipt cannot contain failure")
        if not _non_empty_string(value.get("accepted_turn_id")):
            errors.append("codex v1 success receipt must contain accepted_turn_id")
        if responsibility_state != "delivered_to_master_pending_master_filter":
            errors.append("codex v1 success receipt has an invalid responsibility_state")
    elif outcome == "wake_failed_with_receipt":
        if value.get("failure") is None:
            errors.append("codex v1 failure receipt must contain failure")
        else:
            _validate_failure(value.get("failure"), errors)
        if responsibility_state != "return_ready_wake_failed":
            errors.append("codex v1 failure receipt has an invalid responsibility_state")
    elif value.get("failure") is not None:
        _validate_failure(value.get("failure"), errors)

    return errors


def make_wake_provenance(
    *,
    schema_version: Any,
    raw_ref: str | None,
    raw_content_sha256: str | None,
    freshness: str,
    missingness: str,
    owner_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build source/provenance metadata without copying a receipt body."""

    if schema_version == CODEX_WAKE_RECEIPT_SCHEMA_VERSION:
        contract = owner_contract or {}
        owner_repo = contract.get("owner_repo") or CODEX_WAKE_OWNER_REPO
        owner_ref = contract.get("owner_ref") or CODEX_WAKE_OWNER_REF
        contract_ref = contract.get("contract_ref") or CODEX_WAKE_OWNER_CONTRACT_REF
        source_authority = contract.get("authority") or CODEX_WAKE_OWNER_AUTHORITY
    elif schema_version == TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION:
        owner_repo = "task-local producer"
        owner_ref = TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION
        contract_ref = "task_local_actor_wake_receipt_v2"
        source_authority = "task-local producer: wake delivery witness"
    else:
        owner_repo = "unresolved"
        owner_ref = None
        contract_ref = None
        source_authority = "unsupported wake receipt source"

    return {
        "owner_repo": owner_repo,
        "owner_ref": owner_ref,
        "contract_ref": contract_ref,
        "source_schema_version": schema_version,
        "source_family": wake_source_family(schema_version),
        "adapter_version": WAKE_RECEIPT_ADAPTER_VERSION,
        "raw_owner_ref": raw_ref,
        "raw_owner_content_sha256": raw_content_sha256,
        "raw_owner_content_digest": (
            f"sha256:{raw_content_sha256}" if is_sha256_hex(raw_content_sha256) else None
        ),
        "freshness": freshness,
        "missingness": missingness,
        "authority": source_authority,
        "claim_limit": (
            "Provenance identifies the observed source and adapter only; it does not "
            "grant the dashboard runtime, return, acceptance, or semantic authority."
        ),
    }


__all__ = [
    "CODEX_WAKE_OWNER_AUTHORITY",
    "CODEX_WAKE_OWNER_CONTRACT_REF",
    "CODEX_WAKE_OWNER_REF",
    "CODEX_WAKE_OWNER_REPO",
    "CODEX_WAKE_RECEIPT_SCHEMA_VERSION",
    "TASK_LOCAL_WAKE_RECEIPT_SCHEMA_VERSION",
    "WAKE_RECEIPT_ADAPTER_VERSION",
    "is_sha256_hex",
    "make_wake_provenance",
    "normalize_handoff_sha256",
    "validate_codex_wake_receipt_v1",
    "wake_source_family",
    "wake_source_kind",
]
