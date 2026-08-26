from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.goal_context import (  # noqa: E402
    THREAD_OWNER_COMMIT,
    observe_goal_context,
)
from aoa_dashboard.projection import build_projection  # noqa: E402


GOAL = "goal:exact"
THREAD = "thread:exact"
CANDIDATE_ITEM = Path(__file__).resolve().parent / "fixtures" / "goal_context" / "session_memory_candidate_item.json"


def ref(owner: str, object_id: str, schema: str = "owner_ref_v1") -> dict[str, str]:
    return {
        "owner_repo": owner,
        "object_id": object_id,
        "source_ref": f"repo:{owner}/public/{object_id}",
        "schema_version": schema,
        "content_digest": "sha256:" + (object_id.encode().hex() + "0" * 64)[:64],
    }


def board_payload(*, state: str = "current", goal: str = GOAL, thread: str = THREAD) -> dict:
    item = {
        "item_ref": "item-ref:one",
        "item_id": "item:one",
        "item_id_state": "available",
        "item_kind": "codex_thread_item_observation",
        "owner_event_kind": None,
        "owner_item_type": "agentMessage",
        "review_state": "reviewed_public_safe",
        "body_state": "withheld",
        "order": 0,
        "order_state": "owner_page_order",
        "goal_ref": goal,
        "thread_id": thread,
        "observed_at": "2026-08-23T12:00:00Z",
        "source_ref": "aoa-session-memory:goal-thread-board",
        "evidence_ref": "evidence:item:one",
        "redacted_fields": ["prompt", "transcript_body"],
        "item_digest": "sha256:" + "1" * 64,
        "body": "PRIVATE_TRANSCRIPT_MUST_NOT_APPEAR",
        "prompt": "PRIVATE_PROMPT_MUST_NOT_APPEAR",
    }
    relation = {
        "relation_ref": "relation-ref:one",
        "relation_kind": "spawn_parent",
        "from_thread_id": thread,
        "to_thread_id": "thread:child",
        "from_thread_id_state": "available",
        "to_thread_id_state": "available",
        "relation_state": "available",
        "semantic_branch_state": "missing",
        "order": 0,
        "source_ref": "aoa-session-memory:goal-thread-board",
        "goal_ref": goal,
        "evidence_ref": "evidence:relation:one",
        "redacted_fields": ["cwd", "path"],
        "relation_digest": "sha256:" + "2" * 64,
    }
    return {
        "schema_version": "aoa_session_memory_goal_thread_board_v1",
        "publication_schema_version": "aoa_session_memory_goal_thread_board_public_v1",
        "artifact_type": "goal_thread_board_projection",
        "generated_at": "2026-08-23T12:00:00Z",
        "ok": state == "current",
        "state": state,
        "currentness": "current_at_read" if state == "current" else state,
        "publication_state": "bound" if state == "current" else state,
        "goal_ref": goal,
        "master_thread_id": thread,
        "exact_binding": {"goal_ref": goal, "master_thread_id": thread, "equal": True, "query_mode": "exact_only"},
        "source": {"owner": "aoa-session-memory", "ref": "aoa-session-memory:goal-thread-board", "currentness": state},
        "owner_read": {
            "owner": "codex-app-server",
            "state": "bound" if state == "current" else state,
            "currentness": "current_at_read" if state == "current" else state,
            "source": {"owner": "codex-app-server", "methods": ["thread/read", "thread/items/list"], "currentness": "current_at_read"},
            "goal": {"thread_id": thread, "status": "active", "created_at": 1, "updated_at": 2},
            "thread": {"thread_id": thread, "status": "idle", "parentThreadId_state": "opaque"},
            "observation_digest": "sha256:" + "3" * 64,
            "diagnostics": [],
        },
        "snapshot": {"snapshot_ref": "sha256:" + "4" * 64, "snapshot_digest": "sha256:" + "4" * 64, "generated_at": "2026-08-23T12:00:00Z", "source_freshness": "current", "projection_freshness": state, "immutable": True},
        "pagination": {"mode": "immutable_snapshot", "cursor": None, "next_cursor": None, "owner_next_cursor": None, "complete_for_query": True, "page_size": 50, "supports_immutable_snapshot": True, "owner_page_complete": True},
        "ordering": {"kind": "source_page_order", "item_order_is_semantic": False, "event_ordering": {"state": "missing", "kind": "unavailable", "reason": "not a sequence"}, "watermark": {}},
        "page": {"offset": 0, "item_count": 1, "page_digest": "sha256:" + "5" * 64},
        "snapshot_digest": "sha256:" + "4" * 64,
        "page_digest": "sha256:" + "5" * 64,
        "source_item_count": 1,
        "item_count": 1,
        "total_item_count": 1,
        "relation_state": "complete" if state == "current" else state,
        "relations": [relation] if state == "current" else [],
        "branch": {"state": "missing", "branch_ref": None, "lifecycle_state": None, "reason": "no_canonical_goal_branch_publisher"},
        "items": [item] if state == "current" else [],
        "diagnostics": [],
        "omissions": {key: True for key in ("prompt", "transcript_body", "objective", "raw_paths", "private_metadata", "command_text", "tool_arguments", "tool_results", "process_identity", "actor_identity", "model_identity")},
        "privacy": {"scope": "owner_bounded_public_safe", "prohibited_join_keys": ["cwd", "path", "pid", "title", "timestamp_only"], "no_transcript_body": True, "no_raw_paths": True, "no_private_metadata": True, "no_actor_inference": True},
        "claim_limit": "Exact public-safe board.",
    }


def graph_payload(*, state: str = "current", scope: dict | None = None, synthetic: bool = False) -> dict:
    scope = scope or {"goal_ref": ref("aoa-agents", "goal-ref"), "goal_instance_ref": ref("aoa-agents", "goal-instance"), "master_thread_ref": ref("aoa-agents", "thread-ref")}
    dimensions = {}
    for name, object_id in {
        "identity": "actor-ref",
        "obligation_role": "role-ref",
        "task_assignment": "assignment-ref",
        "model_realization": "model-ref",
        "runtime_incarnation": "incarnation-ref",
    }.items():
        dimensions[name] = {
            "state": "present",
            "owner_ref": ref("aoa-agents", object_id),
            "observed_at": "2026-08-23T12:00:00Z",
            "claim_limit": "Dimension only.",
            "value": {"human_display_name": "PRIVATE_DISPLAY_NAME_MUST_NOT_APPEAR"},
        }
    relation = {
        "schema_version": "aoa_agents_goal_participant_relation_v1",
        "kind": "aoa_agents_goal_participant_relation",
        "evidence_class": "synthetic_public_example" if synthetic else "owner_published",
        "relation_id": "rel-record:one",
        "relation_key": {"schema_version": "aoa_agents_goal_participant_relation_key_v1", "key_id": "rel:publisher-owned", "publisher_ref": ref("aoa-agents", "publisher"), "endpoint_refs": [ref("aoa-agents", "one"), ref("aoa-agents", "two"), ref("aoa-agents", "three")], "content_digest": "sha256:" + "6" * 64},
        "scope": scope,
        "dimensions": dimensions,
        "privacy_omissions": {"state": "applied", "omitted_fields": ["human_display_name", "raw_prompt", "secrets", "cwd", "path", "pid", "terminal_title", "unreviewed_model_metadata"], "policy_ref": ref("aoa-agents", "privacy")},
        "claim_limit": "Exact relation dimensions.",
    }
    return {
        "schema_version": "aoa_agents_goal_participant_graph_v1",
        "kind": "aoa_agents_goal_participant_graph",
        "owner_repo": "aoa-agents",
        "source": {"source_ref": ref("aoa-agents", "source"), "contract_ref": ref("aoa-agents", "contract")},
        "currentness": {"state": state, "reason": "owner publication state"},
        "pagination": {"page_index": 0, "page_size": 100, "has_more": False, "next_cursor_ref": None},
        "privacy_omissions": {"state": "applied", "omitted_fields": ["human_display_name", "raw_prompt", "secrets", "cwd", "path", "pid", "terminal_title", "unreviewed_model_metadata"], "policy_ref": ref("aoa-agents", "privacy")},
        "fallback_policy": {"state": "disabled", "reason": "No fallback."},
        "records": [relation] if state == "current" else [],
        "claim_limit": "Exact graph projection.",
    }


def candidate_session_memory_item() -> dict:
    return json.loads(CANDIDATE_ITEM.read_text(encoding="utf-8"))["item"]


class GoalContextConsumerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scope = {"goal_ref": ref("aoa-agents", "goal-ref"), "goal_instance_ref": ref("aoa-agents", "goal-instance"), "master_thread_ref": ref("aoa-agents", "thread-ref")}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, name: str, value: dict) -> tuple[Path, str]:
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def config(self, board: dict | None, graph: dict | None, *, scope: dict | None = None) -> dict:
        bindings: dict[str, dict] = {}
        if board is not None:
            path, digest = self.write("thread-board.json", board)
            bindings["thread_board"] = {"owner": "aoa-session-memory", "path": str(path), "expected_sha256": digest, "owner_commit": THREAD_OWNER_COMMIT}
        if graph is not None:
            path, digest = self.write("participant-graph.json", graph)
            bindings["participant_graph"] = {"owner": "aoa-agents", "path": str(path), "expected_sha256": digest, "owner_commit": "db7b7f7ac7465406b3a90ca26d3cf31ac81706fe", "goal_scope": scope} if scope is not None else {"owner": "aoa-agents", "path": str(path), "expected_sha256": digest, "owner_commit": "db7b7f7ac7465406b3a90ca26d3cf31ac81706fe"}
        return {"goal_context_sources": bindings}

    def test_missing_sources_remain_missing_without_fabricated_participants_or_items(self) -> None:
        observed = observe_goal_context({}, goal_ref=GOAL, master_thread_id=THREAD)
        self.assertEqual(observed["state"], "missing")
        self.assertEqual(observed["thread_board"]["items"], [])
        self.assertEqual(observed["participant_graph"]["records"], [])
        self.assertNotIn("Participant 1", json.dumps(observed))

    def test_current_board_and_graph_are_allowlisted_and_private_values_do_not_cross_projection(self) -> None:
        observed = observe_goal_context(self.config(board_payload(), graph_payload(scope=self.scope), scope=self.scope), goal_ref=GOAL, master_thread_id=THREAD)
        self.assertEqual(observed["state"], "current")
        self.assertEqual(observed["thread_board"]["state"], "current")
        self.assertEqual(observed["participant_graph"]["state"], "current")
        self.assertEqual(len(observed["thread_board"]["items"]), 1)
        self.assertEqual(len(observed["participant_graph"]["records"]), 1)
        serialized = json.dumps(observed)
        self.assertNotIn("PRIVATE_TRANSCRIPT", serialized)
        self.assertNotIn("PRIVATE_PROMPT", serialized)
        self.assertNotIn("PRIVATE_DISPLAY_NAME", serialized)
        self.assertNotIn("endpoint_refs", serialized)
        self.assertEqual(observed["participant_graph"]["records"][0]["relation_key"]["state"], "present")

    def test_exact_mismatch_and_digest_drift_fail_closed(self) -> None:
        board = board_payload(goal="goal:other")
        graph = graph_payload(scope=self.scope)
        observed = observe_goal_context(self.config(board, graph, scope=self.scope), goal_ref=GOAL, master_thread_id=THREAD)
        self.assertEqual(observed["thread_board"]["state"], "invalid")
        self.assertEqual(observed["thread_board"]["items"], [])
        path, _digest = self.write("drift.json", board_payload())
        config = {"goal_context_sources": {"thread_board": {"owner": "aoa-session-memory", "path": str(path), "expected_sha256": "0" * 64}}}
        self.assertEqual(observe_goal_context(config, goal_ref=GOAL, master_thread_id=THREAD)["thread_board"]["state"], "stale")

    def test_deferred_graph_and_missing_scope_are_human_negative_states(self) -> None:
        deferred = graph_payload(state="deferred")
        observed = observe_goal_context(self.config(board_payload(), deferred), goal_ref=GOAL, master_thread_id=THREAD)
        self.assertEqual(observed["state"], "deferred")
        self.assertEqual(observed["participant_graph"]["records"], [])
        current_without_scope = observe_goal_context(self.config(board_payload(), graph_payload(scope=self.scope), scope=None), goal_ref=GOAL, master_thread_id=THREAD)
        self.assertEqual(current_without_scope["participant_graph"]["state"], "deferred")
        self.assertEqual(current_without_scope["participant_graph"]["records"], [])

    def test_exact_candidate_item_with_nullable_observed_at_is_admitted_with_degraded_freshness(self) -> None:
        board = board_payload()
        board["items"] = [candidate_session_memory_item()]
        board["source_item_count"] = 1
        board["item_count"] = 1
        board["total_item_count"] = 1
        observed = observe_goal_context(self.config(board, graph_payload(scope=self.scope), scope=self.scope), goal_ref=GOAL, master_thread_id=THREAD)
        thread = observed["thread_board"]
        self.assertEqual(observed["state"], "deferred")
        self.assertEqual(thread["state"], "current")
        self.assertEqual(thread["currentness"], "deferred")
        self.assertEqual(thread["item_freshness"], {"state": "missing", "missing_observed_at_count": 1})
        self.assertEqual(len(thread["items"]), 1)
        self.assertIsNone(thread["items"][0]["observed_at"])
        self.assertEqual(thread["items"][0]["observed_at_state"], "missing")
        self.assertIn("thread_item_observed_at_missing", thread["diagnostics"])
        self.assertNotIn("PRIVATE", json.dumps(observed))

    def test_malformed_thread_items_and_wrappers_fail_closed_without_private_leakage(self) -> None:
        valid = board_payload()["items"][0]
        cases = {
            "missing_identity": {key: value for key, value in valid.items() if key != "item_id"},
            "wrong_wrapper": {"item": copy.deepcopy(valid), "turnId": "turn:private-correlation"},
            "unsupported_item_type": {**valid, "owner_item_type": "privateFutureType"},
            "conflicting_thread": {**valid, "thread_id": "thread:other"},
            "malformed_digest": {**valid, "item_digest": "sha256:not-a-digest"},
        }
        for label, item in cases.items():
            with self.subTest(label=label):
                board = board_payload()
                board["items"] = [item]
                observed = observe_goal_context(self.config(board, None), goal_ref=GOAL, master_thread_id=THREAD)
                self.assertEqual(observed["thread_board"]["state"], "invalid")
                self.assertEqual(observed["thread_board"]["items"], [])
                self.assertNotIn("turn:private-correlation", json.dumps(observed))
                self.assertNotIn("PRIVATE_TRANSCRIPT", json.dumps(observed))

    def test_synthetic_relation_and_wrong_owner_commit_are_not_admitted(self) -> None:
        synthetic = observe_goal_context(self.config(None, graph_payload(scope=self.scope, synthetic=True), scope=self.scope), goal_ref=GOAL, master_thread_id=THREAD)
        self.assertEqual(synthetic["participant_graph"]["state"], "invalid")
        config = self.config(None, graph_payload(scope=self.scope), scope=self.scope)
        config["goal_context_sources"]["participant_graph"]["owner_commit"] = "0" * 40
        self.assertEqual(observe_goal_context(config, goal_ref=GOAL, master_thread_id=THREAD)["participant_graph"]["state"], "invalid")

    def test_projection_exposes_context_as_two_source_observations(self) -> None:
        projection = build_projection(str(Path(__file__).resolve().parents[1] / "config" / "demo" / "first-slice.json"))
        self.assertIn("goal_context", projection)
        self.assertEqual({item["id"] for item in projection["sources"] if item["id"] in {"goal-thread-board", "participant-relations"}}, {"goal-thread-board", "participant-relations"})
        self.assertEqual(projection["goal_context"]["thread_board"]["items"], [])
        self.assertEqual(projection["goal_context"]["participant_graph"]["records"], [])


if __name__ == "__main__":
    unittest.main()
