from __future__ import annotations

import json
from pathlib import Path

import pytest

from aoa_dashboard.sources import observe_kag, observe_unconnected_owner


def _config(path: Path, owner: str = "aoa-kag") -> dict:
    return {"goal_id": "goal:test", "owner_observations": {owner: {
        "owner": owner, "path": str(path), "expected_schema_version": "fixture_owner_snapshot_v1",
        "authority": "source_owner", "access_scope": "owner_bounded", "claim_policy": "source_owner_metadata",
    }}}


def test_digest_alone_does_not_invent_a_date_or_currentness() -> None:
    result = observe_kag({"kag_projection_digest": "new-digest", "kag_projection_updated_at": "2030-01-02"})
    assert result["state"] == result["freshness"] == "unknown"
    assert result["metadata"]["updated_at"] == "2030-01-02"
    assert result["metadata"]["retrieval_eval"] == "unknown"
    assert "2026-08-08" not in json.dumps(result)
    assert "/srv/" not in json.dumps(result)


@pytest.mark.parametrize("state,expected", [("stale", "stale"), ("partial", "unknown"), ("denied", "unknown"), ("missing", "missing")])
def test_selected_owner_response_retains_distinct_degradation(tmp_path: Path, state: str, expected: str) -> None:
    path = tmp_path / "owner.json"
    path.write_text(json.dumps({"schema_version": "fixture_owner_snapshot_v1", "owner": "aoa-kag", "state": state}))
    result = observe_kag(_config(path))
    assert result["state"] == expected
    assert result["publisher_status"] == state
    assert result["metadata"]["goal_evidence_admitted"] is False
    assert result["evidence_refs"][0]["ref"] == str(path)


def test_bound_response_presence_does_not_attest_freshness(tmp_path: Path) -> None:
    path = tmp_path / "owner.json"
    path.write_text(json.dumps({"schema_version": "fixture_owner_snapshot_v1", "owner": "aoa-kag", "state": "current", "updated_at": "2030-02-03"}))
    result = observe_kag(_config(path))
    assert result["state"] == "bound"
    assert result["freshness"] == "unknown"
    assert result["metadata"]["reported_state"] == "current"
    assert result["metadata"]["reported_updated_at"] == "2030-02-03"
    pinned = _config(path)
    pinned["owner_observations"]["aoa-kag"]["expected_sha256"] = "0" * 64
    assert observe_kag(pinned)["state"] == "stale"


def test_absent_and_denied_source_are_not_the_same(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "owner.json"
    config = _config(path)
    assert observe_kag(config)["publisher_status"] == "missing"
    monkeypatch.setattr(Path, "read_bytes", lambda _self: (_ for _ in ()).throw(PermissionError("denied")))
    result = observe_kag(config)
    assert result["publisher_status"] == "denied"
    assert result["state"] == "unknown"


@pytest.mark.parametrize("change", [{"owner": "foreign"}, {"goal_id": "goal:other"}, {"schema_version": "foreign_v1"}])
def test_wrong_owner_scope_or_schema_is_invalid(tmp_path: Path, change: dict) -> None:
    path = tmp_path / "owner.json"
    path.write_text(json.dumps({"schema_version": "fixture_owner_snapshot_v1", "owner": "aoa-kag", "state": "current", **change}))
    assert observe_kag(_config(path))["state"] == "invalid"


def test_unbound_owner_has_no_fabricated_root_or_availability(tmp_path: Path) -> None:
    result = observe_unconnected_owner("aoa-memo", {})
    assert result["state"] == "unknown"
    assert result["publisher_status"] == "unbound"
    assert result["evidence_refs"] == []
    path = tmp_path / "memo.json"
    path.write_text(json.dumps({"schema_version": "fixture_owner_snapshot_v1", "owner": "aoa-memo", "state": "partial"}))
    assert observe_unconnected_owner("aoa-memo", _config(path, "aoa-memo"))["publisher_status"] == "partial"


def test_generic_snapshot_exposes_only_bounded_scalar_metadata(tmp_path: Path) -> None:
    path = tmp_path / "owner.json"
    path.write_text(json.dumps({
        "schema_version": "fixture_owner_snapshot_v1", "owner": "aoa-kag",
        "state": "partial", "currentness": {"unsupported": True},
        "updated_at": "x" * 513, "retrieval_eval": float("nan"),
        "private_body": "must not be projected",
    }))
    result = observe_kag(_config(path))
    serialized = json.dumps(result, allow_nan=False)
    assert result["publisher_status"] == "partial"
    assert "reported_updated_at" not in result["metadata"]
    assert "reported_retrieval_eval" not in result["metadata"]
    assert "private_body" not in serialized
