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
const storage = {
  value: null,
  getItem() { return this.value; },
  setItem(_key, value) { this.value = value; },
};
const initial = context.AoaDashboardI18n.createI18n({ locale: "ru-RU", storage });
const before = { language: initial.language, heading: initial.t("app.heading"), status: initial.status("wake requested") };
initial.setLanguage("en");
const after = context.AoaDashboardI18n.createI18n({ locale: "ru-RU", storage });
process.stdout.write(JSON.stringify({ before, stored: storage.value, restart: after.language, russian: context.AoaDashboardI18n.createI18n({ locale: "ru-RU", storage: { getItem() { return null; } } }).language }));
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
        self.assertEqual(observed["before"]["status"], "запрошено wake")
        self.assertEqual(observed["stored"], "en")
        self.assertEqual(observed["restart"], "en")
        self.assertEqual(observed["russian"], "ru")

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

    def test_canonical_values_and_owner_text_are_not_translated_in_logic(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("<code>deferred</code>", html)
        self.assertIn("<code>effect: none</code>", html)
        self.assertIn("canonicalValue.replaceAll", javascript)
        self.assertIn("text(\"p\", item.observation)", javascript)
        self.assertIn("text(\"li\", item)", javascript)
        self.assertIn("JSON.stringify(sourceSummary, null, 2)", javascript)


if __name__ == "__main__":
    unittest.main()
