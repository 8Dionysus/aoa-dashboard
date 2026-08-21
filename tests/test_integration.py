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
        i18n = html.index('<script src="/i18n.js" defer></script>')
        theme = html.index('<script src="/theme.js" defer></script>')
        app = html.index('<script src="/app.js" defer></script>')
        self.assertLess(i18n, theme)
        self.assertLess(theme, app)
        self.assertIn('class="language-switch"', html)
        self.assertIn('data-theme-control', (ROOT / "web" / "theme.js").read_text(encoding="utf-8"))

    def test_installed_data_files_include_every_static_asset(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        data_files = project["tool"]["setuptools"]["data-files"]["share/aoa-dashboard/web"]
        self.assertEqual(
            set(data_files),
            {"web/index.html", "web/app.js", "web/i18n.js", "web/styles.css", "web/theme.js"},
        )

    def test_static_server_serves_bilingual_and_theme_assets(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                for route, marker in (
                    ("/i18n.js", "AoaDashboardI18n"),
                    ("/theme.js", "AoaDashboardTheme"),
                    ("/styles.css", ':root[data-theme="dark"]'),
                ):
                    connection.request("GET", route)
                    response = connection.getresponse()
                    body = response.read().decode("utf-8")
                    self.assertEqual(response.status, 200, route)
                    self.assertIn(marker, body, route)
                    self.assertTrue(response.getheader("Content-Type", "").startswith("text/"), route)
            finally:
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
