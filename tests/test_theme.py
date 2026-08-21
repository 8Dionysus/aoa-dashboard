from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
THEME_JS = ROOT / "web" / "theme.js"
STYLES_CSS = ROOT / "web" / "styles.css"


class ThemeTests(unittest.TestCase):
    def test_theme_layer_has_semantic_dark_surface_coverage(self) -> None:
        css = STYLES_CSS.read_text(encoding="utf-8")
        self.assertIn(':root[data-theme="dark"]', css)
        self.assertIn("color-scheme: dark", css)
        for selector in (
            ".panel",
            ".goal-card",
            ".pressure-card pre",
            ".source-card pre",
            "input, textarea",
            "button",
            ".alert",
            ".badge",
            "*::-webkit-scrollbar-thumb",
        ):
            self.assertIn(selector, css)
        for variable in ("--surface-subtle", "--surface-code", "--surface-alert", "--focus-ring", "--status-negative-bg"):
            self.assertIn(variable, css)

    def test_theme_modes_persist_and_follow_system_changes(self) -> None:
        harness = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const listeners = [];
const storage = new Map();
const media = { matches: true, addEventListener: (_name, listener) => listeners.push(listener) };

function makeNode(tagName) {
  const nodeListeners = {};
  return {
    tagName,
    className: "",
    dataset: {},
    attributes: {},
    children: [],
    value: "",
    append: function (...children) { this.children.push(...children); },
    setAttribute: function (name, value) { this.attributes[name] = String(value); },
    addEventListener: function (name, listener) {
      (nodeListeners[name] || (nodeListeners[name] = [])).push(listener);
    },
    dispatch: function (name) {
      (nodeListeners[name] || []).forEach((listener) => listener({ target: this, currentTarget: this }));
    },
    querySelector: function (selector) {
      if (selector === "[data-theme-control]") {
        return this.children.find((child) => child.dataset && child.dataset.themeControl) || null;
      }
      return null;
    }
  };
}

const root = makeNode("html");
const mastMeta = makeNode("div");
const document = {
  readyState: "complete",
  documentElement: root,
  querySelector: (selector) => selector === ".mast-meta" ? mastMeta : null,
  createElement: makeNode,
  addEventListener: () => {}
};
const context = {
  document,
  localStorage: {
    getItem: (key) => storage.has(key) ? storage.get(key) : null,
    setItem: (key, value) => storage.set(key, String(value))
  },
  matchMedia: () => media,
  console
};
context.window = context;
vm.runInNewContext(source, context, { filename: "theme.js" });

const select = mastMeta.children[0].children[1];
if (root.dataset.themeMode !== "system" || root.dataset.theme !== "dark") throw new Error("system default did not resolve");
if (select.children.map((option) => option.value).join(",") !== "system,light,dark") throw new Error("theme options missing");

select.value = "dark";
select.dispatch("change");
if (root.dataset.themeMode !== "dark" || root.dataset.theme !== "dark") throw new Error("dark selection failed");
if (storage.get("aoa-dashboard-theme-mode") !== "dark") throw new Error("explicit choice was not persisted");

vm.runInNewContext(source, context, { filename: "theme-reload.js" });
if (context.AoaDashboardTheme.getMode() !== "dark" || root.dataset.theme !== "dark") throw new Error("persisted choice was not restored");

media.matches = false;
listeners.forEach((listener) => listener({ matches: false }));
if (root.dataset.theme !== "dark") throw new Error("explicit dark choice followed system unexpectedly");

select.value = "system";
select.dispatch("change");
if (root.dataset.themeMode !== "system" || root.dataset.theme !== "light") throw new Error("system choice did not resolve");
media.matches = true;
listeners.forEach((listener) => listener({ matches: true }));
if (root.dataset.theme !== "dark") throw new Error("system change was not observed");

if (context.AoaDashboardTheme.setMode("invalid") !== "system") throw new Error("invalid mode was not normalized");
process.stdout.write(JSON.stringify({ mode: context.AoaDashboardTheme.getMode(), resolved: root.dataset.theme }));
"""
        completed = subprocess.run(
            ["node", "-e", harness, str(THEME_JS)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"mode": "system", "resolved": "dark"})


if __name__ == "__main__":
    unittest.main()
