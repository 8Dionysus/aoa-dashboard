from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.projection import build_projection, load_config  # noqa: E402
from aoa_dashboard.correlation import observe_current_correlation  # noqa: E402
from aoa_dashboard.sources import observe_session  # noqa: E402


class ProjectionFixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.live = self.root / "live.jsonl"
        self.archive = self.root / "archive.jsonl"
        self.manifest = self.root / "session.manifest.json"
        self.anchor = self.root / "goal-anchor.txt"
        self.stats = self.root / "stats.json"
        self.registry = self.root / "registry.json"
        self.actor = self.root / "actor.jsonl"
        self.actor_manifest = self.root / "incarnation-home.json"
        self.task_local = self.root / "task-local"
        self.master_filter = self.task_local / "master-return-disposition.json"
        self.anchor.write_text("# current goal\nD0 dogfood\n", encoding="utf-8")
        self.live.write_text(
            json.dumps({"type": "message", "timestamp": "2026-08-15T22:00:00Z", "payload": {"type": "session_meta"}}) + "\n",
            encoding="utf-8",
        )
        self.archive.write_bytes(self.live.read_bytes())
        self.live.write_text(
            self.live.read_text(encoding="utf-8")
            + json.dumps({"type": "message", "timestamp": "2026-08-15T22:01:00Z", "payload": {"type": "event_msg"}})
            + "\n",
            encoding="utf-8",
        )
        self.manifest.write_text(
            json.dumps({"latest_event_count": 2, "raw": {"source_path": str(self.live)}}),
            encoding="utf-8",
        )
        self.stats.write_text(
            json.dumps(
                {
                    "schema_version": "aoa_stats_source_coverage_summary_v1",
                    "generated_from": {"total_receipts": 1, "latest_observed_at": "2026-08-15T22:00:00Z"},
                    "owner_counts": {"test-owner": 1},
                    "expected_owner_repos": ["test-owner"],
                    "missing_owner_repos": [],
                    "thin_signal_flags": [],
                }
            ),
            encoding="utf-8",
        )
        self.registry.write_text(json.dumps({"sources": []}), encoding="utf-8")
        self.actor_manifest.write_text("{}", encoding="utf-8")

    def config(self) -> dict:
        config = copy.deepcopy(load_config())
        config.update(
            {
                "goal_id": "test-goal",
                "title": "Test goal",
                "goal_anchor_path": str(self.anchor),
                "historical_bootstrap": {
                    "binding_id": "test-historical-bootstrap",
                    "session_manifest_path": str(self.manifest),
                    "session_archive_raw_path": str(self.archive),
                    "actor_manifest_path": str(self.actor_manifest),
                    "configured_scope": "historical_bootstrap",
                    "current_holder": False,
                },
                "current_correlation": {
                    "master_thread_id": "test-thread",
                    "task_local_dir": str(self.task_local),
                    "master_filter_path": str(self.master_filter),
                    "handoff_glob": "*-luna-handoff.json",
                    "wake_glob": "*.wake-receipt.json",
                    "ignored_handoff_names": [],
                    "current_holder": "test holder",
                },
                "actor_receipt_path": str(self.actor),
                "stats_surface_path": str(self.stats),
                "stats_registry_path": str(self.registry),
                "owner_surfaces": [{"owner": "test-owner", "source_path": str(self.root), "runtime_path": None, "authority": "test binding", "kag_snapshot_state": "stale"}],
            }
        )
        return config

    def close(self) -> None:
        self.tmp.cleanup()


class ProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProjectionFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_live_archive_drift_is_deferred(self) -> None:
        result = observe_session(self.fixture.config())
        self.assertEqual(result["state"], "deferred")
        self.assertEqual(result["freshness"], "deferred")
        self.assertGreater(result["metadata"]["live_records"], result["metadata"]["archive_records"])

    def test_missing_actor_publisher_is_not_zero_success(self) -> None:
        projection = build_projection(self._write_config())
        actor = next(item for item in projection["sources"] if item["id"] == "actor-responsibility-receipts")
        stats = next(item for item in projection["sources"] if item["id"] == "aoa-stats-source-coverage")
        self.assertEqual(actor["state"], "missing")
        self.assertEqual(actor["publisher_status"], "optional-missing")
        self.assertEqual(actor["metadata"]["records"], 0)
        self.assertIn("inferred", actor["observation"])
        self.assertEqual(stats["metadata"]["actor_publisher_state"], "missing")

    def test_state_vocabulary_is_not_collapsed(self) -> None:
        projection = build_projection(self._write_config())
        states = {item["state"] for item in projection["state_inventory"]}
        self.assertEqual(
            states,
            {"planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "wake requested", "reentered", "missing", "unknown", "stale", "deferred", "invalid"},
        )
        steps = {item["step"]: item["state"] for item in projection["lifecycle"]}
        self.assertEqual(steps["planned"], "planned")
        self.assertEqual(steps["bound"], "missing")
        self.assertEqual(steps["running"], "deferred")
        self.assertEqual(steps["paused"], "paused")
        self.assertEqual(steps["returned"], "missing")
        self.assertEqual(steps["reviewed"], "missing")
        self.assertEqual(steps["accepted"], "missing")

    def test_invalid_json_source_is_invalid(self) -> None:
        self.fixture.stats.write_text("{not-json", encoding="utf-8")
        projection = build_projection(self._write_config())
        stats = next(item for item in projection["sources"] if item["id"] == "aoa-stats-source-coverage")
        self.assertEqual(stats["state"], "invalid")
        self.assertNotEqual(stats["state"], "accepted")

    def test_historical_bootstrap_is_not_current_holder(self) -> None:
        projection = build_projection(self._write_config())
        session = next(item for item in projection["sources"] if item["id"] == "aoa-session-memory")
        self.assertEqual(session["metadata"]["binding_scope"], "historical_bootstrap")
        self.assertFalse(session["metadata"]["current_holder"])
        self.assertEqual(projection["current_holder"]["scope"], "current_task_local_correlation")
        self.assertEqual(next(item for item in projection["lifecycle"] if item["step"] == "running")["state"], "deferred")

    def _write_config(self) -> str:
        path = self.fixture.root / "config.json"
        path.write_text(json.dumps(self.fixture.config()), encoding="utf-8")
        return str(path)


class CorrelationFixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.task_local = self.root / "task-local"
        self.task_local.mkdir()
        self.anchor = self.root / "goal-anchor.txt"
        self.anchor.write_text("# goal\n", encoding="utf-8")
        self.thread = "thread-test-1"
        self.handoff = self.task_local / "positive-luna-handoff.json"
        self.wake = self.task_local / "positive-luna-handoff.wake-receipt.json"
        self.filter = self.task_local / "master-return-disposition.json"
        self._write_valid()

    def _write_json(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    def _write_valid(self, *, handoff_thread: str | None = None, wake_payload: dict | None = None) -> None:
        handoff = {
            "schema_version": "test_handoff_v1",
            "master_thread_id": handoff_thread or self.thread,
            "responsibility_state": "returned",
        }
        self._write_json(self.handoff, handoff)
        handoff_digest = hashlib.sha256(self.handoff.read_bytes()).hexdigest()
        wake = wake_payload or {
            "schema_version": "task_local_actor_wake_receipt_v2",
            "thread_id": self.thread,
            "handoff_ref": str(self.handoff.resolve()),
            "handoff_sha256": handoff_digest,
            "outcome": "handoff_delivered_pending_master_filter",
            "attempted_at": "2026-08-15T23:00:00Z",
            "observed": {
                "accepted_turn_id": "accepted-turn-1",
                "delivery_route": "active_turn_steer",
                "handoff_delivery": True,
            },
            "actions": {"handoff_message_submitted": True, "goal_resume_requested": False},
        }
        self._write_json(self.wake, wake)
        self._write_filter(handoff_digest)

    def _write_filter(self, handoff_digest: str, *, duplicate: bool = False, handoff_ref: str | None = None) -> None:
        entry = {
            "id": "positive",
            "disposition": "accepted_with_limits",
            "handoff_ref": handoff_ref or str(self.handoff.resolve()),
            "handoff_sha256": handoff_digest,
            "wake_receipt_ref": str(self.wake.resolve()),
        }
        returns = [entry, copy.deepcopy(entry)] if duplicate else [entry]
        self._write_json(
            self.filter,
            {
                "schema_version": "aoa_dashboard_master_return_disposition_v1",
                "master_thread_id": self.thread,
                "goal_ref": str(self.anchor.resolve()),
                "reviewed_at": "2026-08-15T23:01:00Z",
                "returns": returns,
                "goal_dag": [{"id": "D5", "state": "partial", "next": "runtime owner"}],
                "new_required_obligations": ["obligation:next"],
                "rejected_or_deferred_claims": ["semantic continuation"],
            },
        )

    def config(self) -> dict:
        return {
            "goal_id": "goal-test",
            "goal_anchor_path": str(self.anchor),
            "current_correlation": {
                "master_thread_id": self.thread,
                "task_local_dir": str(self.task_local),
                "master_filter_path": str(self.filter),
                "handoff_glob": "*-luna-handoff.json",
                "wake_glob": "*.wake-receipt.json",
                "ignored_handoff_names": [],
                "current_holder": "test correlation holder",
            },
        }

    def close(self) -> None:
        self.tmp.cleanup()


class CorrelationAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CorrelationFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_positive_real_task_local_shape_is_reentered_only_by_turn_and_filter(self) -> None:
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "bound")
        envelope = result["metadata"]["envelopes"][0]
        self.assertEqual(envelope["state"], "reentered")
        self.assertEqual(envelope["lifecycle"]["returned"]["state"], "returned")
        self.assertEqual(envelope["lifecycle"]["wake_requested"]["state"], "wake requested")
        self.assertEqual(envelope["accepted_turn"]["accepted_turn_id"], "accepted-turn-1")
        self.assertEqual(envelope["lifecycle"]["reentered"]["state"], "reentered")
        self.assertEqual(envelope["return_observation"]["ref"]["sha256"], envelope["master_filter"]["handoff_sha256"])

    def test_current_real_receipt_directory_is_bound_when_available(self) -> None:
        config = load_config()
        current = config["current_correlation"]
        if not Path(current["task_local_dir"]).is_dir():
            self.skipTest("task-local receipt directory is not present")
        result = observe_current_correlation(config)
        self.assertEqual(result["state"], "bound")
        self.assertEqual(result["metadata"]["master_thread_id"], "01a00722-0291-72e0-8310-559da802d6e1")
        self.assertEqual(result["metadata"]["summary"]["reentered"], 4)

    def test_mismatched_master_thread_is_invalid(self) -> None:
        self.fixture._write_valid(handoff_thread="other-thread")
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertEqual(result["metadata"]["envelopes"][0]["state"], "invalid")

    def test_mismatched_handoff_digest_is_invalid(self) -> None:
        self.fixture._write_valid()
        self.fixture._write_filter("0" * 64)
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertIn("SHA-256", " ".join(result["metadata"]["envelopes"][0]["return_observation"]["errors"]))

    def test_non_exact_handoff_ref_is_invalid(self) -> None:
        digest = hashlib.sha256(self.fixture.handoff.read_bytes()).hexdigest()
        self.fixture._write_filter(digest, handoff_ref="/tmp/not-the-task-local-handoff.json")
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertEqual(result["metadata"]["envelopes"][0]["state"], "invalid")

    def test_delivery_outcome_mismatch_is_invalid(self) -> None:
        malformed = json.loads(self.fixture.wake.read_text(encoding="utf-8"))
        malformed["outcome"] = "delivery_not_verified"
        self.fixture._write_valid(wake_payload=malformed)
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertEqual(result["metadata"]["envelopes"][0]["state"], "invalid")

    def test_malformed_v2_wake_receipt_is_invalid(self) -> None:
        malformed = {
            "schema_version": "wake-v1",
            "thread_id": self.fixture.thread,
            "handoff_ref": str(self.fixture.handoff.resolve()),
            "handoff_sha256": hashlib.sha256(self.fixture.handoff.read_bytes()).hexdigest(),
            "outcome": "handoff_delivered_pending_master_filter",
            "attempted_at": "2026-08-15T23:00:00Z",
            "observed": {"accepted_turn_id": "accepted-turn-1", "handoff_delivery": True},
            "actions": {"handoff_message_submitted": True},
        }
        self.fixture._write_valid(wake_payload=malformed)
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertEqual(result["metadata"]["envelopes"][0]["state"], "invalid")

    def test_missing_wake_receipt_stays_missing_and_not_success(self) -> None:
        self.fixture.wake.unlink()
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "deferred")
        envelope = result["metadata"]["envelopes"][0]
        self.assertEqual(envelope["lifecycle"]["returned"]["state"], "returned")
        self.assertEqual(envelope["lifecycle"]["wake_requested"]["state"], "missing")
        self.assertEqual(envelope["lifecycle"]["reentered"]["state"], "missing")

    def test_duplicate_filter_return_is_invalid(self) -> None:
        digest = hashlib.sha256(self.fixture.handoff.read_bytes()).hexdigest()
        self.fixture._write_filter(digest, duplicate=True)
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertTrue(any("duplicate" in item for item in result["metadata"]["degradation"]))

    def test_duplicate_wake_receipts_are_invalid(self) -> None:
        duplicate = self.fixture.task_local / "duplicate.wake-receipt.json"
        duplicate.write_bytes(self.fixture.wake.read_bytes())
        result = observe_current_correlation(self.fixture.config())
        self.assertEqual(result["state"], "invalid")
        self.assertTrue(any("duplicate wake" in item for item in result["metadata"]["degradation"]))


if __name__ == "__main__":
    unittest.main()
