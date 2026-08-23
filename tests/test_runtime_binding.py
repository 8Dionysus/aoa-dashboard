from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.codex_goal import CodexGoalUnavailable  # noqa: E402
from aoa_dashboard.correlation import observe_current_correlation  # noqa: E402
from aoa_dashboard.projection import build_projection, load_config  # noqa: E402


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _owner(owner: str, authority: str, claim_policy: str) -> dict[str, str]:
        return {
            "owner": owner,
            "authority": authority,
            "access_scope": "owner_bounded",
            "claim_policy": claim_policy,
            "claim_limit": "This owner source is read-only evidence and does not grant dashboard authority.",
        }

    def _binding(self, label: str, goal_id: str, thread_id: str) -> tuple[Path, dict]:
        task_root = self.root / label
        topology_dir = task_root / "goal-space-wave"
        topology_dir.mkdir(parents=True)
        anchor = task_root / "goal-anchor.json"
        anchor.write_text(
            json.dumps(
                {
                    "schema_version": "aoa_dashboard_goal_anchor_binding_v1",
                    "owner": "goal-anchor",
                    "authority": "source_owner",
                    "access_scope": "owner_bounded",
                    "claim_policy": "source_owner_metadata",
                    "claim_limit": "The structured Goal Anchor is source evidence, not dashboard authority.",
                    "goal_id": goal_id,
                    "master_thread_id": thread_id,
                    "title": f"{label} selected Goal",
                    "source_ref": f"goal-anchor:{goal_id}",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        topology = topology_dir / "goal-space-dag.json"
        topology.write_text(
            json.dumps(
                {
                    "schema_version": "aoa_dashboard_goal_space_task_dag_v1",
                    "goal_ref": thread_id,
                    "updated_at": "2026-08-23T04:00:00Z",
                    "claim_limit": "Task-local planning only; no proof or acceptance.",
                    "nodes": [
                        {
                            "id": "GS1",
                            "title": f"{label} topology",
                            "state": "active",
                            "depends_on": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        catalog = task_root / "goal-catalog.json"
        catalog.write_text(
            json.dumps(
                {
                    "schema_version": "aoa_session_memory_goal_catalog_v1",
                    "artifact_type": "goal_catalog_projection",
                    "generated_at": "2026-08-23T04:00:00Z",
                    "state": "current",
                    "currentness": "current",
                    "source": {
                        "owner": "aoa-session-memory",
                        "ref": "aoa-session-memory:goal-lifecycles",
                        "currentness": "current",
                    },
                    "items": [
                        {
                            "goal_ref": goal_id,
                            "title": f"{label} navigation",
                            "title_state": "available",
                            "lifecycle_state": "active",
                            "first_observed_at": None,
                            "last_observed_at": None,
                            "ambiguity": False,
                        }
                    ],
                    "item_count": 1,
                    "diagnostics": [],
                    "claim_limit": "Scope: owner-published Goal navigation.",
                }
            ),
            encoding="utf-8",
        )
        pressure = task_root / "pressure-context.json"
        pressure.write_text(
            json.dumps(
                {
                    "schema_version": "aoa_dashboard_pressure_context_v1",
                    "owner": "master-thread",
                    "authority": "master_decision",
                    "state": "current_at_read",
                    "currentness": "current_at_read",
                    "goal_id": goal_id,
                    "items": [],
                }
            ),
            encoding="utf-8",
        )
        binding = {
            "schema_version": "aoa_dashboard_runtime_binding_v1",
            "binding_id": f"binding-{label}",
            "owner": "aoa-sdk",
            "authority": "source_owner",
            "access_scope": "owner_bounded",
            "claim_policy": "runtime_binding",
            "claim_limit": "The selected owner binding is read-only and is not dashboard authority.",
            "state": "current_at_read",
            "currentness": "current_at_read",
            "selected_goal": {
                "goal_id": goal_id,
                "master_thread_id": thread_id,
                "title": f"{label} selected Goal",
            },
            "sources": {
                "goal_anchor": {
                    **self._owner("goal-anchor", "source_owner", "source_owner_metadata"),
                    "path": str(anchor),
                    "expected_sha256": hashlib.sha256(anchor.read_bytes()).hexdigest(),
                },
                "codex_goal": {
                    **self._owner("codex-app-server", "source_owner", "source_owner_metadata"),
                    "enabled": True,
                    "method": "thread/goal/get",
                },
                "codex_thread": {
                    **self._owner("codex-app-server", "source_owner", "source_owner_metadata"),
                    "enabled": True,
                    "methods": ["thread/read", "thread/list"],
                    "relation_queries": ["parentThreadId", "ancestorThreadId"],
                    "requires_experimental_api": True,
                },
                "topology": {
                    **self._owner("master-thread", "master_decision", "master_decision_disposition"),
                    "relative_path": "goal-space-wave/goal-space-dag.json",
                    "expected_schema_version": "aoa_dashboard_goal_space_task_dag_v1",
                },
                "catalog": {
                    **self._owner("aoa-session-memory", "source_owner", "source_owner_metadata"),
                    "path": str(catalog),
                    "expected_schema_version": "aoa_session_memory_goal_catalog_v1",
                },
                "correlation": {
                    **self._owner("master-thread", "master_decision", "master_decision_disposition"),
                    "master_thread_id": thread_id,
                    "task_local_dir": str(task_root),
                    "master_filter_path": str(task_root / "master-return-disposition.json"),
                    "master_filter_currentness": {
                        "schema_version": "aoa_dashboard_master_filter_currentness_binding_v1",
                        "owner": "master-thread",
                        "authority": "master_decision",
                        "access_scope": "owner_bounded",
                        "filter_ref": str(task_root / "master-return-disposition.json"),
                        "current_head_ref": str(task_root / "master-return-current-head.json"),
                        "history_ref": str(task_root / "master-return-history.jsonl"),
                        "claim_limit": "Currentness is owner evidence, not dashboard authority.",
                    },
                    "handoff_glob": "*-handoff.json",
                    "wake_glob": "*.wake.json",
                    "ignored_handoff_names": [],
                    "ignored_wake_names": [],
                },
                "pressure": {
                    **self._owner("master-thread", "master_decision", "master_decision_disposition"),
                    "path": str(pressure),
                    "expected_schema_version": "aoa_dashboard_pressure_context_v1",
                },
            },
        }
        path = self.root / f"{label}.binding.json"
        path.write_text(json.dumps(binding), encoding="utf-8")
        return path, binding

    def test_two_distinct_runtime_bindings_select_without_source_edits(self) -> None:
        binding_a, _ = self._binding("alpha", "goal-alpha", "thread-alpha")
        binding_b, _ = self._binding("beta", "goal-beta", "thread-beta")

        selected_a = load_config(binding_a)
        selected_b = load_config(binding_b)

        self.assertEqual(selected_a["runtime_binding_state"], "bound")
        self.assertEqual(selected_b["runtime_binding_state"], "bound")
        self.assertEqual(selected_a["goal_id"], "goal-alpha")
        self.assertEqual(selected_b["goal_id"], "goal-beta")
        self.assertEqual(selected_a["current_correlation"]["master_thread_id"], "thread-alpha")
        self.assertEqual(selected_b["current_correlation"]["master_thread_id"], "thread-beta")
        self.assertNotEqual(selected_a["goal_anchor_path"], selected_b["goal_anchor_path"])
        self.assertNotEqual(selected_a["goal_catalog_source"]["path"], selected_b["goal_catalog_source"]["path"])
        self.assertNotEqual(selected_a["pressure_source"]["path"], selected_b["pressure_source"]["path"])

    def test_goal_anchor_swap_and_digest_drift_fail_closed(self) -> None:
        binding_a, payload_a = self._binding("alpha", "goal-alpha", "thread-alpha")
        binding_b, _ = self._binding("beta", "goal-beta", "thread-beta")
        beta_anchor = Path(json.loads(binding_b.read_text(encoding="utf-8"))["sources"]["goal_anchor"]["path"])

        swapped = copy.deepcopy(payload_a)
        swapped["sources"]["goal_anchor"]["path"] = str(beta_anchor)
        swapped["sources"]["goal_anchor"]["expected_sha256"] = hashlib.sha256(beta_anchor.read_bytes()).hexdigest()
        swapped_path = self.root / "swapped-anchor.json"
        swapped_path.write_text(json.dumps(swapped), encoding="utf-8")
        swapped_result = load_config(swapped_path)
        self.assertEqual(swapped_result["runtime_binding_state"], "invalid")
        self.assertIn("runtime_binding_goal_anchor_goal_mismatch", swapped_result["runtime_binding_observation"]["diagnostics"])
        self.assertIsNone(swapped_result.get("goal_id"))

        drifted = copy.deepcopy(payload_a)
        drifted["sources"]["goal_anchor"]["path"] = str(beta_anchor)
        drifted_path = self.root / "drifted-anchor.json"
        drifted_path.write_text(json.dumps(drifted), encoding="utf-8")
        drifted_result = load_config(drifted_path)
        self.assertEqual(drifted_result["runtime_binding_state"], "stale")
        self.assertIn("runtime_binding_goal_anchor_stale", drifted_result["runtime_binding_observation"]["diagnostics"])
        self.assertIsNone(drifted_result.get("goal_id"))
        self.assertTrue(binding_a.is_file())

    def test_schema_unknown_type_duplicate_and_contradictory_inputs_are_distinct(self) -> None:
        binding_path, valid = self._binding("shape", "goal-shape", "thread-shape")

        unknown = copy.deepcopy(valid)
        unknown["unexpected_field"] = True
        unknown_path = self.root / "unknown-field.json"
        unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
        unknown_result = load_config(unknown_path)
        self.assertEqual(unknown_result["runtime_binding_state"], "invalid")
        self.assertTrue(any("schema_unknown_field" in item for item in unknown_result["runtime_binding_observation"]["diagnostics"]))

        malformed = copy.deepcopy(valid)
        malformed["selected_goal"]["goal_id"] = 17
        malformed_path = self.root / "malformed-type.json"
        malformed_path.write_text(json.dumps(malformed), encoding="utf-8")
        malformed_result = load_config(malformed_path)
        self.assertEqual(malformed_result["runtime_binding_state"], "invalid")
        self.assertTrue(any("schema_type_invalid" in item for item in malformed_result["runtime_binding_observation"]["diagnostics"]))

        contradictory = copy.deepcopy(valid)
        contradictory["state"] = "current"
        contradictory["currentness"] = "current_at_read"
        contradictory_path = self.root / "contradictory-currentness.json"
        contradictory_path.write_text(json.dumps(contradictory), encoding="utf-8")
        contradictory_result = load_config(contradictory_path)
        self.assertEqual(contradictory_result["runtime_binding_state"], "invalid")
        self.assertIn("runtime_binding_currentness_invalid", contradictory_result["runtime_binding_observation"]["diagnostics"])

        duplicate_path = self.root / "duplicate-name.json"
        raw = json.dumps(valid).replace(
            '"state": "current_at_read"',
            '"state": "stale", "state": "current_at_read"',
            1,
        )
        duplicate_path.write_text(raw, encoding="utf-8")
        duplicate_result = load_config(duplicate_path)
        self.assertEqual(duplicate_result["runtime_binding_state"], "invalid")
        self.assertIn("runtime_binding_duplicate_json_object_name:state", duplicate_result["runtime_binding_observation"]["diagnostics"])
        self.assertTrue(binding_path.is_file())

    def test_current_route_requires_explicit_globs_and_historical_missing_globs_stays_deferred(self) -> None:
        binding_path, payload = self._binding("selectors", "goal-selectors", "thread-selectors")
        payload["sources"]["correlation"].pop("handoff_glob")
        current_path = self.root / "missing-selectors.json"
        current_path.write_text(json.dumps(payload), encoding="utf-8")
        current_result = load_config(current_path)
        self.assertEqual(current_result["runtime_binding_state"], "invalid")
        self.assertTrue(any("schema_missing_field" in item for item in current_result["runtime_binding_observation"]["diagnostics"]))
        self.assertTrue(binding_path.is_file())

        historical = load_config(Path(__file__).resolve().parents[1] / "config" / "demo" / "first-slice.json")
        historical["current_correlation"].pop("handoff_glob", None)
        historical["current_correlation"].pop("wake_glob", None)
        historical_result = observe_current_correlation(historical)
        self.assertEqual(historical_result["state"], "deferred")
        self.assertIn("historical_correlation_selectors_missing", historical_result["degradation"])

    @patch("aoa_dashboard.owner_context.discover_control_socket", side_effect=CodexGoalUnavailable("owner_socket_missing"))
    def test_bound_projection_uses_selected_goal_and_owner_sources(self, _socket: object) -> None:
        binding_path, _ = self._binding("alpha", "goal-alpha", "thread-alpha")
        projection = build_projection(binding_path)

        self.assertEqual(projection["runtime_binding"]["state"], "bound")
        self.assertEqual(projection["sources"][0]["state"], "bound")
        self.assertEqual(projection["goal"]["goal_id"], "goal-alpha")
        self.assertEqual(projection["goal"]["master_thread_id"], "thread-alpha")
        self.assertEqual(projection["goal_topology"]["state"], "bound")
        self.assertEqual(projection["goal_topology"]["nodes"][0]["title"], "alpha topology")
        self.assertEqual(projection["goal_catalog"]["items"][0]["ref"], "goal-alpha")
        self.assertEqual(projection["pressure_inbox"]["goal_id"], "goal-alpha")

    @patch("aoa_dashboard.owner_context.discover_control_socket", side_effect=CodexGoalUnavailable("owner_socket_missing"))
    def test_no_binding_fails_closed_without_sentinel_goal(self, _socket: object) -> None:
        config = load_config()
        projection = build_projection()

        self.assertEqual(config["runtime_binding_state"], "missing")
        self.assertIsNone(projection["goal"]["goal_id"])
        self.assertIsNone(projection["goal"]["master_thread_id"])
        self.assertEqual(projection["goal_topology"]["state"], "missing")
        self.assertEqual(projection["goal_catalog"]["state"], "missing")
        self.assertEqual(projection["correlation_read_model"]["status"], "missing")
        self.assertEqual(projection["pressure_inbox"]["status"], "missing")
        self.assertIsNone(projection["pressure_inbox"]["goal_id"])
        self.assertNotIn("unselected-goal", json.dumps(projection))

    @patch("aoa_dashboard.owner_context.discover_control_socket", side_effect=CodexGoalUnavailable("owner_socket_missing"))
    def test_malformed_conflicting_stale_and_missing_bindings_fail_closed(self, _socket: object) -> None:
        valid_path, valid = self._binding("alpha", "goal-alpha", "thread-alpha")

        malformed = self.root / "malformed.json"
        malformed.write_text("{\"schema_version\": \"aoa_dashboard_runtime_binding_v1\"}", encoding="utf-8")
        self.assertEqual(load_config(malformed)["runtime_binding_state"], "invalid")
        malformed_value = self.root / "malformed-value.json"
        malformed_value.write_text("[]", encoding="utf-8")
        self.assertEqual(load_config(malformed_value)["runtime_binding_state"], "invalid")

        conflicting = copy.deepcopy(valid)
        conflicting["sources"]["correlation"]["master_thread_id"] = "thread-other"
        conflict_path = self.root / "conflicting.json"
        conflict_path.write_text(json.dumps(conflicting), encoding="utf-8")
        self.assertEqual(load_config(conflict_path)["runtime_binding_state"], "invalid")

        forged = copy.deepcopy(valid)
        forged["owner"] = "dashboard-shaped-publisher"
        forged_path = self.root / "forged.json"
        forged_path.write_text(json.dumps(forged), encoding="utf-8")
        self.assertEqual(load_config(forged_path)["runtime_binding_state"], "invalid")

        stale = copy.deepcopy(valid)
        stale["state"] = "stale"
        stale["currentness"] = "stale"
        stale_path = self.root / "stale.json"
        stale_path.write_text(json.dumps(stale), encoding="utf-8")
        stale_config = load_config(stale_path)
        self.assertEqual(stale_config["runtime_binding_state"], "stale")
        self.assertIsNone(stale_config.get("goal_id"))
        self.assertEqual(build_projection(stale_path)["correlation"]["state"], "stale")

        missing = load_config(self.root / "missing.json")
        self.assertEqual(missing["runtime_binding_state"], "missing")
        self.assertIsNone(missing.get("goal_id"))
        self.assertTrue(valid_path.is_file())

    @patch("aoa_dashboard.owner_context.discover_control_socket", side_effect=CodexGoalUnavailable("owner_socket_missing"))
    def test_mismatched_topology_and_pressure_are_not_borrowed(self, _socket: object) -> None:
        binding_a, payload_a = self._binding("alpha", "goal-alpha", "thread-alpha")
        binding_b, _ = self._binding("beta", "goal-beta", "thread-beta")
        payload_b = json.loads(binding_b.read_text(encoding="utf-8"))
        borrowed_topology = Path(payload_a["sources"]["correlation"]["task_local_dir"]) / "borrowed-topology.json"
        borrowed_topology.write_text(
            json.dumps(
                {
                    "schema_version": "aoa_dashboard_goal_space_task_dag_v1",
                    "goal_ref": "thread-beta",
                    "updated_at": "2026-08-23T04:00:00Z",
                    "claim_limit": "Task-local planning only; no proof or acceptance.",
                    "nodes": [{"id": "GS1", "title": "Borrowed topology", "state": "active", "depends_on": []}],
                }
            ),
            encoding="utf-8",
        )
        payload_a["sources"]["topology"]["relative_path"] = borrowed_topology.name
        payload_a["sources"]["pressure"]["path"] = payload_b["sources"]["pressure"]["path"]
        binding_a.write_text(json.dumps(payload_a), encoding="utf-8")

        projection = build_projection(binding_a)

        self.assertEqual(projection["goal"]["goal_id"], "goal-alpha")
        self.assertEqual(projection["goal_topology"]["state"], "invalid")
        self.assertIn("topology_goal_mismatch", projection["goal_topology"]["diagnostics"])
        self.assertEqual(projection["pressure_source"]["state"], "invalid")
        self.assertEqual(projection["pressure_inbox"]["status"], "invalid")
        self.assertEqual(projection["pressure_inbox"]["items"], [])
        self.assertNotIn("goal-beta", json.dumps(projection["goal_topology"]))

    def test_historical_demo_is_explicit_and_default_scan_stays_current_instance_free(self) -> None:
        root = Path(__file__).resolve().parents[1]
        demo = load_config(root / "config" / "demo" / "first-slice.json")
        self.assertEqual(demo["runtime_binding_state"], "historical_demo_opt_in")
        self.assertEqual(demo["runtime_binding_observation"]["state"], "deferred")
        self.assertEqual(demo["runtime_binding_observation"]["selected_goal"]["goal_id"], "aoa-dashboard-goal-01a00722-20260815")

        default_text = (root / "config" / "bootstrap.json").read_text(encoding="utf-8")
        self.assertNotIn("01a00722-0291-72e0-8310-559da802d6e1", default_text)
        self.assertNotIn("aoa-dashboard-goal-01a00722-20260815", default_text)
        self.assertNotIn("/srv/abyss-machine/tmp/ai/", default_text)
        self.assertNotIn("/.codex/attachments/", default_text)


if __name__ == "__main__":
    unittest.main()
