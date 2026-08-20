#!/usr/bin/env python3
"""Validate the source-owned aoa-dashboard organ contract and route surfaces."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "organ_contract.json"


class ContractError(RuntimeError):
    """Raised when a required organ-contract invariant is absent."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def main() -> int:
    try:
        payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {CONTRACT_PATH}: {exc}") from exc

    require(isinstance(payload, dict), "organ contract must be an object")
    require(payload.get("schema_version") == "aoa_dashboard_organ_contract_v1", "unsupported schema version")
    require(payload.get("organ_id") == "aoa-dashboard", "organ_id must be aoa-dashboard")

    repository = payload.get("repository")
    require(isinstance(repository, dict), "repository identity is required")
    require(
        repository.get("canonical_remote") == "https://github.com/8Dionysus/aoa-dashboard",
        "canonical GitHub remote is not exact",
    )
    require(repository.get("visibility") == "public", "repository visibility must be public")
    require(repository.get("maturity") == "bootstrap", "organ maturity must remain bootstrap")
    require(
        repository.get("admission_state") == "declared_not_admitted",
        "source identity must not imply admission",
    )

    boundary = payload.get("constitutional_boundary")
    require(isinstance(boundary, dict), "constitutional boundary is required")
    owned = set(boundary.get("owns", []))
    require(
        {
            "aoa_dashboard_projection_v1",
            "dashboard_annotation_v1",
            "action_intent_v1",
            "goal_local_correlation_projection_v1",
            "goal_local_cursor_v1",
            "pressure_inbox_v1",
            "task_local_actor_activity_projection_v1",
        }.issubset(owned),
        "owned surface set is incomplete",
    )
    excluded = set(boundary.get("does_not_own", []))
    require(
        {
            "roles_mandates_responsibility_returns_or_wakes",
            "capability_abi_or_task_local_dag",
            "runplan_or_incarnation_selection",
            "runtime_deployment_or_process_lifecycle",
            "proof_review_or_eval_verdicts",
            "durable_memory_meaning_or_retention",
            "actor_creation_master_wake_or_action_execution",
        }.issubset(excluded),
        "authority exclusions are incomplete",
    )

    routes = payload.get("owner_routes")
    require(isinstance(routes, dict), "owner routes are required")
    for owner in (
        "aoa-agents",
        "aoa-skills",
        "aoa-sdk",
        "abyss-stack",
        ".aoa-session-memory",
        "aoa-evals",
        "aoa-memo",
        "aoa-stats",
        "aoa-kag",
    ):
        require(owner in routes, f"missing owner route: {owner}")

    admission = payload.get("private_admission")
    require(isinstance(admission, dict), "private admission route is required")
    require(admission.get("access_plane") == "none", "dashboard access plane must be none")
    require(admission.get("current_state") == "no_record_by_design", "registry state must remain absent by design")
    require(admission.get("default_admission") == "deny", "admission must default to deny")
    require(admission.get("registry_schema") == "aoa_organ_registry_source_v2", "v2 registry route is required")
    require(len(admission.get("future_route", [])) >= 5, "future admission route is incomplete")

    required_surfaces = payload.get("required_surfaces")
    require(isinstance(required_surfaces, list), "required surfaces are required")
    for relative in required_surfaces:
        require((ROOT / relative).is_file(), f"required surface is missing: {relative}")

    validation = payload.get("validation")
    require(isinstance(validation, dict), "validation route is required")
    require(validation.get("required_check_name") == "Repo Validation", "required CI check name is not exact")
    require((ROOT / str(validation.get("ci_workflow"))).is_file(), "CI workflow is missing")

    handoff = payload.get("handoff")
    require(isinstance(handoff, dict), "handoff route is required")
    require(handoff.get("return_owner") == "holder:aoa-dashboard-master-sol", "return owner is not exact")
    require(handoff.get("master_thread_id") == "01a00722-0291-72e0-8310-559da802d6e1", "master thread is not exact")

    print(f"[ok] validated {CONTRACT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ContractError as exc:
        print(f"[error] {exc}")
        raise SystemExit(1) from exc
