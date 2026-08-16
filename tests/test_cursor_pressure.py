from __future__ import annotations

import copy
import json
import multiprocessing
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.cursor import (  # noqa: E402
    append_correlation_observations,
    content_digest,
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


def _materialize_process_worker(log_path: str, checkpoint_path: str, item: dict, queue: object) -> None:
    try:
        result = materialize_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[item],
            observation_log_path=log_path,
            checkpoint_path=checkpoint_path,
        )
        queue.put({"ok": True, "status": result["status"]})
    except Exception as exc:  # pragma: no cover - exercised in the parent assertion
        queue.put({"ok": False, "error": str(exc)})


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

    def test_replay_digest_ignores_volatile_provenance_observed_at(self) -> None:
        first = observation()
        first["provenance"]["source_refs"][0]["observed_at"] = "2026-08-15T23:00:00Z"
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first]
        )
        second = copy.deepcopy(first)
        second["provenance"]["source_refs"][0]["observed_at"] = "2026-08-15T23:01:00Z"
        replay = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[second],
            checkpoint=baseline["checkpoint"],
        )
        self.assertEqual(replay["status"], "current")
        self.assertEqual(replay["rebuild"]["mode"], "replay")
        self.assertEqual(replay["checkpoint"]["projection_digest"], baseline["checkpoint"]["projection_digest"])

    def test_replay_digest_ignores_observation_level_observed_at(self) -> None:
        first = observation()
        first["observed_at"] = "2026-08-15T23:00:00Z"
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first]
        )
        second = copy.deepcopy(first)
        second["observed_at"] = "2026-08-15T23:01:00Z"
        replay = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[second],
            checkpoint=baseline["checkpoint"],
        )
        self.assertEqual(replay["status"], "current")
        self.assertEqual(replay["rebuild"]["mode"], "replay")
        self.assertEqual(replay["cursor"]["cursor_digest"], baseline["cursor"]["cursor_digest"])
        self.assertEqual(replay["checkpoint"]["projection_digest"], baseline["checkpoint"]["projection_digest"])

    def test_forged_extension_cursor_is_invalid_before_new_record_is_admitted(self) -> None:
        first = observation("return:one")
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first]
        )
        forged = copy.deepcopy(baseline["checkpoint"])
        forged["cursor"]["input_digest"] = "f" * 64
        forged_cursor = copy.deepcopy(forged["cursor"])
        forged_cursor.pop("cursor_digest")
        forged["cursor"]["cursor_digest"] = content_digest(forged_cursor)
        forged["checkpoint_id"] = f"checkpoint:{forged['cursor']['cursor_digest']}"
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observations=[first, observation("return:two")],
            checkpoint=forged,
        )
        self.assertEqual(result["status"], "invalid")
        self.assertEqual(result["rebuild"]["mode"], "invalid")
        self.assertTrue(any("checkpoint_invalid" in error for error in result["rebuild"]["errors"]))

    def test_checkpoint_maps_and_conflicts_are_authenticated(self) -> None:
        first = observation("return:one")
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first]
        )
        for field, value in (
            ("retained_observation_ids", []),
            ("conflict_ids", ["conflict:forged"]),
            ("projection_digest", "f" * 64),
        ):
            checkpoint = copy.deepcopy(baseline["checkpoint"])
            checkpoint[field] = value
            result = rebuild_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[first],
                checkpoint=checkpoint,
            )
            self.assertEqual(result["status"], "invalid", field)
            self.assertTrue(result["rebuild"]["errors"], field)

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

    def test_same_observation_payload_with_different_entity_is_a_conflict(self) -> None:
        first = observation("return:same", entity_key="entity:first")
        second = observation("return:same", entity_key="entity:second")
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first, second]
        )
        self.assertEqual(result["status"], "conflicted")
        self.assertEqual(len(result["observations"]), 2)
        self.assertEqual(result["duplicates"], [])
        self.assertIsNone(result["conflicts"][0]["winner"])

    def test_source_watermark_collision_retains_complete_candidates(self) -> None:
        first = observation("return:source-a")
        second = make_observation(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observation_id="return:source-b",
            entity_key="return:source-b",
            kind="test_observation",
            payload={"state": "returned", "owner_fact": "retained"},
            source_refs=[{**SOURCE_REF, "sha256": "b" * 64}],
        )
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first, second]
        )
        self.assertEqual(len(result["cursor"]["source_watermarks"]), 2)
        self.assertEqual(len(result["cursor"]["source_collisions"]), 1)
        self.assertIsNone(result["cursor"]["source_collisions"][0]["winner"])

    def test_source_access_downgrade_is_visible_as_unresolved_collision(self) -> None:
        first = observation("return:access-a")
        second = make_observation(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observation_id="return:access-b",
            entity_key="return:access-b",
            kind="test_observation",
            payload={"state": "returned", "owner_fact": "retained"},
            source_refs=[{**SOURCE_REF, "access_scope": "public_metadata"}],
        )
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first, second]
        )
        self.assertEqual(result["status"], "conflicted")
        self.assertTrue(result["cursor"]["source_collisions"][0]["access_downgrade"])

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

    def test_metadata_boundary_rejects_raw_and_nested_secret_content(self) -> None:
        with self.assertRaises(ValueError):
            make_observation(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observation_id="raw",
                entity_key="raw",
                kind="correlation_envelope",
                payload={"raw_body": "PRIVATE-BODY"},
                source_refs=[SOURCE_REF],
            )
        with self.assertRaises(ValueError):
            make_observation(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observation_id="nested-secret",
                entity_key="nested-secret",
                kind="correlation_envelope",
                payload={"goal": {"nested_secret": "PRIVATE"}},
                source_refs=[SOURCE_REF],
            )
        missing_scope = copy.deepcopy(SOURCE_REF)
        missing_scope.pop("access_scope")
        with self.assertRaises(ValueError):
            make_observation(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observation_id="missing-scope",
                entity_key="missing-scope",
                kind="test_observation",
                payload={"state": "returned", "owner_fact": "retained"},
                source_refs=[missing_scope],
            )

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

    def test_materialization_serializes_concurrent_threads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            barrier = threading.Barrier(3)
            results: list[dict] = []

            def worker(item: dict) -> None:
                barrier.wait()
                results.append(
                    materialize_goal_local_projection(
                        goal_id=GOAL_ID,
                        master_thread_id=THREAD_ID,
                        observations=[item],
                        observation_log_path=log_path,
                        checkpoint_path=checkpoint_path,
                    )
                )

            threads = [
                threading.Thread(target=worker, args=(observation("return:thread-one"),)),
                threading.Thread(target=worker, args=(observation("return:thread-two"),)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=5)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(result["status"] in {"current", "conflicted"} for result in results))
            records, errors = read_correlation_observation_log(log_path)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(len(checkpoint["retained_observation_ids"]), 2)

    def test_materialization_serializes_concurrent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            context = multiprocessing.get_context("fork")
            queue = context.Queue()
            processes = [
                context.Process(
                    target=_materialize_process_worker,
                    args=(str(log_path), str(checkpoint_path), observation("return:process-one"), queue),
                ),
                context.Process(
                    target=_materialize_process_worker,
                    args=(str(log_path), str(checkpoint_path), observation("return:process-two"), queue),
                ),
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
            results = [queue.get(timeout=3), queue.get(timeout=3)]
            self.assertTrue(all(item["ok"] for item in results), results)
            records, errors = read_correlation_observation_log(log_path)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            self.assertEqual(len(checkpoint["retained_observation_ids"]), 2)

    def test_checkpoint_replace_failure_cleans_temp_and_recovers_log_ahead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            item = observation("return:replace-failure")
            with patch("aoa_dashboard.cursor.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    materialize_goal_local_projection(
                        goal_id=GOAL_ID,
                        master_thread_id=THREAD_ID,
                        observations=[item],
                        observation_log_path=log_path,
                        checkpoint_path=checkpoint_path,
                    )
            self.assertFalse(checkpoint_path.exists())
            self.assertEqual(list(Path(directory).glob(".checkpoint.json.tmp-*")), [])
            recovered = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            self.assertEqual(recovered["status"], "current")
            self.assertEqual(len(recovered["observations"]), 1)

    def test_checkpoint_parent_fsync_failure_does_not_report_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            item = observation("return:fsync-failure")
            with patch("aoa_dashboard.cursor._fsync_parent_directory", side_effect=OSError("directory fsync failed")):
                with self.assertRaises(OSError):
                    materialize_goal_local_projection(
                        goal_id=GOAL_ID,
                        master_thread_id=THREAD_ID,
                        observations=[item],
                        observation_log_path=log_path,
                        checkpoint_path=checkpoint_path,
                    )
            recovered = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            self.assertEqual(recovered["rebuild"]["mode"], "replay")

    def test_partial_append_tail_is_recovered_on_next_locked_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            first = observation("return:partial-first")
            materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[first],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            with log_path.open("ab") as stream:
                stream.write(b'{"schema_version":"partial')
            recovered = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("return:partial-second")],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            self.assertEqual(recovered["status"], "current")
            self.assertEqual(recovered["storage"]["recovered_tail"]["action"], "truncate_partial_tail")
            records, errors = read_correlation_observation_log(log_path)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)

    def test_stale_checkpoint_is_rebuilt_from_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("return:stale-first")],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            checkpoint_path.unlink()
            recovered = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("return:stale-second")],
                observation_log_path=log_path,
                checkpoint_path=checkpoint_path,
            )
            self.assertEqual(recovered["status"], "current")
            self.assertEqual(len(recovered["observations"]), 2)

    def test_append_write_failure_leaves_no_success_and_recovers_partial_frame(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            original_write_all = __import__("aoa_dashboard.cursor", fromlist=["_write_all"])._write_all

            def partial_write(stream: object, data: bytes) -> None:
                stream.write(data[: max(1, len(data) // 2)])
                raise OSError("append interrupted")

            with patch("aoa_dashboard.cursor._write_all", side_effect=partial_write):
                with self.assertRaises(OSError):
                    materialize_goal_local_projection(
                        goal_id=GOAL_ID,
                        master_thread_id=THREAD_ID,
                        observations=[observation("return:write-failure")],
                        observation_log_path=log_path,
                        checkpoint_path=checkpoint_path,
                    )
            with patch("aoa_dashboard.cursor._write_all", wraps=original_write_all):
                recovered = materialize_goal_local_projection(
                    goal_id=GOAL_ID,
                    master_thread_id=THREAD_ID,
                    observations=[observation("return:write-failure")],
                    observation_log_path=log_path,
                    checkpoint_path=checkpoint_path,
                )
            self.assertEqual(recovered["status"], "current")
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
