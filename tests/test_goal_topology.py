from __future__ import annotations

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

    def config(self) -> dict:
        return {
            "goal_topology_source": {
                "enabled": True,
                "relative_path": "goal-space-wave/goal-space-dag.json",
            },
            "current_correlation": {
                "master_thread_id": THREAD,
                "task_local_dir": str(self.root),
            },
        }

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
        observed = observe_goal_topology(self.config())
        self.assertEqual(observed["state"], "bound")
        self.assertEqual(observed["root_ids"], ["GS2"])
        self.assertEqual(observed["nodes"][1]["source_state"], "in_progress")
        self.assertTrue(observed["nodes"][1]["user_facing"])
        self.assertFalse(observed["nodes"][0]["user_facing"])
        self.assertEqual(observed["source"]["owner"], "master-thread")

    def test_goal_mismatch_and_cycles_fail_closed(self) -> None:
        self.write(goal_ref="other")
        self.assertEqual(observe_goal_topology(self.config())["state"], "invalid")
        self.write(
            nodes=[
                {"id": "GS1", "title": "First direction", "state": "active", "depends_on": ["GS2"]},
                {"id": "GS2", "title": "Second direction", "state": "active", "depends_on": ["GS1"]},
            ]
        )
        observed = observe_goal_topology(self.config())
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

        observed = observe_goal_topology(self.config())

        assert observed["state"] == "invalid"
        assert observed["diagnostics"] == ["topology_source_invalid"]
        assert "secret-topology-value" not in json.dumps(observed)


if __name__ == "__main__":
    unittest.main()
