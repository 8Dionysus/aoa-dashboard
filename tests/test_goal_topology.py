from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.goal_topology import observe_goal_topology  # noqa: E402


THREAD = "01a00722-0291-72e0-8310-559da802d6e1"


class GoalTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.wave = self.root / "goal-space-wave"
        self.wave.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, *, with_freshness: bool = False) -> dict:
        config = {
            "goal_topology_source": {
                "enabled": True,
                "relative_path": "goal-space-wave/goal-space-dag.json",
            },
            "current_correlation": {
                "master_thread_id": THREAD,
                "task_local_dir": str(self.root),
            },
        }
        if with_freshness and (self.wave / "goal-space-dag.json").is_file():
            config["goal_topology_source"]["expected_sha256"] = hashlib.sha256(
                (self.wave / "goal-space-dag.json").read_bytes()
            ).hexdigest()
        return config

    def write(self, **changes: object) -> None:
        value = {
            "schema_version": "aoa_dashboard_goal_space_task_dag_v1",
            "goal_ref": THREAD,
            "updated_at": "2026-08-23T04:00:00Z",
            "claim_limit": "Task-local planning only; no proof or acceptance.",
            "nodes": [
                {"id": "GS1", "title": "Current Goal binding", "state": "completed", "depends_on": []},
                {"id": "GS2", "title": "Full Goal readiness", "state": "in_progress", "depends_on": ["GS1"], "scope": "Hold the remaining directions together", "user_facing": True},
            ],
        }
        value.update(changes)
        (self.wave / "goal-space-dag.json").write_text(json.dumps(value), encoding="utf-8")

    def test_structural_root_is_projected_without_state_word_heuristics(self) -> None:
        self.write()
        observed = observe_goal_topology(self.config(with_freshness=True))
        self.assertEqual(observed["state"], "bound")
        self.assertEqual(observed["root_ids"], ["GS2"])
        self.assertEqual(observed["nodes"][1]["source_state"], "in_progress")
        self.assertTrue(observed["nodes"][1]["user_facing"])
        self.assertFalse(observed["nodes"][0]["user_facing"])
        self.assertEqual(observed["source"]["owner"], "master-thread")
        self.assertEqual([item["ref"] for item in observed["branches"]], ["dag:GS1", "dag:GS2"])
        self.assertEqual(observed["trajectories"][0]["node_refs"], ["dag:GS1", "dag:GS2"])

    def test_current_owner_state_with_embedded_node_refs_is_admitted(self) -> None:
        self.write(
            nodes=[
                {"id": "GS32", "title": "First support direction", "state": "completed", "depends_on": []},
                {
                    "id": "GS33",
                    "title": "Second support direction",
                    "state": "armed_after_GS32_GS33",
                    "depends_on": ["GS32"],
                },
            ]
        )
        observed = observe_goal_topology(self.config(with_freshness=True))
        self.assertEqual(observed["state"], "bound")
        self.assertEqual(observed["nodes"][1]["source_state"], "armed_after_GS32_GS33")
        self.assertEqual(observed["branches"][1]["state"], "armed_after_GS32_GS33")

    def test_malformed_and_stale_topology_sources_remain_distinct(self) -> None:
        self.write(nodes=[{"id": "GS1", "title": "First direction", "state": "bad\nstate", "depends_on": []}])
        malformed = observe_goal_topology(self.config(with_freshness=True))
        self.assertEqual(malformed["state"], "invalid")
        self.assertEqual(malformed["diagnostics"], ["topology_node_state_invalid"])

        self.write()
        stale_config = self.config(with_freshness=True)
        stale_config["goal_topology_source"]["expected_sha256"] = "0" * 64
        stale = observe_goal_topology(stale_config)
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(stale["diagnostics"], ["topology_source_stale"])

    def test_goal_mismatch_and_cycles_fail_closed(self) -> None:
        self.write(goal_ref="other")
        self.assertEqual(observe_goal_topology(self.config(with_freshness=True))["state"], "invalid")
        self.write(
            nodes=[
                {"id": "GS1", "title": "First direction", "state": "active", "depends_on": ["GS2"]},
                {"id": "GS2", "title": "Second direction", "state": "active", "depends_on": ["GS1"]},
            ]
        )
        observed = observe_goal_topology(self.config(with_freshness=True))
        self.assertEqual(observed["state"], "invalid")
        self.assertEqual(observed["diagnostics"], ["topology_cycle"])

    def test_missing_and_path_escape_remain_distinct(self) -> None:
        missing = observe_goal_topology(self.config())
        self.assertEqual(missing["state"], "missing")
        escaped = self.config()
        escaped["goal_topology_source"]["relative_path"] = "../outside.json"
        self.assertEqual(observe_goal_topology(escaped)["state"], "invalid")

    def test_duplicate_json_member_is_invalid_at_shared_source_boundary(self) -> None:
        self.write()
        path = self.wave / "goal-space-dag.json"
        raw = path.read_text(encoding="utf-8").replace(
            f'"goal_ref": "{THREAD}"',
            f'"goal_ref": "{THREAD}", "goal_ref": "secret-topology-value"',
            1,
        )
        path.write_text(raw, encoding="utf-8")

        observed = observe_goal_topology(self.config(with_freshness=True))

        assert observed["state"] == "invalid"
        assert observed["diagnostics"] == ["topology_source_invalid"]
        assert "secret-topology-value" not in json.dumps(observed)

    def test_existing_topology_without_freshness_attestation_is_deferred(self) -> None:
        self.write()

        observed = observe_goal_topology(self.config())

        self.assertEqual(observed["state"], "deferred")
        self.assertEqual(observed["diagnostics"], ["topology_currentness_attestation_missing"])
        self.assertEqual(observed["nodes"], [])
        self.assertEqual(observed["evidence_refs"][0]["currentness"], "deferred")
        self.assertIn("currentness_attestation", observed["evidence_refs"][0]["missing_fields"])


if __name__ == "__main__":
    unittest.main()
