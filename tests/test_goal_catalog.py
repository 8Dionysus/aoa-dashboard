from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.goal_catalog import observe_goal_catalog


def owner_payload() -> dict:
    return {
        "schema_version": "aoa_session_memory_goal_catalog_v1",
        "artifact_type": "goal_catalog_projection",
        "generated_at": "2026-08-23T00:00:00Z",
        "ok": True,
        "state": "stale",
        "currentness": "stale",
        "source": {
            "owner": "aoa-session-memory",
            "ref": "aoa-session-memory:goal-lifecycles",
            "goal_lifecycle_schema_version": 3,
            "generation_identity": {"generation_id": "generation-1"},
            "currentness": "stale",
        },
        "source_item_count": 2,
        "item_count": 2,
        "items": [
            {
                "goal_ref": "goal-current",
                "goal_instance_id": "session-1:goal-0001",
                "goal_id": "goal-0001",
                "thread_id": "goal-current",
                "title": "Собрать спокойное пространство целей",
                "title_state": "available",
                "reason": None,
                "lifecycle_state": "active",
                "first_observed_at": "2026-08-22T18:00:00Z",
                "last_observed_at": "2026-08-22T21:00:00Z",
                "evidence_ref": "goal-lifecycle:session-1:goal-0001",
                "ambiguity": False,
            },
            {
                "goal_ref": "goal-private",
                "goal_instance_id": "session-2:goal-0001",
                "goal_id": "goal-0001",
                "thread_id": "goal-private",
                "title": None,
                "title_state": "withheld",
                "reason": "machine_shaped_objective",
                "lifecycle_state": "complete",
                "first_observed_at": None,
                "last_observed_at": None,
                "evidence_ref": "goal-lifecycle:session-2:goal-0001",
                "ambiguity": True,
            },
        ],
        "counts_by_lifecycle_state": {"active": 1, "complete": 1},
        "diagnostics": ["goal_lifecycle_source_generation_incompatible"],
        "omissions": {"objective": True, "raw_session_body": True, "usage": True, "work_chain": True, "host_paths": True},
        "claim_limit": "Scope: bounded generated Goal navigation.",
    }


def write_source(tmp_path: Path, payload: dict) -> dict:
    path = tmp_path / "goal-catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return {"goal_catalog_source": {"path": str(path)}}


def test_owner_catalog_is_normalized_and_keeps_degradation(tmp_path: Path) -> None:
    result = observe_goal_catalog(write_source(tmp_path, owner_payload()))
    assert result["schema_version"] == "aoa_dashboard_goal_catalog_projection_v1"
    assert result["state"] == "stale"
    assert result["source"] == {
        "owner": "aoa-session-memory",
        "ref": "aoa-session-memory:goal-lifecycles",
        "owner_schema_version": "aoa_session_memory_goal_catalog_v1",
        "currentness": "stale",
        "generation_id": "generation-1",
    }
    assert result["counts_by_group"] == {"active": 1, "completed": 1}
    assert result["items"][0] == {
        "ref": "goal-current",
        "title": "Собрать спокойное пространство целей",
        "title_state": "available",
        "lifecycle_state": "active",
        "group": "active",
        "first_observed_at": "2026-08-22T18:00:00Z",
        "last_observed_at": "2026-08-22T21:00:00Z",
        "ambiguity": False,
    }
    assert "goal_instance_id" not in result["items"][0]
    assert "reason" not in result["items"][1]
    assert result["evidence_refs"][0]["owner"] == "aoa-session-memory"
    assert result["evidence_refs"][0]["currentness"] == "stale"


def test_missing_unreadable_and_future_publishers_fail_closed(tmp_path: Path) -> None:
    assert observe_goal_catalog({})["state"] == "missing"
    assert observe_goal_catalog({"goal_catalog_source": {"path": str(tmp_path / "absent.json")}})["state"] == "missing"
    payload = owner_payload()
    payload["schema_version"] = "aoa_session_memory_goal_catalog_v2"
    result = observe_goal_catalog(write_source(tmp_path, payload))
    assert result["state"] == "invalid"
    assert result["diagnostics"] == ["publisher_schema_unsupported"]


def test_catalog_rejects_duplicate_refs_and_technical_human_titles(tmp_path: Path) -> None:
    duplicate = owner_payload()
    duplicate["items"][1]["goal_ref"] = "goal-current"
    result = observe_goal_catalog(write_source(tmp_path, duplicate))
    assert result["state"] == "invalid"
    assert result["diagnostics"] == ["publisher_duplicate_goal_ref"]

    technical = copy.deepcopy(owner_payload())
    technical["items"][0]["title"] = "/srv/private/goal.json"
    result = observe_goal_catalog(write_source(tmp_path, technical))
    assert result["state"] == "invalid"
    assert result["diagnostics"] == ["human_title_invalid"]
