from __future__ import annotations

import json
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .projection import build_projection
from .state_store import create_action_intent, create_annotation


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
MAX_BODY_BYTES = 32 * 1024


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "aoa-dashboard/0.1"

    def _json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("request body must be between 1 and 32768 bytes")
        value = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("request JSON must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/api/projection":
            try:
                self._json(build_projection())
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                self._json({"error": "projection_unavailable", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if route == "/healthz":
            self._json({"ok": True, "service": "aoa-dashboard", "read_model": "derived"})
            return
        if route == "/":
            route = "/index.html"
        if route.startswith("/api/"):
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        candidate = (WEB_ROOT / route.lstrip("/")).resolve()
        if WEB_ROOT not in candidate.parents and candidate != WEB_ROOT:
            self._json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return
        if not candidate.is_file():
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            body = self._body()
            if route == "/api/annotations":
                result = create_annotation(
                    str(body.get("author_ref", "operator:anonymous")),
                    str(body.get("target_ref", "goal:unknown")),
                    str(body.get("body", "")),
                )
                self._json(result, HTTPStatus.CREATED)
                return
            if route == "/api/action-intents":
                result = create_action_intent(
                    str(body.get("requested_by", "operator:anonymous")),
                    str(body.get("target_ref", "goal:unknown")),
                    str(body.get("owner_route", "owner:unresolved")),
                    str(body.get("summary", "")),
                )
                self._json(result, HTTPStatus.CREATED)
                return
            self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        except (ValueError, json.JSONDecodeError, UnicodeError) as exc:
            self._json({"error": "invalid_request", "detail": str(exc)}, HTTPStatus.BAD_REQUEST)
        except OSError as exc:
            self._json({"error": "state_write_failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("AOA_DASHBOARD_ACCESS_LOG", "1") != "0":
            super().log_message(format, *args)


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(f"aoa-dashboard listening on http://{host}:{port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve(os.environ.get("AOA_DASHBOARD_HOST", "127.0.0.1"), int(os.environ.get("AOA_DASHBOARD_PORT", "8765")))
