from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.participant_context import project_participant_context  # noqa: E402


THREAD = "thread:exact"


def owner_context() -> dict:
    return {
        "state": "bound",
        "goal_ref": {"thread_id": THREAD, "owner": "codex-app-server"},
        "goal_projection": {"state": "bound"},
        "thread": {"state": "bound", "thread": {"thread_id": THREAD}},
    }


def actor(**changes: object) -> dict:
    value = {
        "actor_key": "return:one",
        "state": "returned",
        "payload_state": "observed",
        "freshness": "current_at_read",
        "identity": {"label": "Luna", "role_id": "external_codex_incarnation", "model_id": "gpt-5.6-luna:max"},
        "task": {"task_id": "task:one", "summary": "Review the Goal context"},
        "correlation": {"master_thread_id": THREAD, "state": "returned"},
        "process": {"state": "observed", "process_id": "731"},
        "session": {"state": "missing"},
        "terminal": {"state": "missing"},
        "wake_return": {"state": "observed"},
        "usage": {"state": "missing"},
        "evidence_refs": [{"ref": "task-local:return", "owner": "aoa-dashboard"}],
    }
    value.update(changes)
    return value


class ParticipantContextTests(unittest.TestCase):
    def assert_schema(self, value: dict) -> None:
        schema = json.loads(
            (Path(__file__).resolve().parents[1] / "contracts" / "participant_context.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema).validate(value)

    def test_dimensions_are_independent_and_candidate_model_is_not_activation(self) -> None:
        observed = project_participant_context(
            {"state": "deferred", "freshness": "current_at_read", "actors": [actor()]},
            owner_context(),
        )
        self.assert_schema(observed)
        participant = observed["participants"][0]
        self.assertEqual(participant["task_context"]["state"], "present")
        self.assertEqual(participant["task_context"]["goal_thread"]["thread_id"], THREAD)
        self.assertEqual(participant["identity"]["state"], "present")
        self.assertEqual(participant["model_realization"]["state"], "unknown")
        self.assertEqual(participant["model_realization"]["candidate_model_id"], "gpt-5.6-luna:max")
        self.assertIsNone(participant["model_realization"]["runtime_subject"])
        self.assertEqual(participant["runtime_evidence"]["state"], "deferred")
        self.assertEqual(observed["state"], "deferred")

    def test_missing_dimensions_do_not_fall_back_to_raw_values(self) -> None:
        missing = actor(
            payload_state="missing",
            identity={},
            task={},
            correlation={},
            process={"state": "missing"},
            session={"state": "missing"},
            terminal={"state": "missing"},
            wake_return={"state": "missing"},
            usage={"state": "missing"},
            evidence_refs=[],
        )
        observed = project_participant_context({"state": "missing", "freshness": "missing", "actors": [missing]}, owner_context())
        participant = observed["participants"][0]
        self.assertEqual(participant["dimension_states"], {"identity": "missing", "task_context": "missing", "model_realization": "missing", "runtime_evidence": "missing"})
        self.assertIsNone(participant["identity"]["display_name"])
        self.assertIsNone(participant["task_context"]["summary"])
        self.assertIsNone(participant["model_realization"]["candidate_model_id"])
        self.assertEqual(observed["state"], "deferred")

    def test_stale_owner_activity_stays_stale_without_becoming_current(self) -> None:
        stale = actor(
            freshness="stale",
            process={"state": "stale", "process_id": "731"},
            wake_return={"state": "stale"},
        )
        observed = project_participant_context(
            {"state": "stale", "freshness": "stale", "actors": [stale]},
            owner_context(),
        )
        self.assert_schema(observed)
        participant = observed["participants"][0]
        self.assertEqual(participant["dimension_states"]["identity"], "stale")
        self.assertEqual(participant["dimension_states"]["task_context"], "stale")
        self.assertEqual(participant["dimension_states"]["model_realization"], "stale")
        self.assertEqual(participant["dimension_states"]["runtime_evidence"], "stale")
        self.assertEqual(observed["state"], "stale")

    def test_mismatched_goal_thread_is_invalid_and_exact_thread_is_withheld(self) -> None:
        observed = project_participant_context(
            {"state": "bound", "freshness": "current_at_read", "actors": [actor(correlation={"master_thread_id": "thread:other"})]},
            owner_context(),
        )
        participant = observed["participants"][0]
        self.assertEqual(participant["task_context"]["state"], "invalid")
        self.assertEqual(participant["task_context"]["goal_thread"]["state"], "invalid")
        self.assertIsNone(participant["task_context"]["goal_thread"]["thread_id"])
        self.assertIn("participant_goal_thread_correlation_mismatch", observed["diagnostics"])
        self.assertEqual(observed["state"], "invalid")

    def test_invalid_owner_thread_remains_invalid_through_join_quality_and_top_level(self) -> None:
        invalid_owner = owner_context()
        invalid_owner.update(
            {
                "state": "invalid",
                "diagnostics": ["owner_thread_identity_mismatch"],
                "thread": {
                    "state": "invalid",
                    "thread": None,
                    "diagnostics": ["owner_thread_identity_mismatch"],
                },
            }
        )
        observed = project_participant_context(
            {"state": "bound", "freshness": "current_at_read", "actors": [actor()]},
            invalid_owner,
        )
        participant = observed["participants"][0]
        self.assertEqual(participant["task_context"]["state"], "invalid")
        self.assertEqual(participant["task_context"]["goal_thread"]["state"], "invalid")
        self.assertEqual(participant["quality"], "invalid")
        self.assertEqual(observed["state"], "invalid")
        self.assertIn("owner_thread_identity_mismatch", observed["diagnostics"])

    def test_invalid_activity_correlation_is_not_hidden_by_valid_shaped_actor(self) -> None:
        invalid_activity = {
            "state": "invalid",
            "freshness": "invalid",
            "degradation": ["actor_correlation_invalid"],
            "actors": [
                actor(
                    correlation={"master_thread_id": THREAD, "state": "returned"},
                    freshness="current_at_read",
                )
            ],
        }
        observed = project_participant_context(invalid_activity, owner_context())
        participant = observed["participants"][0]
        self.assertEqual(participant["task_context"]["state"], "invalid")
        self.assertEqual(participant["quality"], "invalid")
        self.assertEqual(observed["state"], "invalid")
        self.assertIn("participant_activity_invalid", observed["diagnostics"])

    def test_explicit_model_owner_shape_requires_exact_runtime_subject(self) -> None:
        value = actor(
            model_realization={
                "model_identity_ref": "aoa-models:model:gpt",
                "model_realization_ref": "aoa-models:realization:gpt",
                "fit_projection_ref": "aoa-models:fit:gpt",
                "runtime_subject": {"kind": "model", "source": "runtime:subject", "digest": "a" * 64},
            }
        )
        observed = project_participant_context({"state": "bound", "freshness": "current_at_read", "actors": [value]}, owner_context())
        self.assertEqual(observed["participants"][0]["model_realization"]["state"], "present")

    def test_explicit_name_role_task_model_and_relationship_fields_flow_without_inference(self) -> None:
        value = actor(
            identity={
                "name": "Luna",
                "display_name": "Luna owner label",
                "role_id": "external_codex_incarnation",
                "role_name": "Independent read-model holder",
                "model_id": "gpt-5.6-luna:max",
            },
            task={"task_id": "task:one", "task_ref": "aoa-task:read-model", "title": "Project Goal context"},
            model_realization={
                "model_identity_ref": "aoa-models:model:gpt",
                "model_realization_ref": "aoa-models:realization:gpt",
                "runtime_subject": {"kind": "model", "source": "runtime:subject", "digest": "b" * 64},
            },
            relationships={
                "parent_thread_id": THREAD,
                "branch_ref": "dag:GS31",
                "private_transcript": "must be discarded",
            },
        )
        observed = project_participant_context(
            {"state": "bound", "freshness": "current_at_read", "actors": [value]},
            owner_context(),
        )
        self.assert_schema(observed)
        participant = observed["participants"][0]
        self.assertEqual(participant["identity"]["name"], "Luna")
        self.assertEqual(participant["identity"]["display_name"], "Luna owner label")
        self.assertEqual(participant["identity"]["role_name"], "Independent read-model holder")
        self.assertEqual(participant["task_context"]["task_ref"], "aoa-task:read-model")
        self.assertEqual(participant["task_context"]["title"], "Project Goal context")
        self.assertEqual(participant["model_realization"]["state"], "present")
        self.assertEqual(participant["relationships"]["state"], "present")
        self.assertEqual(participant["relationships"]["task_local"]["branch_ref"], "dag:GS31")
        self.assertNotIn("private_transcript", participant["relationships"]["task_local"])


if __name__ == "__main__":
    unittest.main()
