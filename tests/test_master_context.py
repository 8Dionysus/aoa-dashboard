from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.master_context import project_master_context  # noqa: E402


THREAD = "thread:master"


class MasterContextTests(unittest.TestCase):
    def context(self, **changes: object) -> tuple[dict, dict, dict, dict]:
        owner = {
            "state": "bound",
            "currentness": "current_at_read",
            "goal_ref": {"thread_id": THREAD, "owner": "codex-app-server", "source": "codex:goal"},
            "goal_projection": {"state": "bound", "goal": {"thread_id": THREAD, "title": "Master Goal"}},
            "thread": {
                "state": "bound",
                "thread_id": THREAD,
                "thread": {
                    "thread_id": THREAD,
                    "status": "active",
                    "name": "Master thread",
                    "parent_thread_id": None,
                    "forked_from_id": None,
                },
                "evidence_refs": [{"kind": "thread", "ref": "codex:thread", "owner": "codex-app-server"}],
                "diagnostics": [],
            },
            "relations": {
                "spawn_parent": {"state": "bound", "items": []},
                "history_fork": {"state": "bound", "items": []},
            },
            "evidence_refs": [{"kind": "goal", "ref": "codex:goal", "owner": "codex-app-server"}],
            "diagnostics": [],
        }
        correlation = {
            "state": "bound",
            "freshness": "current_at_read",
            "master_filter": {"ref": "master:filter", "currentness": "current_at_read"},
            "current_holder": {"label": "Master", "claim_limit": "correlation only"},
            "evidence_refs": [{"kind": "filter", "ref": "master:filter", "owner": "master-thread"}],
            "degradation": [],
        }
        catalog = {
            "state": "stale",
            "currentness": "stale",
            "source": {"ref": "catalog:goals", "owner": "aoa-session-memory"},
            "evidence_refs": [{"kind": "catalog", "ref": "catalog:goals", "owner": "aoa-session-memory"}],
        }
        topology = {
            "state": "bound",
            "currentness": "current_at_read",
            "root_ids": ["GS31"],
            "branches": [{"ref": "dag:GS31"}],
            "trajectories": [{"ref": "trajectory:GS31"}],
            "source": {"ref": "topology:dag", "owner": "master-thread"},
            "evidence_refs": [{"kind": "topology", "ref": "topology:dag", "owner": "master-thread"}],
        }
        for key, value in changes.items():
            if key == "owner":
                owner.update(value)
            elif key == "correlation":
                correlation.update(value)
        return owner, correlation, catalog, topology

    def test_schema_and_owner_fields_flow_with_independent_catalog_degradation(self) -> None:
        value = project_master_context(*self.context())
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts" / "master_context_projection.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema).validate(value)
        self.assertEqual(value["state"], "bound")
        self.assertEqual(value["goal_ref"]["thread_id"], THREAD)
        self.assertEqual(value["thread"]["name"], "Master thread")
        self.assertEqual(value["master_filter"]["ref"], "master:filter")
        self.assertEqual(value["goal_catalog"]["state"], "stale")
        self.assertEqual(value["topology"]["frontier_refs"], ["dag:GS31"])

    def test_invalid_master_filter_does_not_become_deferred_or_missing(self) -> None:
        owner, correlation, catalog, topology = self.context()
        correlation["master_filter"] = {"ref": "master:filter", "currentness": {"state": "invalid"}}
        value = project_master_context(owner, correlation, catalog, topology)
        self.assertEqual(value["state"], "invalid")
        self.assertEqual(value["currentness"], "invalid")

    def test_unavailable_sources_remain_missing(self) -> None:
        value = project_master_context(
            {"state": "missing", "currentness": "missing", "goal_ref": {"thread_id": None, "owner": "codex-app-server"}},
            {"state": "missing", "freshness": "missing"},
            {"state": "missing", "currentness": "missing"},
            {"state": "missing", "currentness": "missing"},
        )
        self.assertEqual(value["state"], "missing")
        self.assertEqual(value["currentness"], "missing")
        self.assertIsNone(value["thread"])


if __name__ == "__main__":
    unittest.main()
