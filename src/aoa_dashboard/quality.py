"""Shared quality normalization for owner-derived dashboard projections.

The dashboard owns projections, not the meaning of the upstream sources.  This
module only keeps the observable quality vocabulary stable while a derived
surface combines independently owned observations.
"""

from __future__ import annotations

from typing import Any


QUALITY_STATES = frozenset({"present", "missing", "unknown", "stale", "deferred", "invalid"})
_PRESENT_ALIASES = frozenset({"observed", "bound", "current", "current_at_read", "reentered", "returned"})
_INVALID_REASON_PREFIXES = ("owner_goal_", "owner_thread_", "owner_schema_")


def normalize_quality_state(value: Any, fallback: str = "unknown") -> str:
    """Map source/lifecycle labels into the participant quality vocabulary."""

    if value in _PRESENT_ALIASES:
        return "present"
    if isinstance(value, str) and value in QUALITY_STATES:
        return value
    return fallback if fallback in QUALITY_STATES else "unknown"


def normalize_freshness(value: Any, fallback: str = "unknown") -> str:
    """Normalize a source freshness/currentness value without inventing data."""

    if value in _PRESENT_ALIASES:
        return "current_at_read"
    if isinstance(value, str) and value in QUALITY_STATES:
        return value
    return fallback if fallback in QUALITY_STATES or fallback == "current_at_read" else "unknown"


def combine_freshness(*values: Any, fallback: str = "unknown") -> str:
    """Retain the strongest observable invalidity or bounded staleness."""

    normalized = [normalize_freshness(value) for value in values if value is not None]
    if not normalized:
        return normalize_freshness(fallback, fallback=fallback)
    for state in ("invalid", "stale", "deferred", "unknown", "missing"):
        if state in normalized:
            return state
    return "current_at_read"


def strongest_degradation(*values: Any) -> str | None:
    """Return only the inherited invalid/stale quality that must propagate."""

    normalized = [normalize_quality_state(value) for value in values if value is not None]
    if "invalid" in normalized:
        return "invalid"
    if "stale" in normalized:
        return "stale"
    return None


def propagate_quality_state(base: Any, *inherited: Any) -> str:
    """Apply inherited invalidity/staleness without erasing missing/unknown."""

    state = normalize_quality_state(base)
    degradation = strongest_degradation(*inherited)
    if degradation == "invalid":
        return "invalid"
    if degradation == "stale" and state == "present":
        return "stale"
    return state


def combine_quality_states(
    *values: Any,
    all_missing: str = "deferred",
    stale_with_missing: bool = False,
) -> str:
    """Combine dimensions while retaining the existing mixed-quality contract."""

    normalized = [normalize_quality_state(value) for value in values]
    if not normalized:
        return "unknown"
    if "invalid" in normalized:
        return "invalid"
    if all(value == "missing" for value in normalized):
        return all_missing
    if "stale" in normalized and (
        all(value == "stale" for value in normalized)
        or (stale_with_missing and all(value in {"stale", "missing"} for value in normalized))
    ):
        return "stale"
    if any(value in {"missing", "unknown", "deferred", "stale"} for value in normalized):
        return "deferred"
    return "present"


def state_for_owner_error(reason: Any) -> str:
    """Classify canonical owner-shape failures separately from transport absence."""

    if isinstance(reason, str) and (
        reason.startswith(_INVALID_REASON_PREFIXES)
        or reason == "owner_method_failed:thread/goal/get"
    ):
        return "invalid"
    return "unknown"
