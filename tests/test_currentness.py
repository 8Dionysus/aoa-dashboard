from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.correlation import observe_current_correlation  # noqa: E402
from aoa_dashboard.currentness import advance_master_filter_currentness  # noqa: E402


CORRELATION_SCHEMA = Draft202012Validator(
    json.loads(
        (Path(__file__).resolve().parents[1] / "contracts" / "correlation_envelope.schema.json").read_text(
            encoding="utf-8"
        )
    )
)


class CurrentnessFixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.task_local = self.root / "task-local"
        self.task_local.mkdir()
        self.anchor = self.root / "goal-anchor.txt"
        self.anchor.write_text("# currentness test goal\n", encoding="utf-8")
        self.thread = "currentness-thread"
        self.handoff = self.task_local / "d8-luna-handoff.json"
        self.wake = self.task_local / "d8-luna-handoff.wake-receipt.json"
        self.filter = self.task_local / "master-return-disposition.json"
        self.current_head = self.task_local / "master-return-current-head.json"
        self.history = self.task_local / "master-return-head-history.jsonl"
        self._write_json(
            self.handoff,
            {
                "schema_version": "test_handoff_v1",
                "master_thread_id": self.thread,
                "responsibility_state": "returned",
            },
        )
        self.handoff_digest = self._digest(self.handoff)
        self._write_json(
            self.wake,
            {
                "schema_version": "task_local_actor_wake_receipt_v2",
                "thread_id": self.thread,
                "handoff_ref": str(self.handoff.resolve()),
                "handoff_sha256": self.handoff_digest,
                "outcome": "handoff_delivered_pending_master_filter",
                "attempted_at": "2026-08-20T20:00:00Z",
                "observed": {
                    "accepted_turn_id": "currentness-turn-1",
                    "delivery_route": "active_turn_steer",
                    "handoff_delivery": True,
                },
                "actions": {"handoff_message_submitted": True, "goal_resume_requested": False},
            },
        )
        self._write_filter("2026-08-20T20:01:00Z")
        self.initial_filter_bytes = self.filter.read_bytes()
        self.initial_digest = self._digest(self.filter)
        self._write_attestation(sequence=0, transition="initial", previous=None, append=True)

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    def _write_filter(self, reviewed_at: str) -> None:
        self._write_json(
            self.filter,
            {
                "schema_version": "aoa_dashboard_master_return_disposition_v1",
                "master_thread_id": self.thread,
                "goal_ref": str(self.anchor.resolve()),
                "reviewed_at": reviewed_at,
                "returns": [
                    {
                        "id": "d8",
                        "disposition": "accepted_with_limits",
                        "handoff_ref": str(self.handoff.resolve()),
                        "handoff_sha256": self.handoff_digest,
                        "wake_receipt_ref": str(self.wake.resolve()),
                    }
                ],
                "goal_dag": [{"id": "D8", "state": "partial", "next": "master owner"}],
                "new_required_obligations": [],
                "rejected_or_deferred_claims": ["semantic continuation"],
            },
        )

    def _head(self, *, sequence: int, transition: str, previous: str | None, digest: str | None = None) -> dict:
        return {
            "schema_version": "aoa_dashboard_master_filter_current_head_v1",
            "owner": "master-thread",
            "authority": "master_decision",
            "access_scope": "owner_bounded",
            "master_thread_id": self.thread,
            "goal_ref": str(self.anchor.resolve()),
            "filter_ref": str(self.filter.resolve()),
            "history_ref": str(self.history.resolve()),
            "head_sha256": digest or self._digest(self.filter),
            "sequence": sequence,
            "reviewed_at": f"2026-08-20T20:{sequence + 1:02d}:00Z",
            "transition": transition,
            "previous_head_sha256": previous,
            "claim_limit": "Currentness is owner evidence, not dashboard authority or acceptance.",
        }

    def _write_attestation(
        self,
        *,
        sequence: int,
        transition: str,
        previous: str | None,
        append: bool,
        digest: str | None = None,
    ) -> dict:
        head = self._head(sequence=sequence, transition=transition, previous=previous, digest=digest)
        record = dict(head)
        record["schema_version"] = "aoa_dashboard_master_filter_head_record_v1"
        if append:
            with self.history.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        self._write_json(self.current_head, head)
        return head

    def advance(self, reviewed_at: str, *, transition: str = "advance", digest: str | None = None) -> dict:
        previous = self._digest(self.current_head)
        old_head = json.loads(self.current_head.read_text(encoding="utf-8"))
        self._write_filter(reviewed_at)
        new_digest = digest or self._digest(self.filter)
        head = self._head(sequence=old_head["sequence"] + 1, transition=transition, previous=old_head["head_sha256"], digest=new_digest)
        record = dict(head)
        record["schema_version"] = "aoa_dashboard_master_filter_head_record_v1"
        with self.history.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        self._write_json(self.current_head, head)
        return head

    def config(self) -> dict:
        binding = {
            "schema_version": "aoa_dashboard_master_filter_currentness_binding_v1",
            "owner": "master-thread",
            "authority": "master_decision",
            "access_scope": "owner_bounded",
            "filter_ref": str(self.filter.resolve()),
            "current_head_ref": str(self.current_head.resolve()),
            "history_ref": str(self.history.resolve()),
            "claim_limit": "The current head is owner evidence consumed by the dashboard, not authority or acceptance.",
        }
        return {
            "goal_id": "currentness-goal",
            "goal_anchor_path": str(self.anchor.resolve()),
            "goal_anchor_expected_sha256": hashlib.sha256(self.anchor.read_bytes()).hexdigest(),
            "current_correlation": {
                "master_thread_id": self.thread,
                "task_local_dir": str(self.task_local.resolve()),
                "master_filter_path": str(self.filter.resolve()),
                "master_filter_currentness": binding,
                "legacy_snapshot_binding": {
                    "schema_version": "aoa_dashboard_legacy_snapshot_binding_v1",
                    "expected_sha256": "0" * 64,
                    "snapshot_role": "historical_bootstrap_only",
                    "claim_limit": "Historical context only.",
                },
                "handoff_glob": "*-luna-handoff.json",
                "wake_glob": "*.wake-receipt.json",
                "ignored_handoff_names": [],
                "ignored_wake_names": [],
                "current_holder": "test currentness holder",
            },
        }

    def close(self) -> None:
        self.tmp.cleanup()


class CurrentnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CurrentnessFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def observe(self) -> dict:
        result = observe_current_correlation(self.fixture.config())
        for envelope in result["metadata"].get("envelopes", []):
            errors = sorted(CORRELATION_SCHEMA.iter_errors(envelope), key=lambda error: str(list(error.path)))
            self.assertEqual([], [f"{list(error.path)}: {error.message}" for error in errors])
        return result

    def currentness(self, result: dict) -> dict:
        return result["metadata"]["master_filter"]["currentness"]

    def test_normal_transition_is_current_and_does_not_rewrite_config(self) -> None:
        config = self.fixture.config()
        before = json.dumps(config, sort_keys=True)
        old_digest = self.fixture.initial_digest
        self.fixture.advance("2026-08-20T20:02:00Z")
        result = self.observe()
        after = json.dumps(config, sort_keys=True)
        currentness = self.currentness(result)
        self.assertEqual(before, after)
        self.assertEqual(result["state"], "bound")
        self.assertEqual(currentness["state"], "current_at_read")
        self.assertEqual(currentness["head"]["sequence"], 1)
        self.assertEqual(currentness["head"]["previous_head_sha256"], old_digest)
        self.assertEqual(currentness["history"]["record_count"], 2)
        self.assertEqual(currentness["history"]["last_sequence"], 1)
        self.assertEqual(currentness["legacy_snapshot_binding"]["snapshot_role"], "historical_bootstrap_only")
        self.assertTrue(any(ref["ref"] == str(self.fixture.current_head.resolve()) for ref in currentness["evidence_refs"]))

    def test_duplicate_current_head_member_is_invalid_without_source_content(self) -> None:
        raw = self.fixture.current_head.read_text(encoding="utf-8").replace(
            '"sequence":0',
            '"sequence":0,"sequence":"secret-current-head-value"',
            1,
        )
        self.fixture.current_head.write_text(raw, encoding="utf-8")

        result = self.observe()

        self.assertEqual(result["state"], "invalid")
        self.assertEqual(self.currentness(result)["state"], "invalid")
        self.assertNotIn("secret-current-head-value", json.dumps(result))

    def test_content_derived_helper_advances_idempotently_and_preserves_history(self) -> None:
        history_before = self.fixture.history.read_bytes()
        self.fixture._write_filter("2026-08-20T20:06:00Z")
        receipt = advance_master_filter_currentness(
            filter_path=self.fixture.filter,
            current_head_path=self.fixture.current_head,
            history_path=self.fixture.history,
            master_thread_id=self.fixture.thread,
            goal_ref=str(self.fixture.anchor.resolve()),
            reviewed_at="2026-08-20T20:06:01Z",
        )
        self.assertEqual(receipt["status"], "advanced")
        self.assertTrue(receipt["changed"])
        self.assertEqual(receipt["filter_sha256"], hashlib.sha256(self.fixture.filter.read_bytes()).hexdigest())
        self.assertEqual(receipt["head"]["sequence"], 1)
        self.assertEqual(receipt["head"]["previous_head_sha256"], self.fixture.initial_digest)
        self.assertTrue(self.fixture.history.read_bytes().startswith(history_before))

        unchanged = advance_master_filter_currentness(
            filter_path=self.fixture.filter,
            current_head_path=self.fixture.current_head,
            history_path=self.fixture.history,
            master_thread_id=self.fixture.thread,
            goal_ref=str(self.fixture.anchor.resolve()),
            reviewed_at="2026-08-20T20:06:02Z",
        )
        self.assertEqual(unchanged["status"], "unchanged")
        self.assertFalse(unchanged["changed"])
        self.assertEqual(self.fixture.history.read_bytes().count(b"\n"), 2)

    def test_content_derived_helper_requires_explicit_rollback_for_prior_bytes(self) -> None:
        self.fixture._write_filter("2026-08-20T20:07:00Z")
        advance_master_filter_currentness(
            filter_path=self.fixture.filter,
            current_head_path=self.fixture.current_head,
            history_path=self.fixture.history,
            master_thread_id=self.fixture.thread,
            goal_ref=str(self.fixture.anchor.resolve()),
            reviewed_at="2026-08-20T20:07:01Z",
        )
        self.fixture.filter.write_bytes(self.fixture.initial_filter_bytes)
        with self.assertRaisesRegex(ValueError, "declare rollback"):
            advance_master_filter_currentness(
                filter_path=self.fixture.filter,
                current_head_path=self.fixture.current_head,
                history_path=self.fixture.history,
                master_thread_id=self.fixture.thread,
                goal_ref=str(self.fixture.anchor.resolve()),
                reviewed_at="2026-08-20T20:07:02Z",
            )
        rollback = advance_master_filter_currentness(
            filter_path=self.fixture.filter,
            current_head_path=self.fixture.current_head,
            history_path=self.fixture.history,
            master_thread_id=self.fixture.thread,
            goal_ref=str(self.fixture.anchor.resolve()),
            reviewed_at="2026-08-20T20:07:03Z",
            transition="rollback",
        )
        self.assertEqual(rollback["status"], "advanced")
        self.assertEqual(rollback["head"]["sequence"], 2)
        self.assertEqual(rollback["head"]["transition"], "rollback")
        self.assertEqual(rollback["filter_sha256"], self.fixture.initial_digest)

    def test_new_lineage_starts_from_selected_filter_without_rewriting_old_material(self) -> None:
        current_head = self.fixture.task_local / "migrated-current-head.json"
        history = self.fixture.task_local / "migrated-head-history.jsonl"
        receipt = advance_master_filter_currentness(
            filter_path=self.fixture.filter,
            current_head_path=current_head,
            history_path=history,
            master_thread_id=self.fixture.thread,
            goal_ref=str(self.fixture.anchor.resolve()),
            reviewed_at="2026-08-20T20:08:00Z",
            transition="initial",
        )
        self.assertEqual(receipt["status"], "initialized")
        self.assertEqual(receipt["head"]["sequence"], 0)
        self.assertEqual(receipt["head"]["transition"], "initial")
        self.assertEqual(
            json.loads(current_head.read_text(encoding="utf-8"))["head_sha256"],
            hashlib.sha256(self.fixture.filter.read_bytes()).hexdigest(),
        )
        self.assertEqual(len(history.read_text(encoding="utf-8").splitlines()), 1)

    def test_filter_change_without_new_head_is_stale_and_deferred(self) -> None:
        self.fixture._write_filter("2026-08-20T20:03:00Z")
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "stale")
        self.assertIn("current_head_digest_mismatch", currentness["degradation"])
        self.assertEqual(result["metadata"]["master_filter"]["ref"]["currentness"], "stale")
        self.assertEqual(result["state"], "deferred")
        self.assertNotEqual(result["metadata"]["envelopes"][0]["state"], "reentered")

    def test_missing_head_is_deferred_and_exposes_missing_attestation(self) -> None:
        self.fixture.current_head.unlink()
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "missing")
        self.assertIn("current_head_missing", currentness["degradation"])
        self.assertEqual(result["metadata"]["master_filter"]["ref"]["currentness"], "deferred")
        self.assertEqual(result["state"], "deferred")
        self.assertIn("currentness_attestation", result["metadata"]["master_filter"]["ref"]["missing_fields"])

    def test_ambiguous_current_head_is_invalid(self) -> None:
        head = json.loads(self.fixture.current_head.read_text(encoding="utf-8"))
        head["heads"] = [copy.deepcopy(head)]
        self.fixture._write_json(self.fixture.current_head, head)
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "invalid")
        self.assertIn("current_head_ambiguous", currentness["degradation"])
        self.assertEqual(result["state"], "invalid")

    def test_conflicting_history_heads_are_invalid(self) -> None:
        conflict = json.loads(self.fixture.current_head.read_text(encoding="utf-8"))
        conflict["schema_version"] = "aoa_dashboard_master_filter_head_record_v1"
        conflict["head_sha256"] = "f" * 64
        with self.fixture.history.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(conflict, sort_keys=True, separators=(",", ":")) + "\n")
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "invalid")
        self.assertIn("current_head_history_conflict", currentness["degradation"])
        self.assertEqual(result["state"], "invalid")

    def test_unannounced_rollback_is_invalid(self) -> None:
        first = self.fixture.initial_filter_bytes
        first_digest = self.fixture.initial_digest
        first_head = json.loads(self.fixture.current_head.read_text(encoding="utf-8"))
        self.fixture.advance("2026-08-20T20:04:00Z")
        second_head = json.loads(self.fixture.current_head.read_text(encoding="utf-8"))
        self.fixture.filter.write_bytes(first)
        self.fixture._write_attestation(
            sequence=second_head["sequence"] + 1,
            transition="advance",
            previous=second_head["head_sha256"],
            append=True,
            digest=first_digest,
        )
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "invalid")
        self.assertIn("current_head_rollback_detected", currentness["degradation"])
        self.assertNotIn("current_head_rollback_attested", currentness["degradation"])
        self.assertEqual(first, self.fixture.initial_filter_bytes)
        self.assertEqual(first_head["sequence"], 0)

    def test_owner_attested_rollback_is_current_but_explicitly_limited(self) -> None:
        first = self.fixture.initial_filter_bytes
        first_digest = self.fixture.initial_digest
        self.fixture.advance("2026-08-20T20:05:00Z")
        second_head = json.loads(self.fixture.current_head.read_text(encoding="utf-8"))
        self.fixture.filter.write_bytes(first)
        self.fixture._write_attestation(
            sequence=second_head["sequence"] + 1,
            transition="rollback",
            previous=second_head["head_sha256"],
            append=True,
            digest=first_digest,
        )
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "current_at_read")
        self.assertIn("current_head_rollback_attested", currentness["degradation"])
        self.assertEqual(result["state"], "bound")

    def test_missing_history_fails_closed(self) -> None:
        self.fixture.history.unlink()
        result = self.observe()
        currentness = self.currentness(result)
        self.assertEqual(currentness["state"], "invalid")
        self.assertIn("current_head_history_missing", currentness["degradation"])
        self.assertEqual(result["state"], "invalid")

    def test_private_current_head_fields_are_not_projected(self) -> None:
        head = json.loads(self.fixture.current_head.read_text(encoding="utf-8"))
        head["private_reason"] = "PRIVATE-OWNER-CONTENT"
        self.fixture._write_json(self.fixture.current_head, head)
        result = self.observe()
        currentness = self.currentness(result)
        serialized = json.dumps(result, sort_keys=True)
        self.assertEqual(currentness["state"], "invalid")
        self.assertNotIn("PRIVATE-OWNER-CONTENT", serialized)
        self.assertNotIn("private_reason", serialized)


if __name__ == "__main__":
    unittest.main()
