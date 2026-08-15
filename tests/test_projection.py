from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.projection import build_projection, load_config  # noqa: E402
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
                "session_manifest_path": str(self.manifest),
                "session_archive_raw_path": str(self.archive),
                "actor_manifest_path": str(self.actor_manifest),
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
        self.assertEqual(steps["bound"], "bound")
        self.assertEqual(steps["running"], "running")
        self.assertEqual(steps["paused"], "paused")
        self.assertEqual(steps["returned"], "deferred")
        self.assertEqual(steps["reviewed"], "missing")
        self.assertEqual(steps["accepted"], "missing")

    def test_invalid_json_source_is_invalid(self) -> None:
        self.fixture.stats.write_text("{not-json", encoding="utf-8")
        projection = build_projection(self._write_config())
        stats = next(item for item in projection["sources"] if item["id"] == "aoa-stats-source-coverage")
        self.assertEqual(stats["state"], "invalid")
        self.assertNotEqual(stats["state"], "accepted")

    def _write_config(self) -> str:
        path = self.fixture.root / "config.json"
        path.write_text(json.dumps(self.fixture.config()), encoding="utf-8")
        return str(path)


if __name__ == "__main__":
    unittest.main()
