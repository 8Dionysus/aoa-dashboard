from __future__ import annotations

import json
import socket
import sys
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.desktop import (  # noqa: E402
    APPLICATION_ID,
    GTK_AVAILABLE,
    LOOPBACK_HOST,
    BackendStartError,
    DashboardBackend,
    DashboardApplication,
    dashboard_url,
)


class DesktopBackendTests(unittest.TestCase):
    def test_ephemeral_loopback_binding_and_url_handoff(self) -> None:
        backend = DashboardBackend()
        url = backend.start()
        self.assertTrue(url.startswith(f"http://{LOOPBACK_HOST}:"))
        self.assertNotEqual(int(url.rsplit(":", 1)[1].rstrip("/")), 0)
        self.assertEqual(backend.snapshot.state, "running")
        connection = HTTPConnection(LOOPBACK_HOST, int(url.rsplit(":", 1)[1].rstrip("/")), timeout=3)
        try:
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["service"], "aoa-dashboard")
            self.assertEqual(payload["read_model"], "derived")
        finally:
            connection.close()
            backend.stop()
        self.assertEqual(backend.snapshot.state, "stopped")
        self.assertFalse(backend.snapshot.thread_alive)

    def test_stop_is_clean_and_idempotent(self) -> None:
        backend = DashboardBackend()
        backend.start()
        backend.stop()
        backend.stop()
        self.assertEqual(backend.snapshot.state, "stopped")
        with self.assertRaises(OSError):
            with socket.create_connection((LOOPBACK_HOST, int(backend.url.rsplit(":", 1)[1].rstrip("/"))), timeout=1):
                pass

    def test_backend_rejects_non_loopback_host(self) -> None:
        with self.assertRaises(ValueError):
            DashboardBackend(host="0.0.0.0")

    def test_start_failure_is_explicit(self) -> None:
        def failing_factory(_address: tuple[str, int], _handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
            raise OSError("test bind failure")

        backend = DashboardBackend(server_factory=failing_factory)
        with self.assertRaises(BackendStartError) as context:
            backend.start()
        self.assertIn("test bind failure", str(context.exception))
        self.assertEqual(backend.snapshot.state, "failed")
        self.assertEqual(backend.snapshot.error, "test bind failure")

    def test_dashboard_url_formats_ipv6_without_changing_port(self) -> None:
        self.assertEqual(dashboard_url(("::1", 4242, 0, 0)), "http://[::1]:4242/")

    def test_application_id_is_stable(self) -> None:
        self.assertEqual(APPLICATION_ID, "org.aoa.AoaDashboard")

    @unittest.skipUnless(GTK_AVAILABLE, "GTK4, Libadwaita, and WebKitGTK 6.0 are not installed")
    def test_application_shutdown_stops_owned_backend(self) -> None:
        backend = DashboardBackend()
        backend.start()
        application = DashboardApplication(backend_factory=lambda: backend)
        application._backend = backend
        application.do_shutdown()
        self.assertEqual(backend.snapshot.state, "stopped")
        self.assertFalse(backend.snapshot.thread_alive)


if __name__ == "__main__":
    unittest.main()
