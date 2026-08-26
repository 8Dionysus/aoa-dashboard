from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.goal_catalog import observe_goal_catalog, observe_goal_projection


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


def public_owner_page(*, items: list[dict], offset: int, cursor: str | None, next_cursor: str | None) -> dict:
    watermark = {
        "schema_version": 1,
        "kind": "complete_session_index_set_v1",
        "registry_digest": "registry-digest",
        "source_set_digest": "sha256:" + "1" * 64,
        "session_count": 2,
        "goal_lifecycle_count": 2,
        "coverage": "complete",
        "max_updated_at": "2026-08-23T10:00:00Z",
        "max_raw_line_count": 12,
    }
    source_generation = {"generation_id": "generation-owner-test"}
    snapshot_digest = "sha256:" + "2" * 64
    page_digest = "sha256:" + str(offset + 3) * 64
    source = {
        "owner": "aoa-session-memory",
        "ref": "aoa-session-memory:goal-lifecycles",
        "goal_lifecycle_schema_version": 3,
        "generation_identity": source_generation,
        "goal_lifecycle_generation": {"generation_id": "lifecycle-owner-test"},
        "watermark": watermark,
        "currentness": "current",
    }
    return {
        "schema_version": "aoa_session_memory_goal_catalog_v1",
        "publication_schema_version": "aoa_session_memory_goal_catalog_public_v1",
        "artifact_type": "goal_catalog_projection",
        "generated_at": "2026-08-23T10:00:00Z",
        "ok": True,
        "state": "current",
        "currentness": "current",
        "publication_state": "bound",
        "target": "all",
        "order": "recent",
        "source": source,
        "source_generation": source_generation,
        "source_watermark": watermark,
        "snapshot": {
            "snapshot_ref": snapshot_digest,
            "snapshot_digest": snapshot_digest,
            "generated_at": "2026-08-23T10:00:00Z",
            "source_watermark": watermark,
            "source_freshness": "current",
            "projection_freshness": "current",
            "immutable": True,
        },
        "pagination": {
            "mode": "immutable_snapshot",
            "cursor": cursor,
            "next_cursor": next_cursor,
            "complete_for_query": next_cursor is None,
            "page_size": 1,
            "supports_immutable_snapshot": True,
        },
        "page": {"offset": offset, "item_count": len(items), "page_digest": page_digest},
        "snapshot_digest": snapshot_digest,
        "page_digest": page_digest,
        "source_item_count": 2,
        "item_count": len(items),
        "total_item_count": 2,
        "lifecycle_group_count": 2,
        "counts_by_lifecycle_state": {"active": 1, "complete": 1},
        "items": items,
        "diagnostics": [],
        "omissions": {"transcript_body": True, "private_objective": True, "raw_session_path": True},
        "privacy": {
            "scope": "owner_bounded_public_safe",
            "allowlisted_fields": ["goal_ref", "lifecycle_state"],
            "withheld_fields": ["private_objective"],
            "prohibited_join_keys": ["raw_session_path"],
            "no_transcript_body": True,
            "no_process_identity": True,
            "no_actor_inference": True,
        },
        "claim_limit": "Owner public navigation only.",
    }


def public_owner_item(ref: str, lifecycle: str) -> dict:
    group = {
        "group_ref": f"group:{ref}",
        "grouping_basis": "goal_instance_id",
        "member_count": 1,
        "current_member_count": 1 if lifecycle == "active" else 0,
        "historical_member_count": 1 if lifecycle == "complete" else 0,
        "unknown_member_count": 0,
        "states": [lifecycle],
        "history_state": "complete",
    }
    return {
        "goal_ref": ref,
        "goal_ref_state": "opaque",
        "goal_instance_id": f"instance:{ref}",
        "goal_instance_id_state": "opaque",
        "goal_id": None,
        "goal_id_state": "missing",
        "thread_id": None,
        "thread_id_state": "missing",
        "safe_title_state": "withheld",
        "safe_title_reason": "private_objective_omitted",
        "title": None,
        "title_state": "withheld",
        "reason": "private_objective_omitted",
        "lifecycle_state": lifecycle,
        "lifecycle_group": group,
        "thread_metadata_state": "missing",
        "relation_state": "missing",
        "first_observed_at": "2026-08-23T09:00:00Z",
        "last_observed_at": "2026-08-23T10:00:00Z",
        "evidence_ref": f"goal-lifecycle:instance:{ref}",
        "ambiguity_state": "none",
        "ambiguity": False,
        "redacted_fields": ["private_objective", "transcript_body"],
        "item_digest": "sha256:" + hashlib.sha256(ref.encode()).hexdigest(),
    }


def write_public_command(tmp_path: Path, first: dict, second: dict) -> list[str]:
    script = tmp_path / "owner-public-command.py"
    script.write_text(
        "import json, sys\n"
        f"pages = {json.dumps({'first': first, 'second': second}, ensure_ascii=False)!r}\n"
        "pages = json.loads(pages)\n"
        "print(json.dumps(pages['second'] if '--cursor' in sys.argv else pages['first']))\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


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


def test_public_owner_pages_are_admitted_and_cursor_followed(tmp_path: Path) -> None:
    first = public_owner_page(
        items=[public_owner_item("goal:active", "active")],
        offset=0,
        cursor=None,
        next_cursor="gcat1-next",
    )
    second = public_owner_page(
        items=[public_owner_item("goal:complete", "complete")],
        offset=1,
        cursor="gcat1-next",
        next_cursor=None,
    )
    result = observe_goal_catalog(
        {
            "goal_catalog_source": {
                "publication": {
                    "capability": "aoa-session-memory.goal-catalog.read",
                    "command": write_public_command(tmp_path, first, second),
                    "cursor_arg": "--cursor",
                    "max_pages": 4,
                }
            }
        }
    )
    assert result["state"] == "current"
    assert [item["ref"] for item in result["items"]] == ["goal:active", "goal:complete"]
    assert result["pagination"]["mode"] == "immutable_snapshot"
    assert result["pagination"]["complete"] is True
    assert result["owner_page_count"] == 2
    assert result["source"]["publication_schema_version"] == "aoa_session_memory_goal_catalog_public_v1"
    assert result["items"][1]["lifecycle_group"]["historical_member_count"] == 1
    assert result["items"][0]["evidence_ref"].startswith("goal-lifecycle:")


def test_public_negative_command_payload_is_preserved_fail_closed(tmp_path: Path) -> None:
    payload = public_owner_page(items=[], offset=0, cursor=None, next_cursor=None)
    payload["ok"] = False
    payload["state"] = payload["currentness"] = payload["publication_state"] = "stale"
    payload["source"]["currentness"] = "stale"
    payload["snapshot"]["source_freshness"] = "stale"
    payload["snapshot"]["projection_freshness"] = "stale"
    payload["counts_by_lifecycle_state"] = {}
    payload["source_item_count"] = payload["total_item_count"] = 0
    payload["diagnostics"] = ["goal_lifecycle_source_generation_incompatible"]
    script = tmp_path / "owner-negative-command.py"
    script.write_text(
        "import json, sys\n"
        f"print({json.dumps(payload, ensure_ascii=False)!r})\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    result = observe_goal_catalog(
        {
            "goal_catalog_source": {
                "publication": {
                    "capability": "aoa-session-memory.goal-catalog.read",
                    "command": [sys.executable, str(script)],
                }
            }
        }
    )
    assert result["state"] == "stale"
    assert result["items"] == []
    assert result["source"]["currentness"] == "stale"
    assert result["evidence_refs"][0]["ref"] == "capability:aoa-session-memory.goal-catalog.read"


def test_missing_unreadable_and_future_publishers_fail_closed(tmp_path: Path) -> None:
    assert observe_goal_catalog({})["state"] == "missing"
    assert observe_goal_catalog({"goal_catalog_source": {"path": str(tmp_path / "absent.json")}})["state"] == "missing"
    payload = owner_payload()
    payload["schema_version"] = "aoa_session_memory_goal_catalog_v2"
    result = observe_goal_catalog(write_source(tmp_path, payload))
    assert result["state"] == "invalid"
    assert result["diagnostics"] == ["publisher_schema_unsupported"]

    stale_path = tmp_path / "stale-catalog.json"
    stale_path.write_text(json.dumps(owner_payload()), encoding="utf-8")
    stale = observe_goal_catalog(
        {"goal_catalog_source": {"path": str(stale_path), "expected_sha256": "0" * 64}}
    )
    assert stale["state"] == "stale"
    assert stale["diagnostics"] == ["publisher_stale"]


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


def test_catalog_duplicate_json_member_is_invalid_at_shared_source_boundary(tmp_path: Path) -> None:
    path = tmp_path / "goal-catalog.json"
    raw = json.dumps(owner_payload()).replace(
        '"schema_version": "aoa_session_memory_goal_catalog_v1"',
        '"schema_version": "aoa_session_memory_goal_catalog_v1", "schema_version": "secret-catalog-value"',
        1,
    )
    path.write_text(raw, encoding="utf-8")

    result = observe_goal_catalog({"goal_catalog_source": {"path": str(path)}})

    assert result["state"] == "invalid"
    assert result["diagnostics"] == ["publisher_unreadable"]
    assert "secret-catalog-value" not in json.dumps(result)


def test_explicit_owner_command_preserves_opaque_pagination_and_locale_metadata(tmp_path: Path) -> None:
    payload = owner_payload()
    payload["state"] = payload["currentness"] = "current"
    payload["source"]["currentness"] = "current"
    payload["items"][0]["title_locale"] = "ru"
    payload["pagination"] = {"cursor": "opaque-in", "next_cursor": "opaque-next", "complete": False}
    payload["item_count"] = 2
    command = [sys.executable, "-c", "import json,sys; print(json.dumps(json.loads(sys.argv[1])))", json.dumps(payload)]
    result = observe_goal_catalog(
        {
            "goal_catalog_source": {
                "publication": {"capability": "aoa-session-memory.goal-catalog.read", "command": command},
            }
        }
    )
    assert result["state"] == "current"
    assert result["pagination"] == {"mode": "opaque_cursor", "cursor": "opaque-in", "next_cursor": "opaque-next", "complete": False}
    assert result["items"][0]["title_locale"] == "ru"
    assert result["evidence_refs"][0]["ref"] == "capability:aoa-session-memory.goal-catalog.read"


def test_catalog_accepts_localized_only_titles_and_full_page_counts(tmp_path: Path) -> None:
    payload = owner_payload()
    payload["state"] = payload["currentness"] = "current"
    payload["source"]["currentness"] = "current"
    payload["items"][0]["title"] = None
    payload["items"][0]["title_by_locale"] = {"en": "A localized Goal"}
    payload["items"][0].pop("title_locale", None)
    payload["item_count"] = 12
    payload["page_item_count"] = 2
    payload["pagination"] = {"cursor": "opaque-page-1", "next_cursor": "opaque-page-2", "complete": False}
    result = observe_goal_catalog(write_source(tmp_path, payload))
    assert result["state"] == "current"
    assert result["items"][0]["title"] is None
    assert result["items"][0]["title_by_locale"] == {"en": "A localized Goal"}
    assert result["pagination"]["next_cursor"] == "opaque-page-2"

    bad = copy.deepcopy(payload)
    bad["page_item_count"] = 3
    result = observe_goal_catalog(write_source(tmp_path, bad))
    assert result["state"] == "invalid"
    assert result["diagnostics"] == ["publisher_page_item_count_mismatch"]


def test_per_goal_projection_requires_catalog_membership_and_exact_owner_ref(tmp_path: Path) -> None:
    catalog = owner_payload()
    catalog["state"] = catalog["currentness"] = "current"
    catalog["source"]["currentness"] = "current"
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    projection = {
        "schema_version": "aoa_session_memory_goal_projection_v1",
        "artifact_type": "goal_projection",
        "state": "current",
        "currentness": "current",
        "goal_ref": "goal-current",
        "title": "Owner Goal in English",
        "title_state": "available",
        "title_locale": "en",
        "lifecycle_state": "active",
        "summary": {"en": "A bounded owner projection"},
        "public_items": [],
        "source": {"owner": "aoa-session-memory", "ref": "aoa-session-memory:goal-projection", "currentness": "current"},
        "omissions": {"raw_body": True},
        "claim_limit": "Owner projection only.",
    }
    projection_path = tmp_path / "projection.json"
    projection_path.write_text(json.dumps(projection), encoding="utf-8")
    config = {
        "goal_catalog_source": {"path": str(catalog_path)},
        "goal_projection_source": {"path": str(projection_path)},
    }
    result = observe_goal_projection(config, "goal-current")
    assert result["state"] == "current"
    assert result["goal_ref"] == "goal-current"
    assert result["title_locale"] == "en"
    assert result["omissions"] == {"raw_body": True}
    not_member = observe_goal_projection(config, "goal-not-in-catalog")
    assert not_member["state"] == "missing"
    assert not_member["diagnostics"] == ["selected_goal_not_in_catalog"]
