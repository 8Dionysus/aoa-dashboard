from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.owner_context import observe_codex_goal_context  # noqa: E402
from aoa_dashboard.codex_goal import CodexGoalUnavailable  # noqa: E402


THREAD = "01a00722-0291-72e0-8310-559da802d6e1"


def thread(thread_id: str, *, parent: str | None = None) -> dict:
    return {
        "id": thread_id,
        "sessionId": "session:test",
        "parentThreadId": parent,
        "forkedFromId": None,
        "source": "app-server",
        "threadSource": "agent_control",
        "agentNickname": "Luna",
        "agentRole": "coder",
        "status": "idle",
        "createdAt": 100,
        "updatedAt": 200,
        "recencyAt": 200,
        "ephemeral": False,
    }


class ContextRpc:
    last_calls: list[tuple[str, dict]] = []
    goal = {
        "goal": {
            "threadId": THREAD,
            "objective": "Build the bounded Goal context",
            "status": "active",
            "tokenBudget": 1000,
            "tokensUsed": 10,
            "timeUsedSeconds": 20,
            "createdAt": 100,
            "updatedAt": 200,
        }
    }
    read = {"thread": thread(THREAD)}
    direct = {"data": [thread("child-thread", parent=THREAD)], "nextCursor": None}
    descendants = {"data": [thread("descendant-thread", parent=THREAD)], "nextCursor": None}

    def __init__(self, _path: Path) -> None:
        self.calls: list[tuple[str, dict]] = []
        ContextRpc.last_calls = self.calls

    def __enter__(self) -> "ContextRpc":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def call(self, method: str, params: dict) -> dict:
        self.calls.append((method, params))
        if method == "initialize":
            return {"userAgent": "test"}
        if method == "thread/goal/get":
            return self.goal
        if method == "thread/read":
            return self.read
        if method == "thread/list":
            return self.direct if "parentThreadId" in params else self.descendants
        raise AssertionError(method)

    def notify(self, method: str) -> None:
        self.calls.append((method, {}))


class OwnerContextTests(unittest.TestCase):
    def config(self, *, thread_enabled: bool = True) -> dict:
        return {
            "owner_goal_source": {"enabled": True},
            "owner_thread_source": {"enabled": thread_enabled},
            "current_correlation": {"master_thread_id": THREAD},
        }

    def assert_schema(self, value: dict) -> None:
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts" / "codex_goal_thread_projection.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema).validate(value)

    def test_exact_goal_thread_and_two_relation_queries_are_current_at_read(self) -> None:
        observed = observe_codex_goal_context(self.config(), rpc_factory=ContextRpc)
        self.assert_schema(observed)
        self.assertEqual(observed["state"], "bound")
        self.assertEqual(observed["goal_ref"]["thread_id"], THREAD)
        self.assertEqual(observed["goal_projection"]["goal"]["thread_id"], THREAD)
        self.assertEqual(observed["thread"]["thread"]["thread_id"], THREAD)
        self.assertEqual(observed["relations"]["spawn_parent"]["items"][0]["thread_id"], "child-thread")
        self.assertEqual(observed["relations"]["history_fork"]["items"][0]["thread_id"], "descendant-thread")
        self.assertEqual(observed["relations"]["spawn_parent"]["source"]["query"], {"parentThreadId": THREAD})
        self.assertEqual(observed["relations"]["history_fork"]["source"]["query"], {"ancestorThreadId": THREAD})
        initialize = next(params for method, params in ContextRpc.last_calls if method == "initialize")
        self.assertEqual(initialize["capabilities"], {"experimentalApi": True})
        self.assertTrue(all(ref["currentness"] == "current_at_read" for ref in observed["evidence_refs"]))

    def test_two_synthetic_goal_identities_bind_without_source_changes(self) -> None:
        for synthetic_thread in (THREAD, "thread:synthetic-two"):
            synthetic_goal = {
                "goal": {
                    "threadId": synthetic_thread,
                    "objective": f"Objective for {synthetic_thread}",
                    "status": "active",
                    "tokenBudget": 1000,
                    "tokensUsed": 10,
                    "timeUsedSeconds": 20,
                    "createdAt": 100,
                    "updatedAt": 200,
                }
            }
            rpc_type = type(
                "SyntheticContextRpc",
                (ContextRpc,),
                {
                    "goal": synthetic_goal,
                    "read": {"thread": thread(synthetic_thread)},
                    "direct": {"data": [thread(f"child:{synthetic_thread}", parent=synthetic_thread)], "nextCursor": None},
                    "descendants": {"data": [thread(f"history:{synthetic_thread}", parent=synthetic_thread)], "nextCursor": None},
                },
            )
            config = self.config()
            config["current_correlation"] = {"master_thread_id": synthetic_thread}
            observed = observe_codex_goal_context(config, rpc_factory=rpc_type)
            self.assertEqual(observed["state"], "bound")
            self.assertEqual(observed["goal_projection"]["goal"]["thread_id"], synthetic_thread)
            self.assertEqual(observed["thread"]["thread"]["thread_id"], synthetic_thread)

    def test_partial_relation_page_is_deferred_without_claiming_completeness(self) -> None:
        class PartialRpc(ContextRpc):
            direct = {"data": [thread("child-thread", parent=THREAD)], "nextCursor": "opaque-next"}

        observed = observe_codex_goal_context(self.config(), rpc_factory=PartialRpc)
        self.assert_schema(observed)
        self.assertEqual(observed["state"], "deferred")
        relation = observed["relations"]["spawn_parent"]
        self.assertEqual(relation["state"], "deferred")
        self.assertFalse(relation["complete_for_query"])
        self.assertEqual(relation["next_cursor"], "opaque-next")
        self.assertEqual(relation["currentness"], "current_at_read")

    def test_thread_identity_mismatch_is_invalid_but_goal_is_not_rewritten(self) -> None:
        class MismatchRpc(ContextRpc):
            read = {"thread": thread("other-thread")}

        observed = observe_codex_goal_context(self.config(), rpc_factory=MismatchRpc)
        self.assert_schema(observed)
        self.assertEqual(observed["state"], "invalid")
        self.assertEqual(observed["thread"]["state"], "invalid")
        self.assertIn("owner_thread_identity_mismatch", observed["diagnostics"])
        self.assertEqual(observed["goal_projection"]["state"], "bound")
        self.assertEqual(observed["goal_projection"]["goal"]["thread_id"], THREAD)

    def test_goal_identity_mismatch_is_invalid_in_context_and_goal_projection(self) -> None:
        class MismatchGoalRpc(ContextRpc):
            goal = {"goal": {**ContextRpc.goal["goal"], "threadId": "other-thread"}}

        observed = observe_codex_goal_context(self.config(), rpc_factory=MismatchGoalRpc)
        self.assert_schema(observed)
        self.assertEqual(observed["state"], "invalid")
        self.assertEqual(observed["goal_projection"]["state"], "invalid")
        self.assertIn("owner_goal_identity_mismatch", observed["diagnostics"])

    def test_goal_transport_missing_and_thread_binding_disabled_preserve_independent_states(self) -> None:
        disabled = observe_codex_goal_context(self.config(thread_enabled=False), rpc_factory=ContextRpc)
        self.assertEqual(disabled["goal_projection"]["state"], "bound")
        self.assertEqual(disabled["thread"]["state"], "missing")
        self.assertEqual(disabled["relations"]["spawn_parent"]["state"], "missing")

        class MissingRpc(ContextRpc):
            def call(self, method: str, params: dict) -> dict:
                if method == "initialize":
                    return {"userAgent": "test"}
                raise CodexGoalUnavailable("owner_transport_unavailable")

        observed = observe_codex_goal_context(self.config(), rpc_factory=MissingRpc)
        self.assertEqual(observed["state"], "unknown")
        self.assertEqual(observed["goal_projection"]["state"], "unknown")
        self.assertIn("owner_transport_unavailable", observed["diagnostics"])


if __name__ == "__main__":
    unittest.main()
