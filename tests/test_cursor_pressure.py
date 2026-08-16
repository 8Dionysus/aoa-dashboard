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
    _checkpoint_lock_path,
    content_digest,
    make_observation,
    materialize_goal_local_projection,
    migrate_legacy_correlation_input,
    redact_legacy_metadata,
    read_correlation_observation_log,
    rebuild_goal_local_projection,
    write_correlation_checkpoint,
)
from aoa_dashboard.cursor import _ledger_lock  # noqa: E402
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
    "claim_policy": "test_metadata",
    "snapshot_role": "test_fixture",
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


def _shared_context_process_worker(
    log_path: str, checkpoint_path: str, item: dict, lock_context: object, queue: object
) -> None:
    failures = 0
    for operation in (
        lambda: append_correlation_observations(log_path, [item], lock_context=lock_context),
        lambda: write_correlation_checkpoint(checkpoint_path, {}, lock_context=lock_context),
    ):
        try:
            operation()
        except ValueError:
            failures += 1
        except Exception as exc:  # pragma: no cover - unexpected child failure
            queue.put({"ok": False, "error": str(exc)})
            return
    queue.put({"ok": failures == 2, "failures": failures})


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
            "owner": "aoa-dashboard",
            "access_scope": "dashboard_local",
            "authority": "dashboard_derived",
            "claim_policy": "test_metadata",
            "snapshot_role": "test_fixture",
            "claim_limit": "Pressure identity is derived metadata, not source authority.",
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
                "claim_policy": "test_metadata",
                "snapshot_role": "test_fixture",
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
            "claim_policy": "test_metadata",
        },
        "checked_existing_surfaces": [
            {
                "surface": "test existing surface",
                "owner": "test-owner",
                "result": "partial",
                "ref": "/bounded/test-surface",
                "access_scope": "dashboard_local",
                "authority": "dashboard_derived",
                "claim_policy": "test_metadata",
                "claim_limit": "Surface check is not proof.",
            }
        ],
        "independence_signals": {
            "status": "present",
            "signals": ["separate_holder"],
            "claim_policy": "test_metadata",
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
            "claim_policy": "test_metadata",
            "claim_limit": "Route display is not execution.",
        },
        "outcome": {
            "state": "new_required_obligation",
            "owner": "test-owner",
            "claim_policy": "test_metadata",
            "claim_limit": "Outcome is not acceptance.",
        },
        "claim_policy": "test_metadata",
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

    def test_checkpoint_authenticates_each_cursor_and_checkpoint_field(self) -> None:
        first = observation("return:one")
        baseline = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first]
        )

        def invalid_checkpoint(checkpoint: dict) -> None:
            result = rebuild_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[first, observation("return:two")],
                checkpoint=checkpoint,
            )
            self.assertEqual(result["status"], "invalid")
            self.assertTrue(any("checkpoint_invalid" in error for error in result["rebuild"]["errors"]))

        cursor_cases = {
            "stream_id": "forged-stream",
            "position": 99,
            "record_ids": ["forged-record"],
            "observation_digests": [{"record_id": "forged-record"}],
            "source_watermarks": [],
            "source_collisions": [
                {
                    "ref": SOURCE_REF["ref"],
                    "candidate_identity_keys": ["a" * 64],
                    "access_downgrade": False,
                    "authority_drift": False,
                    "resolution": "unresolved",
                    "winner": None,
                    "claim_limit": "No winner.",
                }
            ],
            "input_digest": "f" * 64,
            "claim_limit": "forged claim",
        }
        for field, value in cursor_cases.items():
            checkpoint = copy.deepcopy(baseline["checkpoint"])
            checkpoint["cursor"][field] = value
            if field != "cursor_digest":
                forged_cursor = copy.deepcopy(checkpoint["cursor"])
                forged_cursor.pop("cursor_digest", None)
                checkpoint["cursor"]["cursor_digest"] = content_digest(forged_cursor)
                checkpoint["checkpoint_id"] = f"checkpoint:{checkpoint['cursor']['cursor_digest']}"
            invalid_checkpoint(checkpoint)

        checkpoint = copy.deepcopy(baseline["checkpoint"])
        checkpoint["cursor"]["cursor_digest"] = "f" * 64
        invalid_checkpoint(checkpoint)

        checkpoint = copy.deepcopy(baseline["checkpoint"])
        checkpoint["cursor"]["forged_field"] = "tamper"
        invalid_checkpoint(checkpoint)

        checkpoint = copy.deepcopy(baseline["checkpoint"])
        checkpoint["forged_field"] = "tamper"
        invalid_checkpoint(checkpoint)

        checkpoint_cases = {
            "schema_version": "forged",
            "projection_schema_version": "forged",
            "checkpoint_id": "checkpoint:forged",
            "goal_id": "other-goal",
            "master_thread_id": "other-thread",
            "projection_digest": "f" * 64,
            "retained_observation_ids": [],
            "conflict_ids": ["conflict:forged"],
            "rebuild_mode": "invalid",
            "claim_limit": "forged claim",
            "cursor": {},
        }
        for field, value in checkpoint_cases.items():
            checkpoint = copy.deepcopy(baseline["checkpoint"])
            checkpoint[field] = value
            invalid_checkpoint(checkpoint)

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

    def test_source_collision_matrix_retains_all_typed_drift_dimensions(self) -> None:
        first = observation("return:collision-matrix")
        second_ref = {
            **SOURCE_REF,
            "label": "changed source label",
            "kind": "changed_owner_event",
            "sha256": "b" * 64,
            "currentness": "stale",
            "owner": "different-owner",
            "access_scope": "public_metadata",
            "authority": "master_filter",
            "claim_limit": "Different claim limit.",
        }
        second = make_observation(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observation_id="return:collision-matrix-2",
            entity_key="return:collision-matrix-2",
            kind="test_observation",
            payload={"state": "returned", "owner_fact": "retained"},
            source_refs=[second_ref],
        )
        result = rebuild_goal_local_projection(
            goal_id=GOAL_ID, master_thread_id=THREAD_ID, observations=[first, second]
        )
        collision = result["cursor"]["source_collisions"][0]
        self.assertEqual(len(result["cursor"]["source_watermarks"]), 2)
        for field in (
            "access_scope_drift",
            "label_drift",
            "kind_drift",
            "digest_drift",
            "currentness_drift",
            "owner_drift",
            "authority_drift",
            "claim_limit_drift",
        ):
            self.assertTrue(collision[field], field)
        self.assertIsNone(collision["winner"])
        self.assertEqual(collision["resolution"], "unresolved")

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

    def test_nested_source_shaped_payload_observed_at_is_identity_bearing(self) -> None:
        first = make_observation(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observation_id="reviewer-payload-one",
            entity_key="reviewer-payload",
            kind="test_observation",
            payload={
                "state": "returned",
                "owner_fact": "retained",
                "goal": {
                    "ref": "reviewer:source",
                    "kind": "reviewer_source",
                    "claim_limit": "Reviewer payload remains meaningful.",
                    "observed_at": "2026-08-15T23:00:00Z",
                },
            },
            source_refs=[SOURCE_REF],
        )
        second_payload = copy.deepcopy(first["payload"])
        second_payload["goal"]["observed_at"] = "2026-08-15T23:01:00Z"
        second = make_observation(
            goal_id=GOAL_ID,
            master_thread_id=THREAD_ID,
            observation_id="reviewer-payload-two",
            entity_key="reviewer-payload",
            kind="test_observation",
            payload=second_payload,
            source_refs=[SOURCE_REF],
        )
        self.assertNotEqual(first["payload_digest"], second["payload_digest"])
        self.assertNotEqual(first["record_id"], second["record_id"])

    def test_source_ref_owner_and_claim_policy_are_bounded(self) -> None:
        unknown_owner = {**SOURCE_REF, "owner": "not-a-known-owner"}
        with self.assertRaises(ValueError):
            make_observation(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observation_id="unknown-owner",
                entity_key="unknown-owner",
                kind="test_observation",
                payload={"state": "returned", "owner_fact": "retained"},
                source_refs=[unknown_owner],
            )
        unknown_policy = {**SOURCE_REF, "claim_policy": "not-a-known-claim-policy"}
        with self.assertRaises(ValueError):
            make_observation(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observation_id="unknown-policy",
                entity_key="unknown-policy",
                kind="test_observation",
                payload={"state": "returned", "owner_fact": "retained"},
                source_refs=[unknown_policy],
            )

    def test_legacy_obligation_api_view_is_digest_only(self) -> None:
        safe = redact_legacy_metadata(
            {
                "new_obligations": ["PRIVATE-LEGACY-TEXT"],
                "master_filter": {"new_required_obligations": ["NESTED-PRIVATE-TEXT"]},
            }
        )
        rendered = json.dumps(safe, sort_keys=True)
        self.assertNotIn("PRIVATE-LEGACY-TEXT", rendered)
        self.assertNotIn("NESTED-PRIVATE-TEXT", rendered)
        self.assertTrue(safe["new_obligations"][0]["sha256"])
        self.assertTrue(safe["master_filter"]["new_required_obligations"][0]["redacted"].startswith("[redacted"))
        hostile = redact_legacy_metadata(
            {"new_obligations": [{"sha256": "a" * 64, "redacted": "PRIVATE-LEGACY-BODY", "claim_limit": "x"}]}
        )
        self.assertNotIn("PRIVATE-LEGACY-BODY", json.dumps(hostile))

    def test_append_only_log_is_durable_and_malformed_lines_are_not_discarded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "correlation.jsonl"
            item = observation()
            with _ledger_lock(path, Path(directory) / "checkpoint.json") as lock_context:
                self.assertEqual(append_correlation_observations(path, [item], lock_context=lock_context), 1)
            records, errors = read_correlation_observation_log(path)
            self.assertEqual(records, [item])
            self.assertEqual(errors, [])
            path.write_text(path.read_text(encoding="utf-8") + "{broken\n", encoding="utf-8")
            records, errors = read_correlation_observation_log(path)
            self.assertEqual(len(records), 1)
            self.assertTrue(errors)

    def test_public_ledger_writes_require_the_verified_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            with self.assertRaises(ValueError):
                append_correlation_observations(log_path, [observation()])
            with self.assertRaises(ValueError):
                write_correlation_checkpoint(checkpoint_path, {})
            self.assertFalse(log_path.exists())
            self.assertFalse(checkpoint_path.exists())

    def test_released_and_copied_contexts_cannot_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            with _ledger_lock(log_path, checkpoint_path) as lock_context:
                with self.assertRaises(TypeError):
                    copy.copy(lock_context)
                with self.assertRaises(TypeError):
                    copy.deepcopy(lock_context)
                forged = object.__new__(type(lock_context))
                with self.assertRaises(ValueError):
                    append_correlation_observations(log_path, [observation("forged")], lock_context=forged)
            with self.assertRaises(ValueError):
                append_correlation_observations(log_path, [observation("released")], lock_context=lock_context)
            with self.assertRaises(ValueError):
                write_correlation_checkpoint(checkpoint_path, {}, lock_context=lock_context)
            self.assertEqual(log_path.stat().st_size, 0)
            self.assertFalse(checkpoint_path.exists())

    def test_shared_context_fails_closed_across_thread_and_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            checkpoint_path = Path(directory) / "checkpoint.json"
            with _ledger_lock(log_path, checkpoint_path) as lock_context:
                thread_result: list[str] = []

                def thread_attempt() -> None:
                    try:
                        append_correlation_observations(
                            log_path, [observation("shared-thread")], lock_context=lock_context
                        )
                    except ValueError as exc:
                        thread_result.append(str(exc))
                    try:
                        write_correlation_checkpoint(checkpoint_path, {}, lock_context=lock_context)
                    except ValueError as exc:
                        thread_result.append(str(exc))

                thread = threading.Thread(target=thread_attempt)
                thread.start()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(thread_result), 2)

                context = multiprocessing.get_context("fork")
                queue = context.Queue()
                process = context.Process(
                    target=_shared_context_process_worker,
                    args=(str(log_path), str(checkpoint_path), observation("shared-process"), lock_context, queue),
                )
                process.start()
                process.join(timeout=10)
                self.assertEqual(process.exitcode, 0)
                child_result = queue.get(timeout=3)
                self.assertTrue(child_result["ok"], child_result)
            self.assertEqual(log_path.stat().st_size, 0)

    def test_active_context_rejects_wrong_log_and_checkpoint_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "correlation.jsonl"
            checkpoint_path = root / "checkpoint.json"
            wrong_log = root / "wrong.jsonl"
            wrong_checkpoint = root / "wrong-checkpoint.json"
            wrong_log.touch()
            with _ledger_lock(log_path, checkpoint_path) as lock_context:
                with self.assertRaises(ValueError):
                    append_correlation_observations(wrong_log, [observation("wrong-log")], lock_context=lock_context)
                with self.assertRaises(ValueError):
                    write_correlation_checkpoint(wrong_checkpoint, {}, lock_context=lock_context)
            self.assertEqual(wrong_log.stat().st_size, 0)
            self.assertFalse(wrong_checkpoint.exists())

    def test_one_physical_ledger_rejects_divergent_checkpoint_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "correlation.jsonl"
            first_checkpoint = Path(directory) / "checkpoint-a.json"
            second_checkpoint = Path(directory) / "checkpoint-b.json"
            materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("ledger-binding")],
                observation_log_path=log_path,
                checkpoint_path=first_checkpoint,
            )
            self.assertEqual(_checkpoint_lock_path(log_path, first_checkpoint), _checkpoint_lock_path(log_path, second_checkpoint))
            with self.assertRaises(ValueError):
                materialize_goal_local_projection(
                    goal_id=GOAL_ID,
                    master_thread_id=THREAD_ID,
                    observations=[],
                    observation_log_path=log_path,
                    checkpoint_path=second_checkpoint,
                )
            self.assertFalse(second_checkpoint.exists())

    def test_hardlink_and_symlink_aliases_share_the_same_ledger_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "correlation.jsonl"
            hardlink = root / "correlation-hardlink.jsonl"
            symlink = root / "correlation-symlink.jsonl"
            checkpoint = root / "checkpoint.json"
            materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("alias-one")],
                observation_log_path=log_path,
                checkpoint_path=checkpoint,
            )
            hardlink.hardlink_to(log_path)
            symlink.symlink_to(log_path)
            self.assertEqual(_checkpoint_lock_path(log_path, checkpoint), _checkpoint_lock_path(hardlink, checkpoint))
            self.assertEqual(_checkpoint_lock_path(log_path, checkpoint), _checkpoint_lock_path(symlink, checkpoint))
            hard_result = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[observation("alias-two")],
                observation_log_path=hardlink,
                checkpoint_path=checkpoint,
            )
            symlink_result = materialize_goal_local_projection(
                goal_id=GOAL_ID,
                master_thread_id=THREAD_ID,
                observations=[],
                observation_log_path=symlink,
                checkpoint_path=checkpoint,
            )
            self.assertIn(hard_result["status"], {"current", "conflicted"})
            self.assertEqual(symlink_result["rebuild"]["mode"], "replay")
            records, errors = read_correlation_observation_log(log_path)
            self.assertEqual(errors, [])
            self.assertEqual(len(records), 2)

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

    def test_pressure_metadata_boundary_rejects_missing_scope_and_unknown_nested_content(self) -> None:
        record = pressure_record()
        record["evidence"][0].pop("access_scope")
        errors = validate_pressure_record(record, expected_goal_id=GOAL_ID)
        self.assertTrue(any("evidence[0].access_scope" in error for error in errors))

        record = pressure_record()
        record["evidence"][0]["nested_secret"] = "PRIVATE"
        errors = validate_pressure_record(record, expected_goal_id=GOAL_ID)
        self.assertTrue(any("nested_secret" in error for error in errors))

        record = pressure_record()
        record["evidence"][0]["raw_body"] = "PRIVATE-BODY"
        inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[record])
        self.assertEqual(inbox["items"], [])
        self.assertNotIn("PRIVATE-BODY", str(inbox))

    def test_pressure_admission_rejects_unknown_owner_claim_and_unicode_private_keys(self) -> None:
        record = pressure_record()
        record["natural_owner"]["owner"] = "not-a-known-owner"
        self.assertTrue(any("natural_owner.owner" in error for error in validate_pressure_record(record)))

        record = pressure_record()
        record["next_route"]["claim_policy"] = "not-a-known-claim-policy"
        self.assertTrue(any("next_route.claim_policy" in error for error in validate_pressure_record(record)))

        for field_path in (
            ("natural_owner",),
            ("independence_signals",),
            ("next_route",),
            ("outcome",),
            ("checked_existing_surfaces", 0),
            ("evidence", 0),
        ):
            record = pressure_record()
            target: dict = record
            for part in field_path:
                target = target[part]
            target["рrivate"] = "PRIVATE-VALUE"
            inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[record])
            self.assertEqual(inbox["items"], [], field_path)
            self.assertNotIn("PRIVATE-VALUE", json.dumps(inbox, ensure_ascii=False), field_path)

    def test_all_admitted_diagnostic_lists_are_digest_only(self) -> None:
        raw_values = [
            "PRIVATE-DIAGNOSTIC-VALUE",
            "private-diagnostic-value",
            "ΡRIVATE-DIAGNOSTIC-VALUE",
        ]
        field_targets = (
            ("pressure_ref", "degradation"),
            ("evidence", 0, "degradation"),
            ("evidence", 0, "missing_fields"),
            ("pressure_ref", "snapshot_role"),
            ("evidence", 0, "snapshot_role"),
            ("independence_signals", "signals"),
        )
        for field_path in field_targets:
            for raw_value in raw_values:
                record = pressure_record()
                target: object = record
                for part in field_path[:-1]:
                    target = target[part]  # type: ignore[index]
                target[field_path[-1]] = (  # type: ignore[index]
                    [raw_value] if field_path[-1] in {"degradation", "missing_fields", "signals"} else raw_value
                )
                self.assertTrue(validate_pressure_record(record, expected_goal_id=GOAL_ID))
                inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[record])
                rendered = json.dumps(inbox, ensure_ascii=False, sort_keys=True)
                self.assertNotIn(raw_value, rendered, field_path)
                self.assertEqual(inbox["status"], "current", field_path)
                self.assertIn("diagnostic_digest:", rendered, field_path)

    def test_legacy_diagnostic_values_are_digest_only_in_deferred_summaries(self) -> None:
        source = {
            "metadata": {
                "new_obligations": ["legacy obligation"],
                "master_filter": {
                    "ref": {
                        "ref": "/bounded/master-filter.json",
                        "kind": "task_local_master_filter",
                        "sha256": "b" * 64,
                        "owner": "master-thread",
                        "authority": "master_decision",
                        "access_scope": "owner_bounded",
                        "currentness": "current_at_read",
                        "freshness": "current_at_read",
                        "claim_policy": "master_decision_disposition",
                        "snapshot_role": "live_observed",
                        "claim_limit": "Master filter is not acceptance.",
                    }
                },
            }
        }
        raw_value = "PRIVATE-LEGACY-DIAGNOSTIC"
        field_targets = (
            ("pressure_ref", "degradation"),
            ("pressure_ref", "missing_fields"),
            ("pressure_ref", "snapshot_role"),
            ("source_evidence_ref", "degradation"),
            ("source_evidence_ref", "missing_fields"),
            ("source_evidence_ref", "snapshot_role"),
            ("missing_fields",),
            ("source_missing_fields",),
            ("legacy_freshness",),
            ("migration",),
        )
        for field_path in field_targets:
            candidate = migrate_legacy_pressure_candidates({}, source)[0]
            target: object = candidate
            for part in field_path[:-1]:
                target = target[part]  # type: ignore[index]
            field = field_path[-1]
            target[field] = [raw_value] if field.endswith("fields") or field == "degradation" else raw_value  # type: ignore[index]
            inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[], legacy_candidates=[candidate])
            rendered = json.dumps(inbox, ensure_ascii=False, sort_keys=True)
            self.assertEqual(inbox["status"], "deferred", field_path)
            self.assertNotIn(raw_value, rendered, field_path)
            self.assertIn("diagnostic_digest:", rendered, field_path)

    def test_non_string_keys_at_every_nested_boundary_are_redacted_invalid(self) -> None:
        variants: list[dict] = []
        root = pressure_record()
        root[1] = "PRIVATE-VALUE"
        variants.append(root)
        for field_path in (
            ("pressure_ref",),
            ("natural_owner",),
            ("independence_signals",),
            ("next_route",),
            ("outcome",),
            ("evidence", 0),
            ("checked_existing_surfaces", 0),
        ):
            record = pressure_record()
            target: object = record
            for part in field_path:
                target = target[part]  # type: ignore[index]
            target[1] = "PRIVATE-VALUE"  # type: ignore[index]
            variants.append(record)
        for list_field in (("evidence",), ("checked_existing_surfaces",), ("independence_signals", "signals")):
            record = pressure_record()
            target: object = record
            for part in list_field:
                target = target[part]  # type: ignore[index]
            target.append({1: "PRIVATE-VALUE"})  # type: ignore[union-attr]
            variants.append(record)

        for record in variants:
            inbox = build_pressure_inbox(goal_id=GOAL_ID, records=[record])
            rendered = json.dumps(inbox, ensure_ascii=False, sort_keys=True)
            self.assertEqual(inbox["status"], "invalid")
            self.assertEqual(inbox["items"], [])
            self.assertTrue(inbox["invalid_records"])
            self.assertNotIn("PRIVATE-VALUE", rendered)

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
                        "owner": "master-thread",
                        "authority": "master_decision",
                        "access_scope": "owner_bounded",
                        "currentness": "current_at_read",
                        "freshness": "current_at_read",
                        "observed_at": "2026-08-15T23:10:00Z",
                        "claim_policy": "master_decision_disposition",
                        "snapshot_role": "live_observed",
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
        legacy = inbox["legacy_candidates"][0]
        self.assertNotIn("legacy_obligation", legacy)
        self.assertIn(candidates[0]["legacy_obligation_digest"], legacy["legacy_obligation_redacted"])
        self.assertEqual(legacy["source_evidence_ref"]["owner"], "master-thread")
        self.assertEqual(legacy["source_evidence_ref"]["authority"], "master_decision")
        self.assertEqual(legacy["source_evidence_ref"]["access_scope"], "owner_bounded")
        self.assertEqual(legacy["source_evidence_ref"]["observed_at"], "2026-08-15T23:10:00Z")
        self.assertEqual(legacy["source_evidence_ref"], candidates[0]["source_evidence_ref"])
        self.assertEqual(legacy["source_evidence_ref"]["claim_policy"], "master_decision_disposition")
        self.assertEqual(legacy["outcome"], "deferred")

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
