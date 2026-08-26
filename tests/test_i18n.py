from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def dictionary_snapshot() -> dict[str, object]:
    script = """
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
process.stdout.write(JSON.stringify(context.AoaDashboardI18n.dictionaries));
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class LocalizationTests(unittest.TestCase):
    def test_dictionary_is_complete_and_locale_preference_survives_restart(self) -> None:
        dictionaries = dictionary_snapshot()
        self.assertEqual(set(dictionaries), {"en", "ru"})
        self.assertEqual(set(dictionaries["en"]), set(dictionaries["ru"]))
        self.assertTrue(all(value for language in dictionaries.values() for value in language.values()))

        script = """
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
const values = new Map();
const storage = {
  getItem(key) { return values.has(key) ? values.get(key) : null; },
  setItem(key, value) { values.set(key, String(value)); },
};
const initial = context.AoaDashboardI18n.createI18n({ locale: "ru-RU", storage });
const before = { language: initial.language, heading: initial.t("app.heading"), status: initial.status("wake requested") };
initial.setLanguage("en");
const after = context.AoaDashboardI18n.createI18n({ locale: "ru-RU", storage });
process.stdout.write(JSON.stringify({ before, stored: values.get("aoa-dashboard.language"), restart: after.language, russian: context.AoaDashboardI18n.createI18n({ locale: "ru-RU", storage: { getItem() { return null; } } }).language }));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(result.stdout)
        self.assertEqual(observed["before"]["language"], "ru")
        self.assertNotEqual(observed["before"]["heading"], "One truthful surface for a moving Goal")
        self.assertEqual(observed["before"]["status"], "Запрошено пробуждение")
        self.assertEqual(observed["stored"], "en")
        self.assertEqual(observed["restart"], "en")
        self.assertEqual(observed["russian"], "ru")

    def test_system_locale_default_and_unknown_locale_fallback(self) -> None:
        script = """
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
const noStoredPreference = { getItem() { return null; } };
const russian = context.AoaDashboardI18n.createI18n({ locale: "ru-MX", storage: noStoredPreference });
const english = context.AoaDashboardI18n.createI18n({ locale: "en-US", storage: noStoredPreference });
const fallback = context.AoaDashboardI18n.createI18n({ locale: "fr-FR", storage: noStoredPreference });
process.stdout.write(JSON.stringify({ russian: russian.language, english: english.language, fallback: fallback.language }));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(json.loads(result.stdout), {"russian": "ru", "english": "en", "fallback": "en"})

    def test_versioned_presentation_preferences_migrate_legacy_keys_and_bound_fields(self) -> None:
        script = """
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
const storage = new Map([
  ["aoa-dashboard.language", "ru-RU"],
  ["aoa-dashboard-theme-mode", "dark"],
]);
const store = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { storage.set(key, String(value)); },
};
const migrated = context.AoaDashboardI18n.readPresentationPreferences(store);
const written = context.AoaDashboardI18n.writePresentationPreferences(store, { language: "en", theme: "light", density: "compact", owner: "ignored" });
const restarted = context.AoaDashboardI18n.readPresentationPreferences(store);
storage.set("aoa-dashboard.preferences.v1", JSON.stringify({ version: 1, language: "fr", theme: "neon", density: "wide", owner: "ignored" }));
const invalid = context.AoaDashboardI18n.readPresentationPreferences(store);
process.stdout.write(JSON.stringify({ migrated, written, restarted, invalid, raw: JSON.parse(storage.get("aoa-dashboard.preferences.v1")) }));
"""
        result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True)
        observed = json.loads(result.stdout)
        self.assertEqual(observed["migrated"], {"version": 1, "language": "ru", "theme": "dark", "density": "comfortable"})
        self.assertEqual(observed["written"], {"version": 1, "language": "en", "theme": "light", "density": "compact"})
        self.assertEqual(observed["restarted"], observed["written"])
        self.assertEqual(observed["invalid"], {"version": 1, "language": None, "theme": "system", "density": "comfortable"})
        self.assertEqual(set(observed["raw"]), {"version", "language", "theme", "density", "owner"})
        self.assertEqual(observed["raw"]["owner"], "ignored")

    def test_all_declared_html_and_app_translation_keys_exist(self) -> None:
        keys = set(dictionary_snapshot()["en"])
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        declared = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', html))
        declared.update(re.findall(r'\bt\("([^"]+)"', javascript))
        missing = sorted(declared - keys)
        self.assertEqual(missing, [])

    def test_language_switch_rerenders_projection_without_reload(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-language="ru"', html)
        self.assertIn('data-language="en"', html)
        self.assertIn('data-i18n-aria-label="language.switchToRussian"', html)
        self.assertIn("localStorage", (ROOT / "web" / "i18n.js").read_text(encoding="utf-8"))
        self.assertIn("i18n.subscribe", javascript)
        self.assertIn("renderProjection(currentProjection)", javascript)
        self.assertIn("document.documentElement.lang = i18n.language", javascript)
        self.assertIn("AoaDashboardTheme.setLabels", javascript)

    def test_goal_workspace_selection_and_bounded_rendering_contract_is_wired(self) -> None:
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for marker in (
            "SelectionContext",
            "goal_ref",
            "focus_ref",
            "branch_path",
            "thread_ref",
            "observation_cursor_or_generation",
            "MAX_DIRECTIONS",
            "MAX_PEOPLE",
            "lastGoodProjection",
            'refreshState = lastGoodProjection ? "stale"',
            "contextThreadOpen = false",
            "formatHumanRecency",
            "diagnostics.developer",
        ):
            self.assertIn(marker, javascript)
        for marker in (
            'id="home-view"',
            'id="workspace-view"',
            'data-lens="trajectory"',
            'data-lens="attention"',
            'data-lens="participants"',
            'data-lens="evidence"',
            'data-lens="records"',
            'id="context-thread"',
            'id="operate-panel"',
            'aria-live="polite"',
        ):
            self.assertIn(marker, html)

    def test_native_presentation_bridge_publishes_startup_and_live_changes(self) -> None:
        script = """
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync("web/app.js", "utf8");
const posts = [];
const i18nListeners = [];
const themeListeners = [];
let language = "en";
let theme = "system";
let i18nInstance;
const node = {
  classList: { add() {}, remove() {} },
  addEventListener() {},
  textContent: "",
  className: "",
};
const context = {
  document: {
    documentElement: { lang: "" },
    querySelectorAll() { return []; },
    getElementById() { return node; },
  },
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  console,
  AoaDashboardI18n: {
    createI18n() {
      i18nInstance = {
        get language() { return language; },
        t(key) { return key; },
        status(value) { return value; },
        setLanguage(value) {
          language = value;
          i18nListeners.forEach((listener) => listener());
        },
        subscribe(listener) { i18nListeners.push(listener); },
      };
      return i18nInstance;
    },
  },
  AoaDashboardTheme: {
    getMode() { return theme; },
    setLabels() {},
    subscribe(listener) { themeListeners.push(listener); },
  },
  webkit: {
    messageHandlers: {
      aoaDashboardPresentation: { postMessage(value) { posts.push(value); } },
    },
  },
};
context.window = context;
vm.runInNewContext(source, context, { filename: "app.js" });
i18nInstance.setLanguage("ru");
theme = "dark";
themeListeners.forEach((listener) => listener("dark", "dark"));
i18nInstance.setLanguage("fr");
theme = "invalid";
themeListeners.forEach((listener) => listener("invalid", "invalid"));
process.stdout.write(JSON.stringify(posts));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            [
                {"language": "en", "theme": "system"},
                {"language": "ru", "theme": "system"},
                {"language": "ru", "theme": "dark"},
            ],
        )
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("aoaDashboardPresentation", javascript)
        self.assertIn("handler.postMessage({ language, theme })", javascript)
        self.assertIn("AoaDashboardTheme?.subscribe", javascript)

    def test_canonical_values_and_owner_text_are_not_translated_in_logic(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("<code>", html)
        self.assertIn("data-theme-host", html)
        self.assertIn('id="settings-panel"', html)
        self.assertIn('id="diagnostics-surface"', html)
        self.assertEqual(html.count('data-i18n="nav.goals"'), 1)
        self.assertNotIn('data-i18n="home.kicker"', html)
        self.assertNotIn("schema_version", html)
        self.assertNotIn("claim_limit", html)
        self.assertNotIn("sha256", html)
        self.assertNotIn("master-thread:", html)
        self.assertNotIn("Create aoa-dashboard first working vertical slice", html)
        self.assertIn("developer-details", javascript)
        self.assertIn("JSON.stringify(entry.value, null, 2)", javascript)
        self.assertIn('developer.addEventListener("toggle"', javascript)
        self.assertNotIn("boundedJson", javascript)


if __name__ == "__main__":
    unittest.main()
