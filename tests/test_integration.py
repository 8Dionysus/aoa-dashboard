from __future__ import annotations

import tomllib
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import threading


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aoa_dashboard.server import DashboardHandler  # noqa: E402


class IntegrationWiringTests(unittest.TestCase):
    def test_scripts_are_wired_in_dependency_order(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        preferences = html.index('<script src="/preferences.js"></script>')
        i18n = html.index('<script src="/i18n.js" defer></script>')
        theme = html.index('<script src="/theme.js" defer></script>')
        ui_state = html.index('<script src="/ui_state.js" defer></script>')
        app = html.index('<script src="/app.js" defer></script>')
        self.assertLess(preferences, i18n)
        self.assertLess(i18n, theme)
        self.assertLess(theme, ui_state)
        self.assertLess(ui_state, app)
        self.assertIn("AoaDashboardPreferences.read", html)
        self.assertIn('class="language-switch"', html)
        self.assertIn('data-theme-control', (ROOT / "web" / "theme.js").read_text(encoding="utf-8"))

    def test_installed_data_files_include_every_static_asset(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        data_files = project["tool"]["setuptools"]["data-files"]["share/aoa-dashboard/web"]
        self.assertEqual(
            set(data_files),
            {"web/index.html", "web/app.js", "web/favicon.svg", "web/i18n.js", "web/preferences.js", "web/styles.css", "web/theme.js", "web/ui_state.js"},
        )
        self.assertEqual(
            project["tool"]["setuptools"]["data-files"]["share/aoa-dashboard/config"],
            ["config/bootstrap.json"],
        )
        self.assertEqual(
            set(project["tool"]["setuptools"]["data-files"]["share/aoa-dashboard/contracts"]),
            {"contracts/runtime_binding.schema.json", "contracts/goal_anchor.schema.json", "contracts/goal-context-projection.schema.json"},
        )
        self.assertNotIn("config/demo/first-slice.json", project["tool"]["setuptools"]["data-files"]["share/aoa-dashboard/config"])

    def test_static_server_serves_bilingual_and_theme_assets(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                for route, marker, content_type in (
                    ("/favicon.svg", "<svg", "image/svg+xml"),
                    ("/i18n.js", "AoaDashboardI18n", "text/"),
                    ("/preferences.js", "AoaDashboardPreferences", "text/"),
                    ("/theme.js", "AoaDashboardTheme", "text/"),
                    ("/ui_state.js", "AoaDashboardUiState", "text/"),
                    ("/styles.css", ':root[data-theme="dark"]', "text/"),
                ):
                    connection.request("GET", route)
                    response = connection.getresponse()
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200, route)
                    self.assertIn(marker, body, route)
                    self.assertTrue(response.getheader("Content-Type", "").startswith(content_type), route)
            finally:
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
