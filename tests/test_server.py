from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.server import DashboardHandler  # noqa: E402


class ServerTests(unittest.TestCase):
    def test_operator_ui_exposes_actor_activity_surface(self) -> None:
        root = Path(__file__).resolve().parents[1]
        html = (root / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (root / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="actor-activity"', html)
        self.assertIn("function renderActorActivity", javascript)
        self.assertIn("data.actor_activity", javascript)
        self.assertIn("master-filter current-head evidence", javascript)
        self.assertIn("currentness.evidence_refs", javascript)

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


if __name__ == "__main__":
    unittest.main()
