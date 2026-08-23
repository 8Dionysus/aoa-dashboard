from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.codex_goal import observe_codex_goal  # noqa: E402


THREAD = "01a00722-0291-72e0-8310-559da802d6e1"


class FakeRpc:
    response = {
        "goal": {
            "threadId": THREAD,
            "objective": "Преобразовать aoa-dashboard в качественную Goal-centric desktop-среду AbyssOS: подробности далее",
            "status": "active",
            "tokenBudget": None,
            "tokensUsed": 123,
            "timeUsedSeconds": 456,
            "createdAt": 100,
            "updatedAt": 200,
        }
    }

    def __init__(self, _path: Path) -> None:
        self.calls: list[str] = []

    def __enter__(self) -> "FakeRpc":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def call(self, method: str, _params: dict[str, object]) -> dict:
        self.calls.append(method)
        if method == "initialize":
            return {"userAgent": "test"}
        if method == "thread/goal/get":
            return self.response
        raise AssertionError(method)

    def notify(self, method: str) -> None:
        self.calls.append(method)


class CodexGoalTests(unittest.TestCase):
    def config(self) -> dict:
        return {
            "owner_goal_source": {"enabled": True},
            "current_correlation": {"master_thread_id": THREAD},
        }

    def test_exact_owner_goal_is_projected_without_mutation(self) -> None:
        with patch(
            "aoa_dashboard.codex_goal.discover_control_socket",
            return_value=Path("/tmp/app-server.sock"),
        ):
            observed = observe_codex_goal(self.config(), rpc_factory=FakeRpc)
        self.assertEqual(observed["state"], "bound")
        self.assertEqual(observed["currentness"], "current_at_read")
        self.assertEqual(observed["goal"]["status"], "active")
        self.assertEqual(
            observed["goal"]["title"],
            "Преобразовать aoa-dashboard в качественную Goal-centric desktop-среду AbyssOS",
        )
        self.assertEqual(observed["source"]["method"], "thread/goal/get")

    def test_identity_mismatch_fails_closed(self) -> None:
        class MismatchRpc(FakeRpc):
            response = {"goal": {**FakeRpc.response["goal"], "threadId": "other"}}

        with patch(
            "aoa_dashboard.codex_goal.discover_control_socket",
            return_value=Path("/tmp/app-server.sock"),
        ):
            observed = observe_codex_goal(self.config(), rpc_factory=MismatchRpc)
        self.assertEqual(observed["state"], "unknown")
        self.assertIsNone(observed["goal"])
        self.assertIn("owner_goal_identity_mismatch", observed["diagnostics"])

    def test_disabled_binding_does_not_probe_owner_runtime(self) -> None:
        observed = observe_codex_goal(
            {"owner_goal_source": {"enabled": False}, "current_correlation": {}},
            rpc_factory=FakeRpc,
        )
        self.assertEqual(observed["state"], "missing")
        self.assertEqual(observed["diagnostics"], ["owner_binding_disabled"])


if __name__ == "__main__":
    unittest.main()
