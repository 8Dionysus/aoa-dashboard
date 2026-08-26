"""Native desktop shell for the existing aoa-dashboard web surface.

The shell owns the application/window lifecycle and an internal loopback HTTP
server. It does not own the dashboard projection, role meaning, actor
lifecycle, or any action execution route.
"""

from __future__ import annotations

import argparse
import json
import locale
import signal
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Literal, Mapping, Sequence

from .server import DashboardHTTPServer, DashboardHandler


APPLICATION_ID = "org.aoa.AoaDashboard"
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DESKTOP_PORT = 8765
PRESENTATION_HANDLER_NAME = "aoaDashboardPresentation"
PRESENTATION_READ_SCRIPT = """
(() => {
  const api = window.AoaDashboardPreferences;
  if (!api || typeof api.read !== "function") return null;
  const preferences = api.read(window.localStorage);
  if (!preferences || typeof preferences.language !== "string") return null;
  return {language: preferences.language, theme: preferences.theme};
})()
"""
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


def presentation_document_sync_script(preference: PresentationPreference) -> str:
    """Return a bounded script that reuses the web-owned preference controls.

    The native shell does not own a second preference store or translation
    catalog.  This small repair is only a recovery path for a page whose
    persisted preference was changed before the document finished loading.
    Normal web preference changes already update the document themselves.
    """

    expected = json.dumps(
        {"language": preference.language, "theme": preference.theme},
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return """
(() => {
  const expected = __AOA_DASHBOARD_EXPECTED__;
  const dictionary = window.AoaDashboardI18n?.dictionaries?.[expected.language] || null;
  const expectedTitle = dictionary && typeof dictionary["app.title"] === "string" ? dictionary["app.title"] : null;
  const result = {
    language_changed: false,
    theme_changed: false,
    document_language: document.documentElement ? document.documentElement.lang : null,
    theme_mode: null,
  };
  const languageButton = document.querySelector(`[data-language="${expected.language}"]`);
  const titleNeedsUpdate = expectedTitle && document.title !== expectedTitle;
  if (document.documentElement && (document.documentElement.lang !== expected.language || titleNeedsUpdate) && languageButton) {
    languageButton.click();
    result.language_changed = true;
  }
  const themeControl = document.getElementById("theme-mode");
  if (themeControl) {
    result.theme_mode = themeControl.value || null;
    if (themeControl.value !== expected.theme) {
      themeControl.value = expected.theme;
      themeControl.dispatchEvent(new Event("change", {bubbles: true}));
      result.theme_changed = true;
      result.theme_mode = themeControl.value || null;
    }
  }
  result.document_language = document.documentElement ? document.documentElement.lang : null;
  return result;
})()
""".replace("__AOA_DASHBOARD_EXPECTED__", expected)


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


def _javascript_value_to_python(value: object) -> object | None:
    to_json = getattr(value, "to_json", None)
    if not callable(to_json):
        return None
    try:
        return json.loads(to_json(0))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


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
        binding_path: str | None = None,
        handler: type[BaseHTTPRequestHandler] = DashboardHandler,
        server_factory: ServerFactory = _create_backend_server,
    ) -> None:
        if host != LOOPBACK_HOST:
            raise ValueError(f"desktop backend must bind loopback host {LOOPBACK_HOST}")
        if not 0 <= port <= 65535:
            raise ValueError("desktop backend port must be between 0 and 65535")
        self.host = host
        self.port = port
        self.binding_path = binding_path
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
                setattr(server, "binding_path", self.binding_path)
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
        stop_error: Exception | None = None
        try:
            if (
                server is not None
                and thread is not None
                and thread.is_alive()
                and thread is not threading.current_thread()
            ):
                server.shutdown()
        except Exception as exc:  # pragma: no cover - defensive host/runtime path
            stop_error = exc
        finally:
            if server is not None:
                try:
                    server.server_close()
                except Exception as exc:  # pragma: no cover - defensive host/runtime path
                    stop_error = stop_error or exc
            if thread is not None and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=5)
        with self._lock:
            thread_alive = bool(thread and thread.is_alive())
            self._state = "failed" if thread_alive else "stopped"
            if stop_error is not None:
                self._error = str(stop_error)


try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("WebKit", "6.0")
    from gi.repository import Adw, GLib, Gtk, WebKit  # type: ignore[import-not-found]
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


def install_shutdown_signal_handlers(application: Any) -> Callable[[], None]:
    """Route ordinary SIGINT/SIGTERM through the GTK main loop.

    Python signal handlers run on the main thread, but GTK object work belongs
    in the main loop.  Scheduling ``quit`` keeps the same shutdown path for a
    terminal interrupt, a service stop, and an explicit application close.
    """

    previous: dict[int, Any] = {}
    scheduled = False

    def quit_from_main_loop() -> bool:
        application.quit()
        return False

    def request_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal scheduled
        if scheduled:
            return
        scheduled = True
        try:
            GLib.idle_add(
                quit_from_main_loop,
                priority=getattr(GLib, "PRIORITY_HIGH", 0),
            )
        except Exception:  # pragma: no cover - only if GLib is already tearing down
            application.quit()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, request_shutdown)
    except Exception:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        raise

    def restore() -> None:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    return restore


if GTK_AVAILABLE:

    class DashboardApplication(Adw.Application):  # type: ignore[misc,valid-type]
        """Single-instance GTK application embedding the existing dashboard UI."""

        def __init__(
            self,
            *,
            backend_factory: Callable[[], DashboardBackend] | None = None,
            binding_path: str | None = None,
            locale_getter: Callable[[int], tuple[str | None, str | None]] = locale.getlocale,
            style_manager: Any | None = None,
            desktop_port: int = DEFAULT_DESKTOP_PORT,
        ) -> None:
            # No NON_UNIQUE flag is set: Gio.Application provides single-instance
            # behavior for this stable application id.
            super().__init__(application_id=APPLICATION_ID)
            self._backend_factory = backend_factory or (
                lambda: DashboardBackend(binding_path=binding_path, port=desktop_port)
            )
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
            self._shutdown_started = False
            self._presentation_read_requested = False
            self._persisted_read_complete = False
            self._document_sync_expected: PresentationPreference | None = None
            self._document_sync_result: dict[str, Any] = {"state": "not_requested"}
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
            if self._shutdown_started:
                return
            if self._window is None:
                self._window = self._build_window()
                self._window.present()
                self._start_backend()
            else:
                self._window.present()

        def do_shutdown(self) -> None:
            if self._shutdown_started:
                return
            self._shutdown_started = True
            web_view = self._web_view
            backend = self._backend
            try:
                if web_view is not None:
                    stop_loading = getattr(web_view, "stop_loading", None)
                    if callable(stop_loading):
                        stop_loading()
                if backend is not None:
                    backend.stop()
            finally:
                self._web_view = None
                self._user_content_manager = None
                self._backend = None
                self._document_sync_expected = None
                Adw.Application.do_shutdown(self)

        def _build_window(self) -> Any:
            window = Adw.ApplicationWindow(application=self)
            window.set_accessible_role(Gtk.AccessibleRole.APPLICATION)
            window.connect("close-request", self._on_window_close)
            window.set_title(native_text(self.language, "title"))
            window.set_default_size(1280, 900)
            if hasattr(window, "set_size_request"):
                window.set_size_request(800, 600)

            toolbar = Adw.ToolbarView()
            toolbar.set_accessible_role(Gtk.AccessibleRole.TOOLBAR)
            header = Adw.HeaderBar()
            header.set_accessible_role(Gtk.AccessibleRole.BANNER)
            title = Gtk.Label(label=native_text(self.language, "title"))
            title.set_accessible_role(Gtk.AccessibleRole.HEADING)
            title.add_css_class("title")
            header.set_title_widget(title)
            self._status_label = Gtk.Label(label=self._status_text)
            self._status_label.set_accessible_role(Gtk.AccessibleRole.STATUS)
            self._status_label.add_css_class("dim-label")
            self._status_label.set_tooltip_text(self._status_text)
            header.pack_end(self._status_label)
            toolbar.add_top_bar(header)

            self._stack = Gtk.Stack()
            self._stack.set_accessible_role(Gtk.AccessibleRole.MAIN)
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

        def _on_window_close(self, _window: Any) -> bool:
            self.quit()
            return False

        def _message_view(self, message_key: str, detail: str | None = None) -> Any:
            view = Gtk.Label(label=self._message_text(message_key, detail))
            role = Gtk.AccessibleRole.ALERT if message_key in {"message.backend_error", "message.load_error"} else Gtk.AccessibleRole.STATUS
            view.set_accessible_role(role)
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

        @staticmethod
        def _widget_accessibility_snapshot(widget: Any) -> dict[str, Any] | None:
            """Observe direct GTK widget properties without contacting AT-SPI."""

            if widget is None:
                return None
            result: dict[str, Any] = {"type": type(widget).__name__}
            for method_name, key in (
                ("get_accessible_role", "role"),
                ("get_visible", "visible"),
                ("get_mapped", "mapped"),
                ("get_focusable", "focusable"),
                ("get_can_focus", "can_focus"),
            ):
                method = getattr(widget, method_name, None)
                if not callable(method):
                    continue
                try:
                    value = method()
                    if key == "role":
                        value = getattr(value, "value_nick", None) or getattr(value, "value_name", None) or str(value)
                    result[key] = value
                except Exception as exc:  # pragma: no cover - host API variance
                    result[key] = f"error:{type(exc).__name__}:{exc}"
            return result

        def accessibility_snapshot(self) -> dict[str, Any]:
            """Return bounded native observations available without a display."""

            return {
                "observation_contract": "direct-gtk-widget-properties-v1",
                "window": self._widget_accessibility_snapshot(self._window),
                "title": self._widget_accessibility_snapshot(self._title_label),
                "status": self._widget_accessibility_snapshot(self._status_label),
                "main": self._widget_accessibility_snapshot(self._stack),
                "web_view": self._widget_accessibility_snapshot(self._web_view),
                "document_sync": dict(self._document_sync_result),
            }

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
            if preference is None:
                return
            expected = self._document_sync_expected
            if expected is not None:
                if preference == expected:
                    self._apply_presentation(preference)
                    self._document_sync_expected = None
                return
            self._apply_presentation(preference)
            if self._persisted_read_complete:
                self._sync_web_document(preference)

        def _sync_web_document(self, preference: PresentationPreference) -> None:
            if self._shutdown_started or self._web_view is None:
                return
            evaluate = getattr(self._web_view, "evaluate_javascript", None)
            if not callable(evaluate):
                return
            self._document_sync_expected = preference
            try:
                evaluate(
                    presentation_document_sync_script(preference),
                    -1,
                    None,
                    "aoa-dashboard://presentation-sync",
                    None,
                    self._on_document_sync_result,
                    "presentation-sync",
                )
            except Exception as exc:  # pragma: no cover - WebKit teardown/race
                self._document_sync_expected = None
                self._document_sync_result = {"state": "error", "error": str(exc)}

        def _on_document_sync_result(self, web_view: Any, result: Any, _label: str) -> None:
            try:
                finish = getattr(web_view, "evaluate_javascript_finish")
                value = _javascript_value_to_python(finish(result))
            except Exception as exc:  # pragma: no cover - WebKit teardown/race
                self._document_sync_expected = None
                self._document_sync_result = {"state": "error", "error": str(exc)}
                return
            if isinstance(value, Mapping):
                self._document_sync_result = {"state": "observed", **dict(value)}
                if value.get("language_changed") or value.get("theme_changed"):
                    GLib.timeout_add(250, self._expire_document_sync)
                    return
            self._document_sync_expected = None

        def _expire_document_sync(self) -> bool:
            self._document_sync_expected = None
            return False

        def _request_persisted_presentation(self) -> None:
            if self._presentation_read_requested or self._shutdown_started or self._web_view is None:
                return
            evaluate = getattr(self._web_view, "evaluate_javascript", None)
            if not callable(evaluate):
                return
            self._presentation_read_requested = True
            try:
                evaluate(
                    PRESENTATION_READ_SCRIPT,
                    -1,
                    None,
                    "aoa-dashboard://presentation-read",
                    None,
                    self._on_persisted_presentation_result,
                    "presentation-read",
                )
            except Exception as exc:  # pragma: no cover - WebKit teardown/race
                self._persisted_read_complete = True
                self._document_sync_result = {"state": "error", "error": str(exc)}

        def _on_persisted_presentation_result(self, web_view: Any, result: Any, _label: str) -> None:
            if self._shutdown_started:
                return
            self._persisted_read_complete = True
            try:
                finish = getattr(web_view, "evaluate_javascript_finish")
                preference = presentation_from_javascript_value(finish(result))
            except Exception:  # pragma: no cover - WebKit teardown/race
                return
            if preference is not None:
                self._apply_presentation(preference)
                self._sync_web_document(preference)

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
                self._request_persisted_presentation()

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
    raw_args = list(argv) if argv is not None else list(sys.argv)
    program = raw_args[0] if raw_args else "aoa-dashboard-desktop"
    parser = argparse.ArgumentParser(description="Run the aoa-dashboard desktop shell")
    parser.add_argument("--binding", type=str, help="explicit owner-qualified runtime Goal binding JSON")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DESKTOP_PORT,
        help="loopback port for the persistent WebKit origin (0 selects an ephemeral port)",
    )
    parsed, gio_args = parser.parse_known_args(raw_args[1:] if raw_args else [])
    application = DashboardApplication(binding_path=parsed.binding, desktop_port=parsed.port)
    restore_signal_handlers = install_shutdown_signal_handlers(application)
    try:
        return int(application.run([program, *gio_args]))
    except KeyboardInterrupt:
        # Gio's SIGINT fallback raises after asking the application to quit.
        # Treat that operator close as a normal application shutdown.
        application.quit()
        return 0
    finally:
        restore_signal_handlers()


if __name__ == "__main__":
    raise SystemExit(main())
