from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.cursor import (  # noqa: E402
    append_correlation_observations,
    make_observation,
    materialize_goal_local_projection,
    migrate_legacy_correlation_input,
    read_correlation_observation_log,
    rebuild_goal_local_projection,
)
from aoa_dashboard.projection import build_projection  # noqa: E402
from aoa_dashboard.pressure import (  # noqa: E402
    build_pressure_inbox,
    migrate_legacy_pressure_candidates,
    validate_pressure_record,
)
from aoa_dashboard.state_store import create_action_intent, create_annotation  # noqa: E402


GOAL_ID = "goal:test"
THREAD_ID = "thread:test"
SOURCE_REF = {
    "label": "test source",
    "kind": "test_owner_event",
    "ref": "/bounded/test-source.json",
    "sha256": "a" * 64,
    "currentness": "current_at_read",
    "owner": "test-owner",
    "authority": "source_owner",
    "access_scope": "owner_bounded",
    "claim_limit": "Test source is not acceptance.",
}


def observation(observation_id: str = "return:one", state: str = "returned", entity_key: str | None = None) -> dict:
    return make_observation(
        goal_id=GOAL_ID,
        master_thread_id=THREAD_ID,
        observation_id=observation_id,
        entity_key=entity_key or f"return:{observation_id}",
        kind="test_observation",
        payload={"state": state, "owner_fact": "retained"},
        source_refs=[SOURCE_REF],
        observed_at="2026-08-15T23:00:00Z",
    )


def pressure_record() -> dict:
    return {
        "schema_version": "aoa_dashboard_pressure_record_v1",
        "goal_id": GOAL_ID,
        "pressure_ref": {
            "id": "pressure:test",
            "kind": "test_pressure",
            "ref": "goal:test#P-infinity",
            "sha256": None,
            "currentness": "current_at_read",
            "access_scope": "dashboard_local",
            "authority": "dashboard_derived",
        },
        "evidence": [
            {
                "ref": "/bounded/test-source.json",
                "owner": "test-owner",
                "kind": "test_owner_event",
                "sha256": "a" * 64,
                "currentness": "current_at_read",
                "access_scope": "owner_bounded",
                "authority": "source_owner",
                "claim_limit": "Test evidence is not acceptance.",
            }
        ],
        "affected_goal_criterion": "The test criterion must retain pressure.",
        "consequence_of_omission": "The pressure could disappear.",
        "natural_owner": {
            "owner": "test-owner",
            "owner_ref": "owner:test-owner",
            "authority": "source_owner",
            "access_scope": "owner_bounded",
        },
        "checked_existing_surfaces": [
            {
                "surface": "test existing surface",
                "owner": "test-owner",
                "result": "partial",
                "ref": "/bounded/test-surface",
                "claim_limit": "Surface check is not proof.",
            }
        ],
        "independence_signals": {
            "status": "present",
            "signals": ["separate holder"],
            "claim_limit": "Independence is not acceptance.",
        },
        "recommended_trigger_strength": "required_branch",
        "stop_line": "Do not execute from this read model.",
        "wake_condition": "Wake the owner if the pressure needs a new branch.",
        "next_route": {
            "owner": "test-owner",
            "owner_ref": "owner:test-owner",
            "route": "owner:test-owner/review",
            "reason": "The owner decides the next route.",
            "critical": True,
            "authority": "source_owner",
            "access_scope": "owner_bounded",
            "effect": "none",
            "claim_limit": "Route display is not execution.",
        },
        "outcome": {
            "state": "new_required_obligation",
            "owner": "test-owner",
            "claim_limit": "Outcome is not acceptance.",
        },
        "claim_limit": "Pressure is a derived test record.",
    }


class CursorRetentionTests(unittest.TestCase):
    def test_cursor_is_order_independent_and_replay_is_idempotent(self) -> None:
        first = observation("return:one")
        second = observation("return:two")
        left = rebuild_goal_local_projection(goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first, second])
        right = rebuild_goal_local_projection(goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[second, first])
        self.assertEqual(left["cursor"]["cursor_digest"], right["cursor"]["cursor_digest"])
        self.assertEqual(left["checkpoint"]["projection_digest"], right["checkpoint"]["projection_digest"])

        replay = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[first, second],
            checkpoint=left["checkpoint"],
        )
        self.assertEqual(replay["status"], "current")
        self.assertEqual(replay["rebuild"]["mode"], "replay")
        self.assertTrue(replay["rebuild"]["replay_safe"])

    def test_cursor_drift_fails_closed_when_existing_payload_changes(self) -> None:
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[observation()]
        )
        changed = observation(state="reviewed")
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[changed],
            checkpoint=baseline["checkpoint"],
        )
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["rebuild"]["deterministic"])
        self.assertTrue(any("cursor_drift" in error for error in result["rebuild"]["errors"]))

    def test_malformed_checkpoint_fails_closed(self) -> None:
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[observation()]
        )
        checkpoint = copy.deepcopy(baseline["checkpoint"])
        checkpoint["checkpoint_id"] = "checkpoint:wrong"
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[observation()],
            checkpoint=checkpoint,
        )
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("checkpoint_invalid" in error for error in result["rebuild"]["errors"]))

    def test_tampered_replay_projection_digest_fails_closed(self) -> None:
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[observation()]
        )
        checkpoint = copy.deepcopy(baseline["checkpoint"])
        checkpoint["projection_digest"] = "f" * 64
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[observation()],
            checkpoint=checkpoint,
        )
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["rebuild"]["replay_safe"])
        self.assertTrue(any("projection_digest" in error for error in result["rebuild"]["errors"]))

    def test_exact_duplicate_is_retained_as_provenance_without_second_record(self) -> None:
        item = observation()
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[item, copy.deepcopy(item)]
        )
        self.assertEqual(result["status"], "current")
        self.assertEqual(len(result["observations"]), 1)
        self.assertEqual(len(result["duplicates"]), 1)
        self.assertEqual(result["retention"]["winner_selection"], "none")

    def test_conflicting_observations_are_both_retained_without_winner(self) -> None:
        first = observation(state="returned")
        second = observation(state="deferred")
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first, second]
        )
        self.assertEqual(result["status"], "conflicted")
        self.assertEqual(len(result["observations"]), 2)
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertIsNone(result["conflicts"][0]["winner"])
        self.assertEqual(result["conflicts"][0]["resolution"], "unresolved")
        self.assertEqual(len(result["conflicts"][0]["observations"]), 2)

    def test_unknown_access_or_authority_is_not_admitted(self) -> None:
        item = observation()
        item["provenance"]["access_scope"] = "unknown"
        result = rebuild_goal_local_projection(goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[item])
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("access scope" in error for error in result["rebuild"]["errors"]))

        item = observation()
        item["provenance"]["authority"] = "unknown"
        result = rebuild_goal_local_projection(goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[item])
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("authority" in error for error in result["rebuild"]["errors"]))

    def test_append_only_log_is_durable_and_malformed_lines_are_not_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "correlation.jsonl"
            item = observation()
            self.assertEqual(append_correlation_observations(path, [item]), 1)
            records, errors = read_correlation_observation_log(path)
            self.assertEqual(records, [item])
            self.assertEqual(errors, [])
            path.write_text(path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
            records, errors = read_correlation_observation_log(path)
            self.assertEqual(len(records), 1)
            self.assertTrue(errors)

    def test_explicit_materialization_retains_a_later_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            first = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation(state="returned")],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            self.assertEqual(first["status"], "current")
            second = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("return:two", state="deferred", entity_key="return:return:one")],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            self.assertEqual(second["status"], "conflicted")
            self.assertEqual(len(second["conflicts"]), 1)
            self.assertTrue(log_path.exists())
            self.assertTrue(checkpoint_path.exists())


class PressureInboxTests(unittest.TestCase):
    def test_projection_keeps_derived_facts_and_dashboard_owned_write_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = os.environ.get("AOA_DASHBOARD_STATE_ROOT")
            os.environ["AOA_DASHBOARD_STATE_ROOT"] = directory
            try:
                create_annotation("operator:test", "goal:test", "Keep the conflict visible.")
                create_action_intent("operator:test", "goal:test", "owner:test-owner", "Review the pressure.")
                projection = build_projection()
            finally:
                if previous is None:
                    os.environ.pop("AOA_DASHBOARD_STATE_ROOT", None)
                else:
                    os.environ["AOA_DASHBOARD_STATE_ROOT"] = previous
        self.assertIn("correlation_read_model", projection)
        self.assertIn("pressure_inbox", projection)
        self.assertTrue(projection["correlation_read_model"]["observations"])
        self.assertEqual(projection["annotations"]["count"], 1)
        self.assertEqual(projection["action_intents"]["count"], 1)
        self.assertEqual(projection["action_intents"]["latest"][0]["state"], "deferred")
        self.assertEqual(projection["action_intents"]["latest"][0]["effect"], "none")

    def test_complete_pressure_is_admitted_and_critical_route_is_displayable(self) -> None:
        record = pressure_record()
        self.assertEqual(validate_pressure_record(record, expected_goal_id=GOAL_ID), [])
        inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[record])
        self.assertEqual(inbox["status"], "current")
        self.assertEqual(len(inbox["items"]), 1)
        self.assertEqual(len(inbox["critical_next_routes"]), 1)
        self.assertEqual(inbox["critical_next_routes"][0]["next_route"]["effect"], "none")

    def test_missing_required_pressure_fields_fail_closed(self) -> None:
        for field in ("evidence", "natural_owner", "stop_line", "wake_condition", "next_route"):
            record = pressure_record()
            record.pop(field)
            errors = validate_pressure_record(record, expected_goal_id=GOAL_ID)
            self.assertTrue(any(field in error for error in errors), (field, errors))

    def test_unknown_pressure_access_and_authority_fail_closed(self) -> None:
        record = pressure_record()
        record["natural_owner"]["access_scope"] = "unknown"
        self.assertTrue(any("natural_owner.access_scope" in error for error in validate_pressure_record(record)))
        record = pressure_record()
        record["next_route"]["authority"] = "unknown"
        self.assertTrue(any("next_route.authority" in error for error in validate_pressure_record(record)))

    def test_malformed_pressure_is_rejected_and_conflicts_have_no_winner(self) -> None:
        malformed = pressure_record()
        malformed["stop_line"] = "unknown"
        inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[malformed])
        self.assertEqual(inbox["status"], "invalid")
        self.assertEqual(inbox["items"], [])
        self.assertTrue(inbox["invalid_records"])

        first = pressure_record()
        second = pressure_record()
        second["consequence_of_omission"] = "A different consequence."
        inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[first, second])
        self.assertEqual(inbox["status"], "conflicted")
        self.assertEqual(len(inbox["items"]), 2)
        self.assertIsNone(inbox["conflicts"][0]["winner"])

    def test_legacy_master_filter_obligations_remain_deferred_candidates(self) -> None:
        source = {
            "metadata": {
                "new_obligations": ["legacy obligation"],
                "master_filter": {
                    "ref": {
                        "ref": "/bounded/master-filter.json",
                        "kind": "task_local_master_filter",
                        "sha256": "b" * 64,
                        "freshness": "current_at_read",
                        "claim_limit": "Master filter is not acceptance.",
                    }
                },
            }
        }
        candidates = migrate_legacy_pressure_candidates({}, source)
        inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[], legacy_candidates=candidates)
        self.assertEqual(inbox["status"], "deferred")
        self.assertEqual(inbox["items"], [])
        self.assertEqual(inbox["legacy_candidates"][0]["outcome"], "deferred")
        self.assertIn("natural_owner", inbox["legacy_candidates"][0]["missing_fields"])

    def test_legacy_bootstrap_and_master_filter_migration_is_explicit(self) -> None:
        migration = migrate_legacy_correlation_input(
            {"schema_version": "legacy", "current_correlation": {"master_filter_path": "/bounded/filter.json"}},
            {"metadata": {"master_filter": {"ref": {"ref": "/bounded/filter.json"}}}},
        )
        self.assertEqual(migration["schema_version"], "aoa_dashboard_correlation_migration_v1")
        self.assertTrue(migration["master_filter_binding"]["accepted"])
        self.assertEqual(migration["cursor_checkpoint"]["mode"], "new_versioned_projection")


if __name__ == "__main__":
    unittest.main()
