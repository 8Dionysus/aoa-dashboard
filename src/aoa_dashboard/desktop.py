"""Native desktop shell for the existing aoa-dashboard web surface.

The shell owns the application/window lifecycle and an internal loopback HTTP
server. It does not own the dashboard projection, role meaning, actor
lifecycle, or any action execution route.
"""

from __future__ import annotations

import json
import locale
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Literal, Mapping, Sequence

from .server import DashboardHTTPServer, DashboardHandler


APPLICATION_ID = "org.aoa.AoaDashboard"
LOOPBACK_HOST = "127.0.0.1"
PRESENTATION_HANDLER_NAME = "aoaDashboardPresentation"
PresentationLanguage = Literal["en", "ru"]
PresentationTheme = Literal["system", "light", "dark"]
PRESENTATION_LANGUAGES = frozenset({"en", "ru"})
PRESENTATION_THEMES = frozenset({"system", "light", "dark"})
BackendState = Literal["new", "running", "stopping", "stopped", "failed"]
ServerFactory = Callable[[tuple[str, int], type[BaseHTTPRequestHandler]], ThreadingHTTPServer]


_NATIVE_TEXT: dict[PresentationLanguage, dict[str, str]] = {
    "en": {
        "title": "AoA Dashboard",
        "status.starting": "Starting dashboard…",
        "status.loading": "Loading dashboard…",
        "status.connected": "Connected · loading projection…",
        "status.loaded": "Dashboard loaded",
        "status.backend_error": "Backend unavailable",
        "status.load_error": "Dashboard load error",
        "message.starting": "Starting dashboard…",
        "message.backend_error": "The dashboard backend could not start.",
        "message.load_error": "The dashboard could not load.",
    },
    "ru": {
        "title": "Панель AoA",
        "status.starting": "Запуск панели…",
        "status.loading": "Загрузка панели…",
        "status.connected": "Подключено · загрузка проекции…",
        "status.loaded": "Панель загружена",
        "status.backend_error": "Сервер панели недоступен",
        "status.load_error": "Ошибка загрузки панели",
        "message.starting": "Запуск панели…",
        "message.backend_error": "Не удалось запустить сервер панели.",
        "message.load_error": "Не удалось загрузить панель.",
    },
}


@dataclass(frozen=True)
class PresentationPreference:
    """The only values admitted across the WebKit-to-native bridge."""

    language: PresentationLanguage
    theme: PresentationTheme


def startup_language(
    locale_getter: Callable[[int], tuple[str | None, str | None]] = locale.getlocale,
) -> PresentationLanguage:
    """Return the honest native startup fallback derived from the host locale."""

    try:
        locale_name = locale_getter(locale.LC_MESSAGES)[0]
    except (AttributeError, IndexError, locale.Error, TypeError, ValueError):
        locale_name = None
    normalized = str(locale_name or "").strip().lower().replace("_", "-")
    return "ru" if normalized.startswith("ru") else "en"


def parse_presentation_message(payload: object) -> PresentationPreference | None:
    """Validate one exact, presentation-only bridge payload.

    The strict key set prevents the web surface from smuggling arbitrary text,
    commands, or operational data into the native shell.
    """

    if not isinstance(payload, Mapping) or set(payload) != {"language", "theme"}:
        return None
    language = payload.get("language")
    theme = payload.get("theme")
    if (
        type(language) is not str
        or language not in PRESENTATION_LANGUAGES
        or type(theme) is not str
        or theme not in PRESENTATION_THEMES
    ):
        return None
    return PresentationPreference(language=language, theme=theme)  # type: ignore[arg-type]


def presentation_from_javascript_value(value: object) -> PresentationPreference | None:
    """Decode WebKitGTK 6.0's JavaScriptCore.Value and validate its payload."""

    to_json = getattr(value, "to_json", None)
    if not callable(to_json):
        return None
    try:
        payload = json.loads(to_json(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parse_presentation_message(payload)


def native_text(language: PresentationLanguage, key: str) -> str:
    """Look up a bounded native presentation string."""

    return _NATIVE_TEXT[language][key]


def _create_backend_server(
    address: tuple[str, int], handler: type[BaseHTTPRequestHandler]
) -> DashboardHTTPServer:
    return DashboardHTTPServer(address, handler)


class DesktopDependencyError(RuntimeError):
    """Raised when the host lacks the GTK/WebKit runtime for the native shell."""


class BackendStartError(RuntimeError):
    """Raised when the application-owned HTTP backend cannot bind."""


class PresentationBridgeError(RuntimeError):
    """Raised when the native presentation message channel cannot be installed."""


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

        def __init__(
            self,
            *,
            backend_factory: Callable[[], DashboardBackend] = DashboardBackend,
            locale_getter: Callable[[int], tuple[str | None, str | None]] = locale.getlocale,
            style_manager: Any | None = None,
        ) -> None:
            # No NON_UNIQUE flag is set: Gio.Application provides single-instance
            # behavior for this stable application id.
            super().__init__(application_id=APPLICATION_ID)
            self._backend_factory = backend_factory
            self._style_manager = style_manager if style_manager is not None else Adw.StyleManager.get_default()
            self._backend: DashboardBackend | None = None
            self._window: Any | None = None
            self._stack: Any | None = None
            self._web_view: Any | None = None
            self._user_content_manager: Any | None = None
            self._title_label: Any | None = None
            self._status_label: Any | None = None
            self._status_state = "starting"
            self._status_key = "status.starting"
            initial_language = startup_language(locale_getter)
            self._status_text = native_text(initial_language, self._status_key)
            self._message_specs: dict[str, tuple[str, str | None]] = {}
            self._presentation = PresentationPreference(
                language=initial_language,
                theme="system",
            )
            self._apply_color_scheme(self._presentation.theme)

        @property
        def backend(self) -> DashboardBackend | None:
            return self._backend

        @property
        def load_state(self) -> str:
            return self._status_state

        @property
        def load_status(self) -> str:
            return self._status_text

        @property
        def language(self) -> PresentationLanguage:
            return self._presentation.language

        @property
        def theme_mode(self) -> PresentationTheme:
            return self._presentation.theme

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
            window.set_title(native_text(self.language, "title"))
            window.set_default_size(1280, 900)
            if hasattr(window, "set_size_request"):
                window.set_size_request(800, 600)

            toolbar = Adw.ToolbarView()
            header = Adw.HeaderBar()
            title = Gtk.Label(label=native_text(self.language, "title"))
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
            self._message_specs["starting"] = ("message.starting", None)
            self._stack.add_named(self._message_view("message.starting"), "starting")
            self._stack.set_visible_child_name("starting")
            toolbar.set_content(self._stack)
            window.set_content(toolbar)
            self._window = window
            self._title_label = title
            return window

        def _message_view(self, message_key: str, detail: str | None = None) -> Any:
            view = Gtk.Label(label=self._message_text(message_key, detail))
            view.set_wrap(True)
            view.set_margin_top(36)
            view.set_margin_bottom(36)
            view.set_margin_start(36)
            view.set_margin_end(36)
            view.set_selectable(True)
            return view

        def _message_text(self, message_key: str, detail: str | None = None) -> str:
            message = native_text(self.language, message_key)
            return f"{message}\n\n{detail}" if detail else message

        def _set_status(self, state: str, message_key: str) -> None:
            self._status_state = state
            self._status_key = message_key
            self._status_text = native_text(self.language, message_key)
            if self._status_label is not None:
                self._status_label.set_text(self._status_text)
                self._status_label.set_tooltip_text(self._status_text)
                self._status_label.remove_css_class("error")
                if state == "error":
                    self._status_label.add_css_class("error")

        def _show_message(self, name: str, message_key: str, detail: str | None = None) -> None:
            self._message_specs[name] = (message_key, detail)
            if self._stack is None:
                return
            child = self._stack.get_child_by_name(name)
            if child is None:
                self._stack.add_named(self._message_view(message_key, detail), name)
            else:
                child.set_text(self._message_text(message_key, detail))
            self._stack.set_visible_child_name(name)

        def _apply_color_scheme(self, theme: PresentationTheme) -> None:
            scheme = {
                "system": getattr(Adw.ColorScheme, "DEFAULT", Adw.ColorScheme.PREFER_LIGHT),
                "light": Adw.ColorScheme.FORCE_LIGHT,
                "dark": Adw.ColorScheme.FORCE_DARK,
            }[theme]
            self._style_manager.set_color_scheme(scheme)

        def _apply_presentation(self, preference: PresentationPreference) -> None:
            """Apply web-owned preferences without changing native lifecycle state."""

            self._presentation = preference
            self._apply_color_scheme(preference.theme)
            self._status_text = native_text(self.language, self._status_key)
            if self._window is not None:
                self._window.set_title(native_text(self.language, "title"))
            if self._title_label is not None:
                self._title_label.set_text(native_text(self.language, "title"))
            if self._status_label is not None:
                self._status_label.set_text(self._status_text)
                self._status_label.set_tooltip_text(self._status_text)
            if self._stack is not None:
                for name, (message_key, detail) in self._message_specs.items():
                    child = self._stack.get_child_by_name(name)
                    if child is not None:
                        child.set_text(self._message_text(message_key, detail))

        def _on_presentation_message(self, _manager: Any, value: Any) -> None:
            preference = presentation_from_javascript_value(value)
            if preference is not None:
                self._apply_presentation(preference)

        def _create_presentation_bridge(self) -> Any:
            manager = WebKit.UserContentManager()
            manager.connect(
                f"script-message-received::{PRESENTATION_HANDLER_NAME}",
                self._on_presentation_message,
            )
            if not manager.register_script_message_handler(PRESENTATION_HANDLER_NAME):
                raise PresentationBridgeError("could not register presentation message handler")
            return manager

        def _start_backend(self) -> None:
            backend: DashboardBackend | None = None
            try:
                backend = self._backend_factory()
                url = backend.start()
                manager = self._create_presentation_bridge()
            except (BackendStartError, PresentationBridgeError, OSError, RuntimeError, ValueError) as exc:
                if backend is not None:
                    backend.stop()
                self._set_status("error", "status.backend_error")
                self._show_message("backend-error", "message.backend_error", str(exc))
                return
            self._backend = backend
            self._user_content_manager = manager
            self._set_status("loading", "status.loading")
            self._web_view = WebKit.WebView(user_content_manager=manager)
            self._web_view.set_hexpand(True)
            self._web_view.set_vexpand(True)
            self._web_view.connect("load-changed", self._on_load_changed)
            self._web_view.connect("load-failed", self._on_load_failed)
            self._stack.add_named(self._web_view, "web")
            self._stack.set_visible_child_name("web")
            self._web_view.load_uri(url)

        def _on_load_changed(self, _web_view: Any, event: Any) -> None:
            if event == WebKit.LoadEvent.STARTED:
                self._set_status("loading", "status.loading")
            elif event == WebKit.LoadEvent.COMMITTED:
                self._set_status("loading", "status.connected")
            elif event == WebKit.LoadEvent.FINISHED:
                self._set_status("loaded", "status.loaded")

        def _on_load_failed(self, _web_view: Any, _event: Any, _failing_uri: str, error: Any) -> bool:
            detail = getattr(error, "message", None) or str(error)
            self._set_status("error", "status.load_error")
            self._show_message("web-error", "message.load_error", detail)
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
