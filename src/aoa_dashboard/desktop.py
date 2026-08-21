"""Native desktop shell for the existing aoa-dashboard web surface.

The shell owns the application/window lifecycle and an internal loopback HTTP
server. It does not own the dashboard projection, role meaning, actor
lifecycle, or any action execution route.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Literal, Sequence

from .server import DashboardHTTPServer, DashboardHandler


APPLICATION_ID = "org.aoa.AoaDashboard"
LOOPBACK_HOST = "127.0.0.1"
BackendState = Literal["new", "running", "stopping", "stopped", "failed"]
ServerFactory = Callable[[tuple[str, int], type[BaseHTTPRequestHandler]], ThreadingHTTPServer]


def _create_backend_server(
    address: tuple[str, int], handler: type[BaseHTTPRequestHandler]
) -> DashboardHTTPServer:
    return DashboardHTTPServer(address, handler)


class DesktopDependencyError(RuntimeError):
    """Raised when the host lacks the GTK/WebKit runtime for the native shell."""


class BackendStartError(RuntimeError):
    """Raised when the application-owned HTTP backend cannot bind."""


def dashboard_url(server_address: tuple[str, int] | tuple[str, int, int, int]) -> str:
    """Return the URL handed from the application-owned server to WebKit."""

    host = server_address[0]
    port = server_address[1]
    display_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{display_host}:{port}/"


@dataclass(frozen=True)
class BackendSnapshot:
    state: BackendState
    url: str | None
    error: str | None
    thread_alive: bool


class DashboardBackend:
    """Lifecycle wrapper for one application-owned, ephemeral loopback server."""

    def __init__(
        self,
        *,
        host: str = LOOPBACK_HOST,
        port: int = 0,
        handler: type[BaseHTTPRequestHandler] = DashboardHandler,
        server_factory: ServerFactory = _create_backend_server,
    ) -> None:
        if host != LOOPBACK_HOST:
            raise ValueError(f"desktop backend must bind loopback host {LOOPBACK_HOST}")
        if not 0 <= port <= 65535:
            raise ValueError("desktop backend port must be between 0 and 65535")
        self.host = host
        self.port = port
        self.handler = handler
        self._server_factory = server_factory
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._state: BackendState = "new"
        self._url: str | None = None
        self._error: str | None = None

    @property
    def snapshot(self) -> BackendSnapshot:
        with self._lock:
            return BackendSnapshot(
                state=self._state,
                url=self._url,
                error=self._error,
                thread_alive=bool(self._thread and self._thread.is_alive()),
            )

    @property
    def url(self) -> str:
        with self._lock:
            if self._url is None:
                raise RuntimeError("dashboard backend has not started")
            return self._url

    def start(self) -> str:
        with self._lock:
            if self._state == "running":
                return self.url
            if self._state != "new":
                raise RuntimeError(f"dashboard backend cannot start from {self._state}")
            server: ThreadingHTTPServer | None = None
            try:
                server = self._server_factory((self.host, self.port), self.handler)
                address = server.server_address
                self._server = server
                self._url = dashboard_url(address)
                self._state = "running"
                self._thread = threading.Thread(
                    target=self._serve,
                    name="aoa-dashboard-backend",
                    daemon=True,
                )
                self._thread.start()
                return self._url
            except Exception as exc:
                self._state = "failed"
                self._error = str(exc)
                if server is not None:
                    server.server_close()
                raise BackendStartError(f"could not start dashboard backend: {exc}") from exc

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return
        try:
            server.serve_forever(poll_interval=0.05)
        except Exception as exc:
            with self._lock:
                if self._state not in {"stopping", "stopped"}:
                    self._state = "failed"
                    self._error = str(exc)

    def stop(self) -> None:
        with self._lock:
            if self._state in {"new", "stopped"}:
                if self._state == "new":
                    self._state = "stopped"
                return
            server = self._server
            thread = self._thread
            self._state = "stopping"
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            self._state = "stopped"


try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Adw, Gtk, WebKit  # type: ignore[import-not-found]
except (ImportError, ValueError) as exc:  # pragma: no cover - exercised on non-GTK CI hosts
    GTK_AVAILABLE = False
    GTK_IMPORT_ERROR: Exception | None = exc
else:
    GTK_AVAILABLE = True
    GTK_IMPORT_ERROR = None


def require_desktop_dependencies() -> None:
    if not GTK_AVAILABLE:
        detail = str(GTK_IMPORT_ERROR) if GTK_IMPORT_ERROR else "GTK runtime is unavailable"
        raise DesktopDependencyError(
            "native shell requires PyGObject with GTK4, Libadwaita 1, and WebKitGTK 6.0: " + detail
        )


if GTK_AVAILABLE:

    class DashboardApplication(Adw.Application):  # type: ignore[misc,valid-type]
        """Single-instance GTK application embedding the existing dashboard UI."""

        def __init__(self, *, backend_factory: Callable[[], DashboardBackend] = DashboardBackend) -> None:
            # No NON_UNIQUE flag is set: Gio.Application provides single-instance
            # behavior for this stable application id.
            super().__init__(application_id=APPLICATION_ID)
            self._backend_factory = backend_factory
            self._backend: DashboardBackend | None = None
            self._window: Any | None = None
            self._stack: Any | None = None
            self._web_view: Any | None = None
            self._status_label: Any | None = None
            self._status_state = "starting"
            self._status_text = "Starting dashboard…"

        @property
        def backend(self) -> DashboardBackend | None:
            return self._backend

        @property
        def load_state(self) -> str:
            return self._status_state

        @property
        def load_status(self) -> str:
            return self._status_text

        def do_activate(self) -> None:
            if self._window is None:
                self._window = self._build_window()
                self._window.present()
                self._start_backend()
            else:
                self._window.present()

        def do_shutdown(self) -> None:
            if self._backend is not None:
                self._backend.stop()
                self._backend = None
            Adw.Application.do_shutdown(self)

        def _build_window(self) -> Any:
            window = Adw.ApplicationWindow(application=self)
            window.set_title("AoA Dashboard")
            window.set_default_size(1280, 900)

            toolbar = Adw.ToolbarView()
            header = Adw.HeaderBar()
            title = Gtk.Label(label="AoA Dashboard")
            title.add_css_class("title")
            header.set_title_widget(title)
            self._status_label = Gtk.Label(label=self._status_text)
            self._status_label.add_css_class("dim-label")
            self._status_label.set_tooltip_text(self._status_text)
            header.pack_end(self._status_label)
            toolbar.add_top_bar(header)

            self._stack = Gtk.Stack()
            self._stack.set_hexpand(True)
            self._stack.set_vexpand(True)
            self._stack.add_named(self._message_view("Starting dashboard…"), "starting")
            self._stack.set_visible_child_name("starting")
            toolbar.set_content(self._stack)
            window.set_content(toolbar)
            return window

        def _message_view(self, message: str) -> Any:
            view = Gtk.Label(label=message)
            view.set_wrap(True)
            view.set_margin_top(36)
            view.set_margin_bottom(36)
            view.set_margin_start(36)
            view.set_margin_end(36)
            view.set_selectable(True)
            return view

        def _set_status(self, state: str, message: str) -> None:
            self._status_state = state
            self._status_text = message
            if self._status_label is not None:
                self._status_label.set_text(message)
                self._status_label.set_tooltip_text(message)
                self._status_label.remove_css_class("error")
                if state == "error":
                    self._status_label.add_css_class("error")

        def _show_message(self, name: str, message: str) -> None:
            if self._stack is None:
                return
            child = self._stack.get_child_by_name(name)
            if child is None:
                self._stack.add_named(self._message_view(message), name)
            self._stack.set_visible_child_name(name)

        def _start_backend(self) -> None:
            try:
                backend = self._backend_factory()
                url = backend.start()
            except (BackendStartError, OSError, RuntimeError, ValueError) as exc:
                self._set_status("error", "Backend unavailable")
                self._show_message("backend-error", f"The dashboard backend could not start.\n\n{exc}")
                return
            self._backend = backend
            self._set_status("loading", "Loading dashboard…")
            self._web_view = WebKit.WebView()
            self._web_view.set_hexpand(True)
            self._web_view.set_vexpand(True)
            self._web_view.connect("load-changed", self._on_load_changed)
            self._web_view.connect("load-failed", self._on_load_failed)
            self._stack.add_named(self._web_view, "web")
            self._stack.set_visible_child_name("web")
            self._web_view.load_uri(url)

        def _on_load_changed(self, _web_view: Any, event: Any) -> None:
            if event == WebKit.LoadEvent.STARTED:
                self._set_status("loading", "Loading dashboard…")
            elif event == WebKit.LoadEvent.COMMITTED:
                self._set_status("loading", "Connected · loading projection…")
            elif event == WebKit.LoadEvent.FINISHED:
                self._set_status("loaded", "Dashboard loaded")

        def _on_load_failed(self, _web_view: Any, _event: Any, _failing_uri: str, error: Any) -> bool:
            detail = getattr(error, "message", None) or str(error)
            self._set_status("error", "Dashboard load error")
            self._show_message("web-error", f"The dashboard could not load.\n\n{detail}")
            return False

else:

    class DashboardApplication:  # pragma: no cover - exercised on non-GTK CI hosts
        def __init__(self, **_kwargs: Any) -> None:
            require_desktop_dependencies()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the native application and return its Gio application exit code."""

    try:
        require_desktop_dependencies()
    except DesktopDependencyError as exc:
        print(f"aoa-dashboard desktop shell unavailable: {exc}", file=sys.stderr)
        return 2
    application = DashboardApplication()
    try:
        return int(application.run(list(argv) if argv is not None else sys.argv))
    except KeyboardInterrupt:
        # Gio's SIGINT fallback raises after asking the application to quit.
        # Treat that operator close as a normal application shutdown.
        application.quit()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
