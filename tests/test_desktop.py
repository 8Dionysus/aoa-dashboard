from __future__ import annotations

import json
import socket
import sys
import unittest
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aoa_dashboard.desktop import (  # noqa: E402
    APPLICATION_ID,
    DEFAULT_DESKTOP_PORT,
    GTK_AVAILABLE,
    LOOPBACK_HOST,
    BackendStartError,
    DashboardBackend,
    DashboardApplication,
    PresentationPreference,
    PRESENTATION_READ_SCRIPT,
    PRESENTATION_HANDLER_NAME,
    native_text,
    parse_presentation_message,
    presentation_document_sync_script,
    presentation_from_javascript_value,
    install_shutdown_signal_handlers,
    startup_language,
    dashboard_url,
)
import aoa_dashboard.desktop as desktop_module  # noqa: E402


class FakeJavascriptValue:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    def to_json(self, _indent: int) -> str:
        return self.raw


class FakeStyleManager:
    def __init__(self) -> None:
        self.schemes: list[object] = []

    def set_color_scheme(self, scheme: object) -> None:
        self.schemes.append(scheme)


class FakeWidget:
    def __init__(self) -> None:
        self.text = ""
        self.tooltip = ""
        self.title = ""
        self.css_classes: set[str] = set()
        self.role = "none"
        self.visible = True
        self.mapped = True
        self.focusable = False
        self.can_focus = False

    def set_text(self, value: str) -> None:
        self.text = value

    def set_tooltip_text(self, value: str) -> None:
        self.tooltip = value

    def set_title(self, value: str) -> None:
        self.title = value

    def set_accessible_role(self, value: object) -> None:
        self.role = value

    def get_accessible_role(self) -> object:
        return self.role

    def get_visible(self) -> bool:
        return self.visible

    def get_mapped(self) -> bool:
        return self.mapped

    def get_focusable(self) -> bool:
        return self.focusable

    def get_can_focus(self) -> bool:
        return self.can_focus

    def remove_css_class(self, value: str) -> None:
        self.css_classes.discard(value)

    def add_css_class(self, value: str) -> None:
        self.css_classes.add(value)


class FakeStack:
    def __init__(self) -> None:
        self.children: dict[str, FakeWidget] = {}
        self.visible_name: str | None = None

    def get_child_by_name(self, name: str) -> FakeWidget | None:
        return self.children.get(name)

    def add_named(self, child: FakeWidget, name: str) -> None:
        self.children[name] = child

    def set_visible_child_name(self, name: str) -> None:
        self.visible_name = name


class FakeWebView:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def evaluate_javascript(self, *args: object) -> None:
        self.calls.append(args)

    def evaluate_javascript_finish(self, result: object) -> object:
        return result


class DesktopBackendTests(unittest.TestCase):
    def test_native_window_and_system_theme_contract_are_bounded(self) -> None:
        source = Path(desktop_module.__file__).read_text(encoding="utf-8")
        self.assertIn("set_default_size(1280, 900)", source)
        self.assertIn("set_size_request(800, 600)", source)
        self.assertIn('getattr(Adw.ColorScheme, "DEFAULT"', source)
        self.assertIn("Gtk.AccessibleRole.APPLICATION", source)
        self.assertIn("Gtk.AccessibleRole.STATUS", source)
        self.assertIn("direct-gtk-widget-properties-v1", source)

    def test_document_sync_script_is_bounded_and_reuses_web_controls(self) -> None:
        script = presentation_document_sync_script(
            PresentationPreference(language="ru", theme="dark")
        )
        self.assertIn('"language":"ru"', script)
        self.assertIn('"theme":"dark"', script)
        self.assertIn('[data-language="${expected.language}"]', script)
        self.assertIn("expectedTitle", script)
        self.assertIn("document.title", script)
        self.assertIn('getElementById("theme-mode")', script)
        self.assertIn("dispatchEvent(new Event(\"change\"", script)
        self.assertNotIn("localStorage.setItem", script)

    def test_native_startup_locale_and_bridge_payload_are_strictly_bounded(self) -> None:
        self.assertEqual(startup_language(lambda _category: ("ru_RU", "UTF-8")), "ru")
        self.assertEqual(startup_language(lambda _category: ("fr_FR", "UTF-8")), "en")
        self.assertEqual(startup_language(lambda _category: (None, None)), "en")

        self.assertEqual(
            parse_presentation_message({"language": "ru", "theme": "dark"}),
            PresentationPreference(language="ru", theme="dark"),
        )
        for payload in (
            None,
            [],
            {"language": "ru"},
            {"language": "ru", "theme": "dark", "title": "unsafe"},
            {"language": "ru-RU", "theme": "dark"},
            {"language": "en", "theme": "blue"},
            {"language": True, "theme": "dark"},
        ):
            self.assertIsNone(parse_presentation_message(payload))

        self.assertEqual(
            presentation_from_javascript_value(FakeJavascriptValue('{"language":"en","theme":"light"}')),
            PresentationPreference(language="en", theme="light"),
        )
        self.assertIsNone(presentation_from_javascript_value(FakeJavascriptValue("not-json")))
        self.assertIsNone(presentation_from_javascript_value({"language": "ru", "theme": "dark"}))

    @unittest.skipUnless(GTK_AVAILABLE, "GTK4, Libadwaita, and WebKitGTK 6.0 are not installed")
    def test_native_bridge_applies_live_preferences_and_preserves_state(self) -> None:
        from gi.repository import Adw

        style_manager = FakeStyleManager()
        application = DashboardApplication(
            locale_getter=lambda _category: ("ru_RU", "UTF-8"),
            style_manager=style_manager,
        )
        self.assertEqual(application.language, "ru")
        self.assertEqual(application.theme_mode, "system")
        self.assertEqual(application.load_status, native_text("ru", "status.starting"))
        self.assertEqual(style_manager.schemes[-1], getattr(Adw.ColorScheme, "DEFAULT", Adw.ColorScheme.PREFER_LIGHT))

        window = FakeWidget()
        title_label = FakeWidget()
        status_label = FakeWidget()
        stack = FakeStack()
        application._window = window
        application._title_label = title_label
        application._status_label = status_label
        application._stack = stack
        application._backend = object()
        application._web_view = object()
        application._set_status("error", "status.load_error")
        application._show_message("web-error", "message.load_error", "network unavailable")
        backend_before = application._backend
        web_view_before = application._web_view

        application._on_presentation_message(
            None,
            FakeJavascriptValue('{"language":"en","theme":"dark"}'),
        )
        self.assertEqual(application.language, "en")
        self.assertEqual(application.theme_mode, "dark")
        self.assertEqual(application.load_state, "error")
        self.assertEqual(application.load_status, native_text("en", "status.load_error"))
        self.assertEqual(window.title, native_text("en", "title"))
        self.assertEqual(title_label.text, native_text("en", "title"))
        self.assertEqual(status_label.text, native_text("en", "status.load_error"))
        self.assertEqual(
            stack.children["web-error"].get_text(),
            "The dashboard could not load.\n\nnetwork unavailable",
        )
        self.assertEqual(style_manager.schemes[-1], Adw.ColorScheme.FORCE_DARK)
        self.assertIs(application._backend, backend_before)
        self.assertIs(application._web_view, web_view_before)

        application._on_presentation_message(
            None,
            FakeJavascriptValue('{"language":"ru","theme":"dark","title":"unsafe"}'),
        )
        self.assertEqual(application.language, "en")
        self.assertEqual(application.theme_mode, "dark")

    @unittest.skipUnless(GTK_AVAILABLE, "GTK4, Libadwaita, and WebKitGTK 6.0 are not installed")
    def test_native_bridge_resyncs_document_without_a_second_preference_store(self) -> None:
        application = DashboardApplication(style_manager=FakeStyleManager())
        web_view = FakeWebView()
        application._web_view = web_view
        application._on_persisted_presentation_result(
            web_view,
            FakeJavascriptValue('{"language":"ru","theme":"dark"}'),
            "presentation-read",
        )
        self.assertEqual(application.language, "ru")
        self.assertEqual(application.theme_mode, "dark")
        self.assertEqual(len(web_view.calls), 1)
        self.assertEqual(web_view.calls[0][3], "aoa-dashboard://presentation-sync")
        application._on_presentation_message(
            None,
            FakeJavascriptValue('{"language":"ru","theme":"system"}'),
        )
        self.assertEqual(application.theme_mode, "dark")
        application._on_presentation_message(
            None,
            FakeJavascriptValue('{"language":"ru","theme":"dark"}'),
        )
        self.assertIsNone(application._document_sync_expected)

        self.assertIn("AoaDashboardPreferences", PRESENTATION_READ_SCRIPT)

    @unittest.skipUnless(GTK_AVAILABLE, "GTK4, Libadwaita, and WebKitGTK 6.0 are not installed")
    def test_direct_native_accessibility_observation_is_bounded(self) -> None:
        application = DashboardApplication(style_manager=FakeStyleManager())
        application._window = FakeWidget()
        application._title_label = FakeWidget()
        application._status_label = FakeWidget()
        application._stack = FakeWidget()
        application._web_view = FakeWidget()
        snapshot = application.accessibility_snapshot()
        self.assertEqual(snapshot["observation_contract"], "direct-gtk-widget-properties-v1")
        self.assertEqual(snapshot["window"]["role"], "none")
        self.assertTrue(snapshot["window"]["visible"])
        self.assertEqual(snapshot["document_sync"]["state"], "not_requested")

    @unittest.skipUnless(GTK_AVAILABLE, "GTK4, Libadwaita, and WebKitGTK 6.0 are not installed")
    def test_native_bridge_registers_the_expected_webkit_channel(self) -> None:
        application = DashboardApplication(style_manager=FakeStyleManager())
        manager = application._create_presentation_bridge()
        manager.unregister_script_message_handler(PRESENTATION_HANDLER_NAME)

    def test_dependency_unavailable_returns_explicit_exit_code(self) -> None:
        with patch.object(desktop_module, "GTK_AVAILABLE", False), patch.object(
            desktop_module, "GTK_IMPORT_ERROR", ImportError("test dependency missing")
        ):
            self.assertEqual(desktop_module.main([]), 2)

    @unittest.skipUnless(GTK_AVAILABLE, "GTK4, Libadwaita, and WebKitGTK 6.0 are not installed")
    def test_sigint_and_sigterm_are_routed_to_one_clean_quit(self) -> None:
        class FakeApplication:
            def __init__(self) -> None:
                self.quit_calls = 0

            def quit(self) -> None:
                self.quit_calls += 1

        application = FakeApplication()
        installed: dict[int, object] = {}
        restored: list[tuple[int, object]] = []

        def fake_signal(signum: int, handler: object) -> object:
            if callable(handler):
                installed[signum] = handler
                return "previous"
            restored.append((signum, handler))
            return handler

        with patch.object(desktop_module.signal, "signal", side_effect=fake_signal), patch.object(
            desktop_module.GLib,
            "idle_add",
            side_effect=lambda callback, priority=0: callback(),
        ):
            restore = install_shutdown_signal_handlers(application)
            installed[desktop_module.signal.SIGTERM](desktop_module.signal.SIGTERM, None)
            installed[desktop_module.signal.SIGINT](desktop_module.signal.SIGINT, None)
            restore()

        self.assertEqual(application.quit_calls, 1)
        self.assertEqual(
            restored,
            [(desktop_module.signal.SIGINT, "previous"), (desktop_module.signal.SIGTERM, "previous")],
        )

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
    def test_desktop_backend_origin_port_is_stable_by_default_and_overridable(self) -> None:
        application = DashboardApplication(style_manager=FakeStyleManager())
        self.assertEqual(application._backend_factory().port, DEFAULT_DESKTOP_PORT)
        ephemeral = DashboardApplication(style_manager=FakeStyleManager(), desktop_port=0)
        self.assertEqual(ephemeral._backend_factory().port, 0)

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
