from __future__ import annotations

from typing import Literal, TypedDict


LifecycleState = Literal[
    "planned",
    "bound",
    "running",
    "paused",
    "returned",
    "reviewed",
    "accepted",
    "wake requested",
    "reentered",
]
ObservationQuality = Literal["missing", "unknown", "stale", "deferred", "invalid"]
Status = LifecycleState | ObservationQuality

LIFECYCLE_STATES: tuple[str, ...] = (
    "planned",
    "bound",
    "running",
    "paused",
    "returned",
    "reviewed",
    "accepted",
    "wake requested",
    "reentered",
)
OBSERVATION_QUALITY: tuple[str, ...] = (
    "missing",
    "unknown",
    "stale",
    "deferred",
    "invalid",
)
STATUS_VOCABULARY: tuple[str, ...] = LIFECYCLE_STATES + OBSERVATION_QUALITY


class EvidenceRef(TypedDict, total=False):
    label: str
    kind: str
    ref: str
    path: str
    claim_limit: str


class StatusItem(TypedDict, total=False):
    step: str
    state: str
    observation: str
    evidence_refs: list[EvidenceRef]
    claim_limit: str


class SourceObservation(TypedDict, total=False):
    id: str
    owner: str
    state: str
    freshness: str
    degradation: list[str]
    runtime_state: str
    publisher_status: str
    observation: str
    metadata: dict[str, object]
    evidence_refs: list[EvidenceRef]
    claim_limit: str


class Projection(TypedDict, total=False):
    schema_version: str
    generated_at: str
    presentation: dict[str, object]
    goal: dict[str, object]
    owner_goal_context: dict[str, object]
    participant_context: dict[str, object]
    correlation: dict[str, object]
    correlation_read_model: dict[str, object]
    pressure_inbox: dict[str, object]
    actor_activity: dict[str, object]
    current_holder: dict[str, object]
    dag: list[dict[str, object]]
    lifecycle: list[StatusItem]
    state_inventory: list[dict[str, object]]
    sources: list[SourceObservation]
    owner_surfaces: list[dict[str, object]]
    annotations: dict[str, object]
    action_intents: dict[str, object]
    claim_limits: list[str]


def is_lifecycle(value: str) -> bool:
    return value in LIFECYCLE_STATES


def is_quality(value: str) -> bool:
    return value in OBSERVATION_QUALITY
