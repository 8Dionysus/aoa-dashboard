from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.server import DashboardHandler  # noqa: E402


class ServerTests(unittest.TestCase):
    def test_operator_ui_exposes_actor_activity_surface(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-lens="participants"', html)
        self.assertIn("function participantItems", javascript)
        self.assertIn("data.actor_activity", javascript)
        self.assertIn("currentness.evidence_refs", javascript)
        self.assertIn("renderDiagnosticRoutes", javascript)

    def test_health_endpoint_is_read_model_only(self) -> None:
        server = __import__("http.server", fromlist=["ThreadingHTTPServer"]).ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["read_model"], "derived")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_annotation_and_intent_are_dashboard_owned_deferred_records(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            previous = os.environ.get("AOA_DASHBOARD_STATE_ROOT")
            os.environ["AOA_DASHBOARD_STATE_ROOT"] = state_dir
            try:
                from aoa_dashboard.state_store import create_action_intent, create_annotation

                annotation = create_annotation("operator:test", "goal:test", "Observed archive drift.")
                intent = create_action_intent("operator:test", "goal:test", "owner:aoa-agents", "Review missing return receipt.")
                self.assertEqual(annotation["authority"], "dashboard_owned")
                self.assertEqual(intent["state"], "deferred")
                self.assertEqual(intent["effect"], "none")
            finally:
                if previous is None:
                    os.environ.pop("AOA_DASHBOARD_STATE_ROOT", None)
                else:
                    os.environ["AOA_DASHBOARD_STATE_ROOT"] = previous

    def test_record_summaries_keep_missing_unavailable_and_empty_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as state_dir:
            previous = os.environ.get("AOA_DASHBOARD_STATE_ROOT")
            os.environ["AOA_DASHBOARD_STATE_ROOT"] = state_dir
            try:
                from aoa_dashboard.state_store import action_intent_summary, annotation_summary

                for summary in (annotation_summary(), action_intent_summary()):
                    self.assertEqual(summary["state"], "missing")
                    self.assertEqual(summary["availability"], "missing")
                    self.assertIsNone(summary["count"])

                state_path = Path(state_dir)
                (state_path / "annotations.jsonl").write_text("", encoding="utf-8")
                (state_path / "action_intents.jsonl").write_text("", encoding="utf-8")
                for summary in (annotation_summary(), action_intent_summary()):
                    self.assertEqual(summary["state"], "bound")
                    self.assertEqual(summary["availability"], "present")
                    self.assertEqual(summary["count"], 0)

                with patch.object(Path, "open", side_effect=PermissionError("state file denied")):
                    for summary in (annotation_summary(), action_intent_summary()):
                        self.assertEqual(summary["state"], "unknown")
                        self.assertEqual(summary["availability"], "unavailable")
                        self.assertIsNone(summary["count"])
            finally:
                if previous is None:
                    os.environ.pop("AOA_DASHBOARD_STATE_ROOT", None)
                else:
                    os.environ["AOA_DASHBOARD_STATE_ROOT"] = previous


if __name__ == "__main__":
    unittest.main()
