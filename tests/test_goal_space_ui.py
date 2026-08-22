from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(source: str) -> object:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


class GoalSpaceUiStateTests(unittest.TestCase):
    def test_app_keeps_selection_evidence_and_operate_routes_exactly_bound(self) -> None:
        source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("|| envelopes[0]", source)
        self.assertNotIn("|| arrayOrEmpty(data.pressure_inbox?.items)[0]", source)
        self.assertIn("function envelopeMatchesSelection", source)
        self.assertIn("function routeReadiness", source)
        self.assertIn("selectionQuality === \"missing\"", source)
        self.assertIn("clearAlert()", source)
        self.assertIn("setProjectionBusy(true)", source)
        self.assertIn("renderDiagnosticRoutes", source)

    def test_selection_route_round_trip_is_complete_and_malformed_routes_fail_closed(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null, URLSearchParams };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
const selection = {
  goal_ref: "goal:test/one",
  lens: "evidence",
  focus_ref: "actor:7",
  branch_path: ["dag:D1", "actor:7"],
  thread_ref: "thread:test",
  expanded_branch_refs: ["detail:correlation:7"],
  page_by_list: { actors: 3, pressure: 1 },
  observation_cursor_or_generation: "2026-08-22T00:00:00Z",
};
const encoded = context.AoaDashboardUiState.encodeRoute(selection);
const decoded = context.AoaDashboardUiState.decodeRoute(encoded);
const cleared = context.AoaDashboardUiState.decodeRoute(context.AoaDashboardUiState.encodeRoute({}));
const malformed = context.AoaDashboardUiState.decodeRoute("#goal/%E0%A4%A/evidence?context=%7Bbad");
process.stdout.write(JSON.stringify({ encoded, decoded, cleared, malformed }));
'''
        )
        self.assertEqual(observed["decoded"]["status"], "valid")
        self.assertEqual(observed["decoded"]["selection"]["branch_path"], ["dag:D1", "actor:7"])
        self.assertEqual(observed["decoded"]["selection"]["expanded_branch_refs"], ["detail:correlation:7"])
        self.assertEqual(observed["decoded"]["selection"]["page_by_list"], {"actors": 3, "pressure": 1})
        self.assertEqual(observed["decoded"]["selection"]["observation_cursor_or_generation"], "2026-08-22T00:00:00Z")
        self.assertEqual(observed["cleared"]["status"], "home")
        self.assertEqual(observed["malformed"]["status"], "invalid")
        self.assertIsNone(observed["malformed"]["selection"]["goal_ref"])

    def test_catalog_optional_record_and_page_semantics_keep_missing_distinct_from_zero(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
const ui = context.AoaDashboardUiState;
const qualified = { items: [], source: { ref: "owner://catalog", owner: "goal-owner", currentness: "current_at_read" }, claim_limit: "derived catalog only" };
const page = ui.pageWindow([{ ref: "a" }, { ref: "b" }, { ref: "c" }, { ref: "d" }], 0, 2, "d");
process.stdout.write(JSON.stringify({
  arrayCatalog: ui.qualifiedCatalog([]),
  unqualifiedCatalog: ui.qualifiedCatalog({ items: [], claim_limit: "missing source" }),
  emptyCatalog: ui.qualifiedCatalog(qualified),
  boundCatalog: ui.qualifiedCatalog({ ...qualified, items: [{ goal_ref: "goal:1" }] }),
  missingRecord: ui.optionalRecord(null),
  zeroRecord: ui.optionalRecord({ count: 0, latest: [] }),
  unknownRecord: ui.optionalRecord({ latest: [] }),
  page,
}));
'''
        )
        self.assertEqual(observed["arrayCatalog"]["state"], "missing")
        self.assertEqual(observed["unqualifiedCatalog"]["state"], "missing")
        self.assertEqual(observed["emptyCatalog"]["state"], "admitted-empty")
        self.assertEqual(observed["boundCatalog"]["state"], "bound")
        self.assertEqual(observed["missingRecord"], {"state": "missing", "count": None, "latest": [], "evidence_refs": [], "claim_limit": None})
        self.assertEqual(observed["zeroRecord"]["state"], "bound")
        self.assertEqual(observed["zeroRecord"]["count"], 0)
        self.assertEqual(observed["unknownRecord"]["state"], "unknown")
        self.assertEqual(observed["unknownRecord"]["count"], None)
        self.assertEqual([item["ref"] for item in observed["page"]["items"]], ["c", "d"])
        self.assertEqual(observed["page"]["page"], 1)

    def test_versioned_preferences_share_invalid_future_fallback_and_plural_categories(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
const storageMap = new Map([["aoa-dashboard-theme-mode", "dark"], ["aoa-dashboard.language", "ru"]]);
const storage = { getItem(key) { return storageMap.has(key) ? storageMap.get(key) : null; }, setItem(key, value) { storageMap.set(key, String(value)); } };
const legacy = context.AoaDashboardPreferences.read(storage);
storageMap.set("aoa-dashboard.preferences.v1", JSON.stringify({ version: 2, theme: "dark", language: "en", density: "compact" }));
const future = context.AoaDashboardPreferences.read(storage);
storageMap.set("aoa-dashboard.preferences.v1", "{bad");
const malformed = context.AoaDashboardPreferences.read(storage);
const en = context.AoaDashboardI18n.createI18n({ locale: "en", storage: { getItem() { return null; }, setItem() {} } });
const ru = context.AoaDashboardI18n.createI18n({ locale: "ru", storage: { getItem() { return null; }, setItem() {} } });
process.stdout.write(JSON.stringify({ legacy, future, malformed, categories: {
  en: [0, 1, 2].map((count) => en.plural("plural.actor", count)),
  ru: [0, 1, 2, 5, 1.2].map((count) => ({ category: context.AoaDashboardI18n.pluralCategory("ru", count), text: ru.plural("plural.actor", count) })),
} }));
'''
        )
        self.assertEqual(observed["legacy"]["theme"], "dark")
        self.assertEqual(observed["future"]["theme"], "system")
        self.assertEqual(observed["malformed"]["theme"], "system")
        self.assertIn("No actors", observed["categories"]["en"][0])
        self.assertIn("1 actor", observed["categories"]["en"][1])
        self.assertIn("2 actors", observed["categories"]["en"][2])
        self.assertEqual([item["category"] for item in observed["categories"]["ru"]], ["zero", "one", "few", "many", "other"])

    def test_refresh_interaction_snapshot_restores_details_scroll_drafts_and_focus(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(id) {
  const listeners = {};
  return { id, dataset: {}, classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } }, children: [], firstChild: null, scrollTop: 0, scrollLeft: 0, open: false, value: "", type: "text", name: "", append(...items) { this.children.push(...items); }, removeChild() {}, setAttribute() {}, addEventListener(name, listener) { listeners[name] = listener; }, focus() { document.activeElement = this; }, querySelector() { return null; }, elements: [] };
}
const nodes = new Map();
for (const id of ["refresh-status", "center-surface", "workspace-view", "context-thread", "thread-toggle", "live-region", "alert", "route-status", "home-view", "workspace-view", "goal-selector", "catalog-state", "fallback-evidence", "annotation-form", "intent-form", "home-button", "workspace-goal-button"]) nodes.set(id, node(id));
nodes.get("center-surface").scrollTop = 41;
nodes.get("center-surface").scrollLeft = 3;
nodes.get("context-thread").classList = { add() {}, remove() {}, toggle() {} };
nodes.get("thread-toggle").setAttribute = function () {};
const detail = node("detail"); detail.dataset.detailKey = "correlation:one"; detail.open = true;
const focus = node("focus"); focus.dataset.focusKey = "return:one";
const draftControl = node("body"); draftControl.name = "body"; draftControl.value = "keep this draft";
nodes.get("annotation-form").elements = [draftControl];
const document = {
  title: "",
  activeElement: focus,
  documentElement: { lang: "", dataset: {} },
  getElementById(id) { return nodes.get(id) || null; },
  createElement(tag) { return node(tag); },
  querySelectorAll(selector) {
    if (selector === "details") return [detail];
    if (selector === "[data-focus-key]") return [focus];
    return [];
  },
  addEventListener() {},
};
const context = { document, globalThis: null, console, setInterval() {}, fetch() { return new Promise(() => {}); }, history: { replaceState() {} }, location: { hash: "" }, addEventListener() {}, AoaDashboardI18n: { createI18n() { return { language: "en", t(key) { return key; }, status(value) { return value; }, plural(key, count) { return `${key}:${count}`; }, subscribe() {} }; } }, AoaDashboardTheme: { getMode() { return "system"; }, setLabels() {}, subscribe() {} } };
context.globalThis = context; context.window = context; vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const snapshot = context.AoaDashboardApp.captureInteractionState();
detail.open = false; nodes.get("center-surface").scrollTop = 0; draftControl.value = "lost"; document.activeElement = null;
context.AoaDashboardApp.restoreInteractionState(snapshot);
process.stdout.write(JSON.stringify({ open: detail.open, scrollTop: nodes.get("center-surface").scrollTop, scrollLeft: nodes.get("center-surface").scrollLeft, draft: draftControl.value, focus: document.activeElement === focus }));
'''
        )
        self.assertEqual(observed, {"open": True, "scrollTop": 41, "scrollLeft": 3, "draft": "keep this draft", "focus": True})


if __name__ == "__main__":
    unittest.main()
