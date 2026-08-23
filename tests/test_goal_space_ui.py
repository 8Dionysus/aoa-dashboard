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
        self.assertIn("function contextForSelection", source)
        self.assertIn("function contextForRef", source)
        self.assertIn("function directionItems", source)
        self.assertIn("function primaryDirectionItems", source)
        self.assertIn("function goalDirectionItem", source)
        self.assertIn("function trajectoryDirectionItems", source)
        self.assertIn("function topologyDirectionItems", source)
        self.assertIn("function renderTopologyBranches", source)
        self.assertIn("expanded_branch_refs", source)
        self.assertIn("function participantItems", source)
        self.assertIn("function participantContextItems", source)
        self.assertIn("owner_goal_context", source)
        self.assertIn("owner-context-details", source)
        self.assertIn("function routeReadiness", source)
        self.assertIn("selectionQuality === \"missing\"", source)
        self.assertIn("clearAlert()", source)
        self.assertIn("setProjectionBusy(true)", source)
        self.assertIn("renderDiagnosticRoutes", source)
        self.assertIn("function formatHumanRecency", source)
        self.assertIn("contextThreadOpen = false", source)
        self.assertNotIn("GOAL_LABELS", source)
        self.assertNotRegex(source, r"aoa-dashboard-goal-01a00722-20260815")
        self.assertNotIn('i18n.language === "ru"', source)

    def test_narrow_settings_keeps_summary_targetable_above_disclosure(self) -> None:
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".settings-panel > summary { position: relative; z-index: 3;", styles)
        self.assertIn(".settings-content { position: absolute; z-index: 2;", styles)
        self.assertIn(".settings-content { top: calc(100% + 8px); right: 0; }", styles)
        self.assertIn(".lens-hint { display: none;", styles)
        self.assertIn(".lens-button.active .lens-hint { display: block; }", styles)
        self.assertNotIn(".settings-content { position: fixed", styles)

    def test_operate_route_requires_admitted_currentness_and_exact_context(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = {
  document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; }, createElement() { return {}; } },
  globalThis: null,
  console,
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  location: { hash: "" },
  history: { replaceState() {} },
  AoaDashboardI18n: { createI18n() { return { language: "en", t(key) { return key; }, status(value) { return value; }, plural(key, count) { return `${key}:${count}`; }, subscribe() {} }; } },
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const selection = { goal_ref: "goal:test", thread_ref: "thread:test", focus_ref: "pressure:p2" };
const base = {
  goal_id: "goal:test",
  master_thread_id: "thread:test",
  pressure_ref: { id: "p2" },
  next_route: { owner: "aoa-agents", route: "review", effect: "none", authority: "master_decision" },
  stop_line: "stop",
  wake_condition: "wake",
  evidence: [{ ref: "evidence:p2" }],
};
const check = (currentness) => context.AoaDashboardApp.routeReadiness({ ...base, pressure_ref: { ...base.pressure_ref, currentness } }, selection);
const missingThread = { ...base };
delete missingThread.master_thread_id;
const conflictingThread = context.AoaDashboardApp.routeReadiness({ ...base, pressure_ref: { id: "p2", currentness: "current" } }, { ...selection, thread_ref: "thread:other" });
const wrongFocus = context.AoaDashboardApp.routeReadiness({ ...base, pressure_ref: { id: "p3", currentness: "current" } }, selection);
process.stdout.write(JSON.stringify({
  matchingThread: check("current").ready,
  missingThread: context.AoaDashboardApp.routeReadiness(missingThread, selection).ready,
  conflictingThread: conflictingThread.ready,
  current: check("current").ready,
  currentAtRead: check("current_at_read").ready,
  unknown: check("unknown").ready,
  stale: check("stale").ready,
  invented: check("invented").ready,
  absent: check(null).ready,
  wrongFocus: wrongFocus.ready,
}));
'''
        )
        self.assertEqual(
            observed,
            {"matchingThread": True, "missingThread": False, "conflictingThread": False, "current": True, "currentAtRead": True, "unknown": False, "stale": False, "invented": False, "absent": False, "wrongFocus": False},
        )

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
const fabricated = { items: [{ goal_ref: "goal:1" }], source: { ref: "fixture://not-owner", owner: "fabricated-owner", currentness: "invented" }, claim_limit: "fabricated claim" };
const admitted = {
  schema_version: "aoa_dashboard_goal_catalog_projection_v1",
  state: "stale",
  currentness: "stale",
  source: { owner: "aoa-session-memory", ref: "aoa-session-memory:goal-lifecycles", owner_schema_version: "aoa_session_memory_goal_catalog_v1", currentness: "stale" },
  items: [{ ref: "goal:1", title: "A human Goal", title_locale: "en", title_state: "available", lifecycle_state: "active", group: "active", first_observed_at: null, last_observed_at: "2026-08-22T00:00:00Z", ambiguity: false }],
  counts_by_group: { active: 1 },
  claim_limit: "bounded owner projection",
};
const duplicate = { ...admitted, items: [admitted.items[0], { ...admitted.items[0] }] };
const page = ui.pageWindow([{ ref: "a" }, { ref: "b" }, { ref: "c" }, { ref: "d" }], 0, 2, "d");
process.stdout.write(JSON.stringify({
  arrayCatalog: ui.qualifiedCatalog([]),
  emptyMissingCatalog: ui.qualifiedCatalog({ schema_version: "aoa_dashboard_goal_catalog_projection_v1", state: "missing", currentness: "missing", source: null, items: [], claim_limit: "Scope: owner-published Goal navigation." }),
  emptyInvalidCatalog: ui.qualifiedCatalog({ schema_version: "aoa_dashboard_goal_catalog_projection_v1", state: "invalid", currentness: "invalid", source: null, items: [], claim_limit: "Scope: owner-published Goal navigation." }),
  unqualifiedCatalog: ui.qualifiedCatalog({ items: [], claim_limit: "missing source" }),
  fabricatedCatalog: ui.qualifiedCatalog(fabricated),
  admittedCatalog: ui.qualifiedCatalog(admitted),
  duplicateCatalog: ui.qualifiedCatalog(duplicate),
  missingRecord: ui.optionalRecord(null),
  zeroRecord: ui.optionalRecord({ count: 0, latest: [] }),
  unknownRecord: ui.optionalRecord({ latest: [] }),
  page,
}));
'''
        )
        self.assertEqual(observed["arrayCatalog"]["state"], "missing")
        self.assertEqual(observed["emptyMissingCatalog"]["state"], "missing")
        self.assertEqual(observed["emptyInvalidCatalog"]["state"], "invalid")
        self.assertEqual(observed["unqualifiedCatalog"]["state"], "invalid")
        self.assertEqual(observed["fabricatedCatalog"]["state"], "invalid")
        self.assertEqual(observed["fabricatedCatalog"]["reason"], "publisher_unqualified")
        self.assertEqual(observed["admittedCatalog"]["state"], "stale")
        self.assertEqual(observed["admittedCatalog"]["items"][0]["title"], "A human Goal")
        self.assertEqual(observed["admittedCatalog"]["items"][0]["group"], "active")
        self.assertEqual(observed["duplicateCatalog"]["state"], "invalid")
        self.assertEqual(observed["duplicateCatalog"]["reason"], "item_invalid")
        self.assertEqual(observed["missingRecord"], {"state": "missing", "count": None, "latest": [], "evidence_refs": [], "claim_limit": None})
        self.assertEqual(observed["zeroRecord"]["state"], "bound")
        self.assertEqual(observed["zeroRecord"]["count"], 0)
        self.assertEqual(observed["unknownRecord"]["state"], "unknown")
        self.assertEqual(observed["unknownRecord"]["count"], None)
        self.assertEqual([item["ref"] for item in observed["page"]["items"]], ["c", "d"])
        self.assertEqual(observed["page"]["page"], 1)

    def test_federated_catalog_keeps_owner_inputs_and_selected_goal_page_stable(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = { globalThis: null };
context.globalThis = context;
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
const ui = context.AoaDashboardUiState;
const items = [
  { ref: "history:one", title: "Historical Goal", title_state: "available", lifecycle_state: "complete", group: "completed", first_observed_at: null, last_observed_at: null, ambiguity: false },
  { ref: "live:two", title: "Live Goal", title_state: "available", lifecycle_state: "active", group: "active", first_observed_at: null, last_observed_at: null, ambiguity: false },
  { ref: "live:three", title: "Attention Goal", title_state: "available", lifecycle_state: "blocked", group: "attention", first_observed_at: null, last_observed_at: null, ambiguity: false },
];
const catalog = {
  schema_version: "aoa_dashboard_goal_catalog_projection_v1",
  state: "current",
  currentness: "current",
  source: {
    owner: "aoa-dashboard",
    ref: "aoa-dashboard:goal-catalog-federation",
    kind: "derived_federation",
    currentness: "current",
    inputs: [
      { owner: "aoa-session-memory", ref: "aoa-session-memory:goal-lifecycles", currentness: "stale" },
      { owner: "codex-app-server", ref: "codex-app-server:goal-catalog", currentness: "current_at_read" },
    ],
  },
  items,
  counts_by_group: { completed: 1, active: 1, attention: 1 },
  pagination: { mode: "federated", cursor: null, next_cursor: null, complete: true, sources: {} },
  claim_limit: "federated owner navigation",
};
const admitted = ui.qualifiedCatalog(catalog);
const page = ui.pageWindow(admitted.items, 0, 2, "live:three");
process.stdout.write(JSON.stringify({ state: admitted.state, refs: admitted.items.map((item) => item.ref), selectedPage: page.items.map((item) => item.ref), sourceCount: admitted.sources.length }));
'''
        )
        self.assertEqual(observed["state"], "current")
        self.assertEqual(observed["refs"], ["history:one", "live:two", "live:three"])
        self.assertEqual(observed["selectedPage"], ["live:three"])
        self.assertEqual(observed["sourceCount"], 2)

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
process.stdout.write(JSON.stringify({ legacy, future, malformed, unknownCategories: [null, undefined, "not-a-number", "2"].map((count) => context.AoaDashboardI18n.pluralCategory("en", count)), categories: {
  en: [0, 1, 2].map((count) => en.plural("plural.person", count)),
  ru: [0, 1, 2, 5, 1.2].map((count) => ({ category: context.AoaDashboardI18n.pluralCategory("ru", count), text: ru.plural("plural.person", count) })),
} }));
'''
        )
        self.assertEqual(observed["legacy"]["theme"], "dark")
        self.assertEqual(observed["future"]["theme"], "system")
        self.assertEqual(observed["malformed"]["theme"], "system")
        self.assertEqual(observed["unknownCategories"], ["unknown", "unknown", "unknown", "unknown"])
        self.assertIn("No people", observed["categories"]["en"][0])
        self.assertIn("1 person", observed["categories"]["en"][1])
        self.assertIn("2 people", observed["categories"]["en"][2])
        self.assertEqual([item["category"] for item in observed["categories"]["ru"]], ["zero", "one", "few", "many", "other"])

    def test_local_recency_and_goal_title_are_human_and_minute_bounded(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = {
  globalThis: null,
  document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; } },
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: { language: "en-US" },
  location: { hash: "" },
  history: { replaceState() {} },
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  addEventListener() {},
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const app = context.AoaDashboardApp;
const goal = { goal: { goal_id: "goal:future-one", title: "Canonical future goal" }, presentation: { goal: { title: { en: "Create the first Goal Space slice", ru: "Собрать первый рабочий срез пространства целей" } } } };
const ownerGoal = { goal: { goal_id: "goal:current", title: "Преобразовать aoa-dashboard в Goal Space", title_source: "codex_app_server_thread_goal" }, presentation: { goal: { title: { en: "Stale configured title", ru: "Устаревший заголовок" } } } };
const recent = app.formatHumanRecency("2026-08-22T16:17:00Z", "2026-08-22T16:29:00Z");
const old = app.formatHumanRecency("2026-08-01T09:10:45.123Z", "2026-08-22T16:29:00Z");
const absolute = app.formatAbsoluteMinute("2026-08-01T09:10:45.123Z");
const enTitle = app.goalTitle(goal);
const ownerTitle = app.goalTitle(ownerGoal);
const longGoal = { goal: { goal_id: "goal:long", title: "Create a calm modern Goal-first workspace for the active and historical work view" } };
const compactLong = app.compactGoalTitle(longGoal);
const explicitCompact = app.compactGoalTitle({ ...longGoal, presentation: { goal: { short_title: { en: "Goal workspace" } } } });
const ownerLifecycle = app.lifecycleForData({ goal: { state: "active", title_source: "codex_app_server_thread_goal" }, lifecycle: [{ step: "planned", state: "planned" }] });
const legacyLifecycle = app.lifecycleForData({ goal: { state: "active" }, lifecycle: [{ step: "planned", state: "planned" }] });
context.AoaDashboardI18n.createI18n;
process.stdout.write(JSON.stringify({ recent, old, absolute, enTitle, ownerTitle, compactLong, explicitCompact, ownerLifecycle, legacyLifecycle, hasSeconds: /:\d{2}(?:\.|Z|$)/.test(old), hasAbsoluteSeconds: /:\d{2}:\d{2}/.test(absolute), hasIso: /T|Z/.test(old) }));
'''
        )
        self.assertIn("12", observed["recent"])
        self.assertNotRegex(observed["recent"], r"T|Z|\.\d")
        self.assertFalse(observed["hasSeconds"])
        self.assertFalse(observed["hasAbsoluteSeconds"])
        self.assertFalse(observed["hasIso"])
        self.assertEqual(observed["enTitle"], "Create the first Goal Space slice")
        self.assertEqual(observed["ownerTitle"], "Stale configured title")
        self.assertEqual(observed["compactLong"], "Goal title unavailable")
        self.assertEqual(observed["explicitCompact"], "Goal workspace")
        self.assertEqual(observed["ownerLifecycle"], "active")
        self.assertEqual(observed["legacyLifecycle"], "planned")

    def test_generic_localized_presentation_handles_future_goals_and_hides_technical_cards(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function load(language) {
  const storage = new Map([["aoa-dashboard.language", language]]);
  const context = {
    globalThis: null,
    document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; } },
    localStorage: { getItem(key) { return storage.get(key) || null; }, setItem(key, value) { storage.set(key, String(value)); } },
    navigator: { language: "en-US" },
    location: { hash: "" },
    history: { replaceState() {} },
    fetch() { return new Promise(() => {}); },
    setInterval() {},
    addEventListener() {},
  };
  context.globalThis = context;
  context.window = context;
  vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
  return context.AoaDashboardApp;
}
const presentation = {
  goal: { title: { en: "First future goal", ru: "Первая будущая цель" } },
  directions: { D4: { title: { en: "Observation history", ru: "История наблюдений" }, relationship: { en: "Keeps changes together", ru: "Собирает изменения вместе" }, focus: { en: "Keep history clear", ru: "Сохранять историю ясной" }, next: { en: "Review the next change", ru: "Проверить следующее изменение" } } },
  pressures: { "pressure:test": { title: { en: "Review the update", ru: "Проверить обновление" }, relationship: { en: "Needs review", ru: "Нужна проверка" }, focus: { en: "A short pressure summary", ru: "Короткое резюме запроса" }, next: { en: "Ask the owner", ru: "Спросить владельца" } } },
  participants: { roles: { external_codex_incarnation: { en: "Working agent", ru: "Рабочий агент" } } },
};
function projection(goalId, title, goalPresentation) {
  return {
    goal: { goal_id: goalId, title },
    presentation: { ...presentation, goal: { title: goalPresentation } },
    dag: [{ id: "D4", title: "D4 versioned cursor/checkpoint correlation projection is degraded; source dashboard:correlation_read_model.", pressure: "runtime event drift", observation: "versioned cursor/checkpoint correlation projection is degraded; source dashboard:correlation_read_model.", next: "filter exact pressure-cursor-ui handoff" }],
    pressure_inbox: { items: [{ pressure_ref: { id: "pressure:test" }, affected_goal_criterion: "D4 requires a deterministic rebuild", consequence_of_omission: "source dashboard:correlation_read_model", next_route: { owner: "master-thread", route: "filter exact pressure-cursor-ui handoff", critical: true }, outcome: { state: "deferred" } }] },
    actor_activity: { actors: [{ actor_key: "actor:one", identity: { label: "one-shot return holder description that belongs in diagnostics", role_id: "external_codex_incarnation", model_id: "gpt-5" }, task: { task_id: "task:private", state: "returned" }, responsibility: { holder: "actor:one", responsibility_state: "not_independent" } }] },
    sources: [{ id: "aoa-session-memory", owner: "aoa-session-memory", state: "missing", observation: "The historical source dashboard path is unavailable.", evidence_refs: [] }],
  };
}
const en = load("en");
const ru = load("ru");
const one = projection("goal:one", "Canonical one", { en: "First future goal", ru: "Первая будущая цель" });
const two = projection("goal:two", "Canonical two", { en: "Second future goal", ru: "Вторая будущая цель" });
const topology = {
  ...one,
  goal_topology: {
    state: "bound",
    root_ids: ["GS18"],
    evidence_refs: [{ label: "Current Goal topology", ref: "owner:topology" }],
    nodes: [
      { id: "GS17", title: "Current Goal binding", state: "completed", source_state: "completed", depends_on: [], owner: "master-thread", scope: "Keep the Goal identity current" },
      { id: "GS18", title: "Full aoa-dashboard Goal readiness", state: "in_progress", source_state: "in_progress", depends_on: ["GS17"], owner: "master-thread", scope: "Hold source, runtime, visual and human evidence together", user_facing: true },
    ],
  },
    dag: [{ id: "GS18", source_kind: "master_goal_topology", title: "Full aoa-dashboard Goal readiness", state: "active", depends_on: ["GS17"], observation: "Hold source, runtime, visual and human evidence together", user_facing: true }],
};
const enDirection = en.directionItems(one).find((item) => item.ref === "dag:D4");
const topologyDirection = en.directionItems(topology)[0];
const topologyBranches = en.topologyDirectionItems(topology);
const ruPressure = ru.directionItems(one).find((item) => item.ref === "pressure:pressure:test");
const person = en.participantItems(one)[0] || null;
const source = en.sourceItems(one)[0];
process.stdout.write(JSON.stringify({
  goals: [en.goalTitle(one), en.goalTitle(two), ru.goalTitle(one)],
  direction: { title: enDirection.title, relationship: enDirection.relationship, focus: enDirection.focus, next: enDirection.next, raw: enDirection.raw.observation },
  topology: { title: topologyDirection.title, focus: topologyDirection.focus, relationship: topologyDirection.relationship, next: topologyDirection.next, nextFocus: en.nextFocus(topology).title, attentionFocus: en.attentionFocus(topology).title, branches: topologyBranches.map((item) => ({ ref: item.ref, title: item.title, state: item.state, owner: item.owner, focus: item.focus })) },
  trajectoryRefs: en.trajectoryDirectionItems(topology).map((item) => item.ref),
  knownTopologyRef: en.knownFocusRefs(topology).has("dag:GS17"),
  selectedTopologyTitle: en.contextForRef(topology, "dag:GS17").title,
  pressure: { title: ruPressure.title, focus: ruPressure.focus, next: ruPressure.next, raw: ruPressure.raw.next_route.route },
  person: person && { title: person.title, role: person.role, task: person.task },
  source: { title: source.title, focus: source.focus },
}));
'''
        )
        self.assertEqual(observed["goals"], ["First future goal", "Second future goal", "Первая будущая цель"])
        self.assertEqual(observed["direction"]["title"], "Observation history")
        self.assertNotIn("correlation_read_model", json.dumps({key: value for key, value in observed["direction"].items() if key != "raw"}))
        self.assertIn("correlation_read_model", observed["direction"]["raw"])
        self.assertEqual(observed["topology"]["title"], "Full aoa-dashboard Goal readiness")
        self.assertEqual(observed["topology"]["focus"], "Hold source, runtime, visual and human evidence together")
        self.assertEqual(observed["topology"]["relationship"], "1 direction")
        self.assertEqual(observed["topology"]["next"], "")
        self.assertEqual(observed["topology"]["nextFocus"], "Full aoa-dashboard Goal readiness")
        self.assertEqual(observed["topology"]["attentionFocus"], "Review the update")
        self.assertEqual(observed["topology"]["branches"][0], {"ref": "dag:GS17", "title": "Current Goal binding", "state": "unknown", "owner": "Goal master", "focus": "Keep the Goal identity current"})
        self.assertEqual(observed["topology"]["branches"][1]["state"], "unknown")
        self.assertEqual(observed["trajectoryRefs"], ["dag:GS18"])
        self.assertTrue(observed["knownTopologyRef"])
        self.assertEqual(observed["selectedTopologyTitle"], "Current Goal binding")
        self.assertEqual(observed["pressure"]["title"], "Проверить обновление")
        self.assertNotIn("pressure-cursor-ui", json.dumps({key: value for key, value in observed["pressure"].items() if key != "raw"}))
        self.assertIn("pressure-cursor-ui", observed["pressure"]["raw"])
        self.assertIsNone(observed["person"])
        self.assertNotIn("historical source", observed["source"]["focus"])

    def test_goal_bound_primary_trajectory_uses_admitted_mapping_and_hides_internal_topology(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  return { tagName: tag, children: [], className: "", dataset: {}, textContent: "", append(...items) { this.children.push(...items); }, setAttribute() {}, addEventListener() {} };
}
const context = {
  globalThis: null,
  document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; }, createElement: node },
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: { language: "en-US" },
  location: { hash: "" },
  history: { replaceState() {} },
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  addEventListener() {},
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const data = {
  goal: { goal_id: "goal:bound", title: "A human Goal", title_source: "codex_app_server_thread_goal", state: "paused", source_refs: [{ ref: "owner:goal" }] },
  owner_goal: { state: "bound", source: { ref: "owner:goal" } },
  current_holder: {},
  lifecycle: [{ step: "paused", state: "paused" }],
  presentation: { trajectory: { primary: {
    title: { en: "Move this Goal forward", ru: "Продвигать эту цель" },
    relationship: { en: "the selected Goal", ru: "выбранной целью" },
    focus: { en: "Follow the next step published by its owner.", ru: "Следовать следующему шагу, опубликованному владельцем." },
    next: { en: "Choose the next step to inspect.", ru: "Выбрать следующий шаг для просмотра." },
  } } },
  dag: [{ id: "GS18", source_kind: "master_goal_topology", title: "Full Goal completion readiness", state: "active", scope: "Hold source, runtime, visual and human evidence together", user_facing: false }],
  goal_topology: { state: "bound", root_ids: ["GS18"], nodes: [{ id: "GS18", title: "Full Goal completion readiness", scope: "Hold source, runtime, visual and human evidence together", user_facing: false }], evidence_refs: [{ ref: "owner:topology" }] },
  pressure_inbox: { items: [] },
};
const target = node("section");
const primary = context.AoaDashboardApp.primaryDirectionItems(data);
const selected = context.AoaDashboardApp.contextForRef(data, "goal-direction");
const known = context.AoaDashboardApp.knownFocusRefs(data);
context.AoaDashboardApp.renderTrajectoryLens(data, target);
process.stdout.write(JSON.stringify({ primary: primary.map((item) => ({ ref: item.ref, title: item.title, focus: item.focus })), selected: selected && ({ ref: selected.ref, title: selected.title, focus: selected.focus }), known: known.has("goal-direction"), rendered: JSON.stringify(target) }));
'''
        )
        self.assertEqual(observed["primary"][0]["ref"], "goal-direction")
        self.assertEqual(observed["primary"][0]["title"], "Move this Goal forward")
        self.assertEqual(observed["selected"]["ref"], "goal-direction")
        self.assertEqual(observed["selected"]["title"], "Move this Goal forward")
        self.assertTrue(observed["known"])
        self.assertIn("Follow the next step published by its owner.", observed["rendered"])
        self.assertNotIn("Full Goal completion readiness", observed["rendered"])
        self.assertNotIn("Hold source, runtime, visual and human evidence together", observed["rendered"])
        self.assertNotIn("GS18", observed["rendered"])

    def test_default_human_projection_hides_machine_identity_and_source_keys(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = {
  globalThis: null,
  document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; } },
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: { language: "en-US" },
  location: { hash: "" },
  history: { replaceState() {} },
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  addEventListener() {},
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const projection = {
  actor_activity: { actors: [{ actor_key: "actor:abc", identity: { label: "actor:abc", role_id: "external_codex_incarnation", model_id: "gpt-5.6-luna:max" }, task: { task_id: "task:private", summary: "Review the Goal catalog integration" }, responsibility: { holder: "independent Luna Max D1/D2 owner contracts reviewer", responsibility_state: "not_independent" } }] },
  sources: [{ id: "aoa-session-memory", owner: ".aoa/session-memory", state: "missing", evidence_refs: [] }],
};
const person = context.AoaDashboardApp.participantItems(projection)[0] || null;
const source = context.AoaDashboardApp.sourceItems(projection)[0];
process.stdout.write(JSON.stringify({ person: person && { title: person.title, role: person.role, model: person.model, task: person.task, owner: person.owner }, source: { title: source.title, owner: source.owner } }));
'''
        )
        self.assertIsNone(observed["person"])
        self.assertEqual(observed["source"]["title"], "Session history")
        self.assertEqual(observed["source"]["owner"], "Session history")
        self.assertNotIn("aoa-session-memory", json.dumps(observed["source"]))

    def test_owner_participant_context_stays_human_in_en_ru_and_exact_details_are_deferred(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  const listeners = {};
  return { tagName: tag, children: [], dataset: {}, className: "", open: false, textContent: "", append(...items) { this.children.push(...items); }, addEventListener(name, listener) { listeners[name] = listener; }, setAttribute() {}, trigger(name) { if (listeners[name]) listeners[name](); } };
}
function load(language) {
  const context = { globalThis: null, document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; }, createElement: node }, localStorage: { getItem() { return language; }, setItem() {} }, location: { hash: "" }, history: { replaceState() {} }, fetch() { return new Promise(() => {}); }, setInterval() {}, addEventListener() {}, navigator: { language: language === "ru" ? "ru-RU" : "en-US" } };
  context.globalThis = context; context.window = context;
  vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
  return context;
}
const data = {
  goal: { goal_id: "goal:synthetic", title: "Bounded Goal" },
  participant_context: {
    state: "deferred",
    participants: [{
      ref: "actor:return:synthetic",
      lifecycle_state: "returned",
      quality: "deferred",
      identity: { state: "present", role_id: "external_codex_incarnation", display_name: null, display_name_state: "missing", candidate_label: "actor:secret" },
      task_context: { state: "present", summary: "Review the Goal context", goal_thread: { state: "present", thread_id: "thread:owner", owner: "codex-app-server" } },
      model_realization: { state: "unknown", candidate_model_id: "gpt-5.6-luna:max", runtime_subject: null },
      runtime_evidence: { state: "deferred" },
      evidence_refs: [{ label: "owner thread", ref: "codex-app-server:thread/read:thread:owner" }],
    }],
  },
  owner_goal_context: {
    state: "deferred",
    goal_ref: { thread_id: "thread:owner", owner: "codex-app-server" },
    thread: { state: "bound", thread_id: "thread:owner", evidence_refs: [{ ref: "thread:owner" }] },
    relations: {
      spawn_parent: { state: "bound", complete_for_query: true, items: [{ thread_id: "thread:child" }] },
      history_fork: { state: "deferred", complete_for_query: false, items: [] },
    },
    evidence_refs: [{ label: "owner thread", ref: "codex-app-server:thread/read:thread:owner" }],
  },
};
const enContext = load("en");
const ruContext = load("ru");
const enPerson = enContext.AoaDashboardApp.participantItems(data)[0] || null;
const ruPerson = ruContext.AoaDashboardApp.participantItems(data)[0] || null;
const human = (person) => person && ({ title: person.title, role: person.role, model: person.model, task: person.task, relationship: person.relationship, focus: person.focus, owner: person.owner });
const target = node("section");
enContext.AoaDashboardApp.renderDiagnosticRoutes(data, target);
const body = target.children[0].children[1];
const ownerEntry = body.children.find((item) => item.children?.[0]?.textContent === "Goal and branch context");
const developer = ownerEntry.children[1];
const before = JSON.stringify(ownerEntry).includes("thread:owner");
developer.open = true;
developer.trigger("toggle");
const after = JSON.stringify(developer).includes("thread:owner") && developer.children.some((item) => item.tagName === "pre");
process.stdout.write(JSON.stringify({ en: human(enPerson), ru: human(ruPerson), before, after }));
'''
        )
        self.assertIsNone(observed["en"])
        self.assertIsNone(observed["ru"])
        self.assertFalse(observed["before"])
        self.assertTrue(observed["after"])

    def test_explicit_owner_labels_replace_numbered_participants_without_inference(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = {
  globalThis: null,
  document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; } },
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: { language: "en-US" },
  location: { hash: "" },
  history: { replaceState() {} },
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  addEventListener() {},
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const actor = context.AoaDashboardApp.participantItems({ actor_activity: { actors: [{ actor_key: "actor:one", identity: { label: "actor:one", display_name: "Luna", role_id: "external_codex_incarnation" }, task: {}, responsibility: {} }] } })[0];
const participant = context.AoaDashboardApp.participantItems({ participant_context: { participants: [{ ref: "actor:two", display_name: "Мира", identity: { display_name: "Мира", display_name_state: "present", role_id: "external_codex_incarnation" }, task_context: {}, model_realization: {} }] } })[0];
process.stdout.write(JSON.stringify({ actor: actor && actor.title, participant: participant && participant.title }));
'''
        )
        self.assertEqual(observed, {"actor": "Luna", "participant": "Мира"})

    def test_diagnostics_materializes_raw_detail_only_after_developer_disclosure(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  const listeners = {};
  return { tagName: tag, children: [], dataset: {}, className: "", open: false, textContent: "", append(...items) { this.children.push(...items); }, addEventListener(name, listener) { listeners[name] = listener; }, setAttribute() {}, trigger(name) { if (listeners[name]) listeners[name](); } };
}
const context = { globalThis: null, document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; }, createElement: node }, localStorage: { getItem() { return null; }, setItem() {} }, location: { hash: "" }, history: { replaceState() {} }, fetch() { return new Promise(() => {}); }, setInterval() {}, addEventListener() {}, navigator: { language: "en-US" } };
context.globalThis = context; context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const target = node("section");
context.AoaDashboardApp.renderDiagnosticRoutes({ goal: { goal_id: "goal:test", title: "Goal", source_refs: [{ ref: "source:goal", sha256: "abc" }] }, correlation: { evidence_refs: [] } }, target);
const inspector = target.children[0];
const developer = inspector.children[1].children[1].children[1];
const before = JSON.stringify(target).includes('"tagName":"pre"');
const beforeRefs = JSON.stringify(target).includes("source:goal");
developer.open = true;
developer.trigger("toggle");
const after = developer.children.some((child) => child.tagName === "pre");
const afterRefs = JSON.stringify(developer).includes("source:goal");
process.stdout.write(JSON.stringify({ before, beforeRefs, after, afterRefs, inspectorClass: inspector.className, developerClass: developer.className }));
'''
        )
        self.assertFalse(observed["before"])
        self.assertFalse(observed["beforeRefs"])
        self.assertTrue(observed["after"])
        self.assertTrue(observed["afterRefs"])
        self.assertEqual(observed["inspectorClass"], "diagnostics-inspector")
        self.assertEqual(observed["developerClass"], "developer-details")

    def test_home_groups_owner_catalog_without_rendering_machine_refs(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  const listeners = {};
  return { tagName: tag, children: [], firstChild: null, className: "", textContent: "", dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, append(...items) { this.children.push(...items); }, removeChild() {}, setAttribute(name, value) { this[name] = value; }, addEventListener(name, listener) { listeners[name] = listener; }, trigger(name) { listeners[name]?.(); }, focus() {} };
}
const nodes = new Map([["goal-selector", node("div")], ["catalog-state", node("div")], ["live-region", node("div")]]);
const document = { documentElement: { lang: "", dataset: {} }, title: "", querySelectorAll() { return []; }, getElementById(id) { return nodes.get(id) || null; }, createElement: node, addEventListener() {} };
let routed = "";
const context = { document, globalThis: null, localStorage: { getItem() { return null; }, setItem() {} }, location: { hash: "" }, history: { replaceState(_state, _title, value) { routed = value; } }, fetch() { return new Promise(() => {}); }, setInterval() {}, addEventListener() {}, navigator: { language: "ru-RU" }, AoaDashboardTheme: { getMode() { return "dark"; }, subscribe() {} } };
context.globalThis = context; context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
context.AoaDashboardApp.renderHome({
  presentation: { goal: { title: { ru: "Текущая цель", en: "Current Goal" } } },
  goal: { goal_id: "current-goal", title: "machine fallback", state: "bound" },
  lifecycle: [],
  goal_catalog: {
    schema_version: "aoa_dashboard_goal_catalog_projection_v1",
    state: "current",
    currentness: "current",
    source: {
      owner: "aoa-dashboard",
      ref: "aoa-dashboard:goal-catalog-federation",
      kind: "derived_federation",
      currentness: "current",
      inputs: [
        { owner: "aoa-session-memory", ref: "aoa-session-memory:goal-lifecycles", currentness: "stale" },
        { owner: "codex-app-server", ref: "codex-app-server:goal-catalog", currentness: "current_at_read" },
      ],
    },
    items: [
      { ref: "019f9075-41a3-7933-a81d-f32bc4da12ca", title: "Развить пространство целей", title_locale: "ru", title_state: "available", lifecycle_state: "active", group: "active", first_observed_at: null, last_observed_at: "2026-08-22T21:00:00Z", ambiguity: false },
      { ref: "019e967f-1747-7ec0-a056-9e626300d531", title: null, title_state: "withheld", lifecycle_state: "complete", group: "completed", first_observed_at: null, last_observed_at: null, ambiguity: true },
    ],
    counts_by_group: { active: 1, completed: 1 },
    claim_limit: "bounded owner projection",
  },
});
const rendered = JSON.stringify(nodes.get("goal-selector"));
const note = JSON.stringify(nodes.get("catalog-state"));
const group = nodes.get("goal-selector").children.find((child) => child.className === "goal-group");
const row = group.children[1].children[0];
row.trigger("click");
process.stdout.write(JSON.stringify({ rendered, note, selection: context.AoaDashboardApp.getSelection(), routed }));
'''
        )
        self.assertIn("Текущая цель", observed["rendered"])
        self.assertIn("Развить пространство целей", observed["rendered"])
        self.assertIn("Активные", observed["rendered"])
        self.assertNotIn("019f9075", observed["rendered"])
        self.assertNotIn("019e967f", observed["rendered"])
        self.assertIn("История целей обновляется", observed["note"])
        self.assertIn("Ещё без отображаемого названия: 1", observed["note"])
        self.assertEqual(observed["selection"]["goal_ref"], "019f9075-41a3-7933-a81d-f32bc4da12ca")
        self.assertIn("#goal/019f9075-41a3-7933-a81d-f32bc4da12ca/trajectory", observed["routed"])

    def test_home_and_selected_goal_connection_states_follow_projection_refresh_state(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function makeNode(tag, documentRef) {
  const classes = new Set();
  const listeners = {};
  const node = {
    tagName: tag, children: [], firstChild: null, className: "", textContent: "", dataset: {}, style: {}, value: "", type: "", name: "", disabled: false, open: false, scrollTop: 0, scrollLeft: 0,
    classList: {
      add(...names) { names.forEach((name) => classes.add(name)); node.className = [...classes].join(" "); },
      remove(...names) { names.forEach((name) => classes.delete(name)); node.className = [...classes].join(" "); },
      toggle(name, force) { const enabled = force === undefined ? !classes.has(name) : Boolean(force); if (enabled) classes.add(name); else classes.delete(name); node.className = [...classes].join(" "); return enabled; },
      contains(name) { return classes.has(name); },
    },
    append(...items) { node.children.push(...items.filter(Boolean)); node.firstChild = node.children[0] || null; },
    appendChild(item) { node.append(item); return item; },
    removeChild(item) { const index = node.children.indexOf(item); if (index >= 0) node.children.splice(index, 1); node.firstChild = node.children[0] || null; },
    setAttribute(name, value) { node[name] = String(value); },
    getAttribute(name) { return node[name] ?? null; },
    removeAttribute(name) { delete node[name]; },
    addEventListener(name, listener) { listeners[name] = listener; },
    focus() { documentRef.activeElement = node; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  return node;
}
function textOf(node) { return node.textContent || (node.children || []).map(textOf).join(""); }
function projection() {
  return {
    generated_at: "2026-08-23T22:00:00Z",
    goal: { goal_id: "goal:current", master_thread_id: "thread:current", title: "Current Goal", state: "bound" },
    goal_catalog: { schema_version: "aoa_dashboard_goal_catalog_projection_v1", state: "current", currentness: "current", source: { owner: "aoa-dashboard", ref: "aoa-dashboard:catalog", currentness: "current" }, items: [{ ref: "goal:current", title: "Current Goal", title_locale: "en", title_state: "available", lifecycle_state: "active", group: "active", first_observed_at: null, last_observed_at: "2026-08-23T22:00:00Z", ambiguity: false }], counts_by_group: { active: 1 }, claim_limit: "bounded" },
    dag: [], directions: [], trajectories: [], pressure_inbox: { status: "missing", items: [] }, correlation: { state: "missing", evidence_refs: [] }, sources: [], lifecycle: [], annotations: { state: "missing", items: [] }, action_intents: { state: "missing", items: [] },
  };
}
async function load(hash, failInitially = false) {
  const nodes = new Map();
  let pendingResolve;
  let fetchMode = failInitially ? "fail" : "pending";
  const document = {
    activeElement: null, title: "", documentElement: { lang: "", dataset: {} },
    querySelectorAll() { return []; },
    getElementById(id) { if (!nodes.has(id)) nodes.set(id, makeNode(id, document)); return nodes.get(id); },
    createElement(tag) { return makeNode(tag, document); }, addEventListener() {},
  };
  const context = {
    document, globalThis: null, window: null, console,
    localStorage: { getItem() { return null; }, setItem() {} },
    location: { hash }, history: { replaceState() {} }, navigator: { language: hash ? "ru-RU" : "en-US" },
    fetch() {
      if (fetchMode === "fail") return Promise.reject(new Error("offline"));
      return new Promise((resolve) => { pendingResolve = resolve; });
    },
    setInterval() {}, addEventListener() {}, URLSearchParams,
    AoaDashboardTheme: { getMode() { return "system"; }, getDensity() { return "comfortable"; }, setLabels() {}, subscribe() {} },
  };
  context.globalThis = context; context.window = context;
  vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
  await new Promise((resolve) => setImmediate(resolve));
  const connection = () => ({ text: document.getElementById("connection").textContent, className: document.getElementById("connection").className });
  const refresh = () => textOf(document.getElementById("refresh-status"));
  const loading = connection();
  if (failInitially) return { loading, unavailable: { ...connection(), refresh: refresh() } };
  pendingResolve({ ok: true, async json() { return projection(); } });
  await new Promise((resolve) => setImmediate(resolve));
  const current = { ...connection(), refresh: refresh(), workspaceHidden: document.getElementById("workspace-view").classList.contains("hidden"), homeHidden: document.getElementById("home-view").classList.contains("hidden") };
  fetchMode = "fail";
  await context.AoaDashboardApp.refresh();
  return { loading, current, failed: { ...connection(), refresh: refresh(), workspaceHidden: document.getElementById("workspace-view").classList.contains("hidden"), homeHidden: document.getElementById("home-view").classList.contains("hidden") } };
}
(async () => {
  process.stdout.write(JSON.stringify({ home: await load(""), selected: await load("#goal/goal%3Acurrent/trajectory"), unavailable: await load("", true) }));
})();
'''
        )
        self.assertEqual(observed["home"]["loading"], {"text": "Checking", "className": "connection-state state-loading"})
        self.assertEqual(observed["home"]["current"]["text"], "Updated")
        self.assertEqual(observed["home"]["current"]["className"], "connection-state state-ready")
        self.assertFalse(observed["home"]["current"]["homeHidden"])
        self.assertTrue(observed["home"]["current"]["workspaceHidden"])
        self.assertEqual(observed["home"]["failed"]["text"], "Degraded")
        self.assertEqual(observed["home"]["failed"]["className"], "connection-state state-stale")
        self.assertIn("Trying again shortly.", observed["home"]["failed"]["refresh"])
        self.assertEqual(observed["selected"]["loading"], {"text": "Проверка", "className": "connection-state state-loading"})
        self.assertEqual(observed["selected"]["current"]["text"], "Обновлено")
        self.assertEqual(observed["selected"]["current"]["className"], "connection-state state-ready")
        self.assertTrue(observed["selected"]["current"]["homeHidden"])
        self.assertFalse(observed["selected"]["current"]["workspaceHidden"])
        self.assertEqual(observed["selected"]["failed"]["text"], "Сниженная актуальность")
        self.assertEqual(observed["selected"]["failed"]["className"], "connection-state state-stale")
        self.assertIn("Скоро будет новая попытка.", observed["selected"]["failed"]["refresh"])
        self.assertEqual(observed["unavailable"]["unavailable"]["text"], "Waiting")
        self.assertEqual(observed["unavailable"]["unavailable"]["className"], "connection-state state-disconnected")
        self.assertIn("Trying again shortly.", observed["unavailable"]["unavailable"]["refresh"])

    def test_home_catalog_paginates_groups_and_keeps_selected_ref_stable_on_refresh(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  const listeners = {};
  return { tagName: tag, children: [], firstChild: null, className: "", textContent: "", dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, append(...items) { this.children.push(...items); this.firstChild = this.children[0] || null; }, removeChild() { this.children.shift(); this.firstChild = this.children[0] || null; }, setAttribute(name, value) { this[name] = value; }, addEventListener(name, listener) { listeners[name] = listener; }, trigger(name) { listeners[name]?.(); }, focus() {} };
}
const nodes = new Map([["goal-selector", node("div")], ["catalog-state", node("div")], ["live-region", node("div")]]);
const document = { documentElement: { lang: "", dataset: {} }, title: "", querySelectorAll() { return []; }, getElementById(id) { return nodes.get(id) || null; }, createElement: node, addEventListener() {} };
const context = { document, globalThis: null, localStorage: { getItem() { return null; }, setItem() {} }, location: { hash: "" }, history: { replaceState() {} }, fetch() { return new Promise(() => {}); }, setInterval() {}, addEventListener() {}, navigator: { language: "en-US" }, AoaDashboardTheme: { getMode() { return "system"; }, subscribe() {} } };
context.globalThis = context; context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const item = (ref, group, lifecycle = group === "completed" ? "complete" : group === "attention" ? "blocked" : group) => ({ ref, title: `Goal ${ref}`, title_locale: "en", title_state: "available", lifecycle_state: lifecycle, group, first_observed_at: null, last_observed_at: "2026-08-23T00:00:00Z", ambiguity: false });
const active = Array.from({ length: 7 }, (_, index) => item(String(index + 1), "active"));
const items = [...active, item("attention", "attention"), item("paused", "paused"), item("completed", "completed")];
const data = { goal: {}, goal_catalog: { schema_version: "aoa_dashboard_goal_catalog_projection_v1", state: "current", currentness: "current", source: { owner: "aoa-session-memory", ref: "aoa-session-memory:goal-lifecycles", owner_schema_version: "aoa_session_memory_goal_catalog_v1", currentness: "current" }, items, counts_by_group: { active: 7, attention: 1, paused: 1, completed: 1 }, claim_limit: "bounded owner projection" } };
context.AoaDashboardApp.renderHome(data);
const selector = nodes.get("goal-selector");
const groups = selector.children.filter((child) => child.className === "goal-group");
const activeGroup = groups[0];
const pager = activeGroup.children[2];
const firstPageRefs = activeGroup.children[1].children.map((row) => row.children[0].children[0].textContent);
pager.children[2].trigger("click");
context.AoaDashboardApp.renderHome(data);
const secondPageRefs = selector.children.find((child) => child.className === "goal-group").children[1].children.map((row) => row.children[0].children[0].textContent);
const selectedRow = selector.children.find((child) => child.className === "goal-group").children[1].children[0];
selectedRow.trigger("click");
const refreshed = { ...data, goal_catalog: { ...data.goal_catalog, items: [active[6], ...active.slice(0, 6), ...items.slice(7)] } };
context.AoaDashboardApp.renderHome(refreshed);
const stableRow = selector.children.find((child) => child.className === "goal-group").children[1].children[0];
process.stdout.write(JSON.stringify({ groupCount: groups.length, activePageCount: pager.children[1].textContent, firstPageRefs, secondPageRefs, selected: context.AoaDashboardApp.getSelection().goal_ref, stableTitle: stableRow.children[0].children[0].textContent, stablePressed: stableRow["aria-pressed"] }));
'''
        )
        self.assertEqual(observed["groupCount"], 4)
        self.assertEqual(observed["activePageCount"], "1 / 2")
        self.assertEqual(observed["firstPageRefs"], ["Goal 1", "Goal 2", "Goal 3", "Goal 4", "Goal 5", "Goal 6"])
        self.assertEqual(observed["secondPageRefs"], ["Goal 7"])
        self.assertEqual(observed["selected"], "7")
        self.assertEqual(observed["stableTitle"], "Goal 7")
        self.assertEqual(observed["stablePressed"], "true")

    def test_catalog_titles_and_participant_cards_fail_closed_by_language_and_identity_quality(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  return { tagName: tag, children: [], firstChild: null, className: "", textContent: "", dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, append(...items) { this.children.push(...items); this.firstChild = this.children[0] || null; }, removeChild() { this.children.shift(); this.firstChild = this.children[0] || null; }, setAttribute(name, value) { this[name] = value; }, addEventListener() {}, focus() {} };
}
function load(language) {
  const nodes = new Map([["goal-selector", node("div")], ["catalog-state", node("div")], ["live-region", node("div")]]);
  const document = { documentElement: { lang: "", dataset: {} }, title: "", querySelectorAll() { return []; }, getElementById(id) { return nodes.get(id) || null; }, createElement: node, addEventListener() {} };
  const context = { document, globalThis: null, localStorage: { getItem() { return language; }, setItem() {} }, location: { hash: "" }, history: { replaceState() {} }, fetch() { return new Promise(() => {}); }, setInterval() {}, addEventListener() {}, navigator: { language: language === "ru" ? "ru-RU" : "en-US" }, AoaDashboardTheme: { subscribe() {} } };
  context.globalThis = context; context.window = context;
  vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
  vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
  return { app: context.AoaDashboardApp, rendered: () => JSON.stringify(nodes.get("goal-selector")) };
}
const catalog = { schema_version: "aoa_dashboard_goal_catalog_projection_v1", state: "current", currentness: "current", source: { owner: "aoa-session-memory", ref: "aoa-session-memory:goal-lifecycles", owner_schema_version: "aoa_session_memory_goal_catalog_v1", currentness: "current" }, items: [{ ref: "goal:localized", title: "Русская цель", title_locale: "ru", title_state: "available", lifecycle_state: "active", group: "active", first_observed_at: null, last_observed_at: null, ambiguity: false }], counts_by_group: { active: 1 }, claim_limit: "bounded owner projection" };
const en = load("en"); const ru = load("ru");
en.app.renderHome({ goal: {}, goal_catalog: catalog });
ru.app.renderHome({ goal: {}, goal_catalog: catalog });
const invalidContext = { participant_context: { state: "invalid", participants: [{ ref: "actor:invalid", identity: { display_name: "Invented Person", display_name_state: "present", role_id: "master" } }] } };
const invalidActivity = { actor_activity: { state: "invalid", actors: [{ actor_key: "actor:invalid", identity: { display_name: "Invented Actor" }, responsibility: { holder: "Master" } }] } };
process.stdout.write(JSON.stringify({ en: en.rendered(), ru: ru.rendered(), invalidContext: en.app.participantItems(invalidContext), invalidActivity: en.app.participantItems(invalidActivity) }));
'''
        )
        self.assertIn("Goal title unavailable", observed["en"])
        self.assertNotIn("Русская цель", observed["en"])
        self.assertIn("Русская цель", observed["ru"])
        self.assertEqual(observed["invalidContext"], [])
        self.assertEqual(observed["invalidActivity"], [])

    def test_thread_surface_is_deferred_metadata_inspector_until_public_items_exist(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Metadata inspector", html)
        self.assertIn("Inspector", html)
        self.assertIn('t("thread.deferredNotice")', app)
        self.assertNotIn("thread board", html.lower())

    def test_catalog_goal_workspace_is_human_bounded_and_does_not_borrow_current_goal(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
function node(tag) {
  return { tagName: tag, children: [], firstChild: null, className: "", textContent: "", dataset: {}, classList: { add() {}, remove() {}, toggle() {} }, append(...items) { this.children.push(...items); }, removeChild() {}, setAttribute(name, value) { this[name] = value; }, addEventListener() {}, removeAttribute() {} };
}
const ids = ["catalog-workspace-heading", "catalog-workspace-summary", "catalog-workspace-lifecycle", "catalog-workspace-recency", "catalog-workspace-body"];
const nodes = new Map(ids.map((id) => [id, node(id)]));
const document = { documentElement: { lang: "", dataset: {} }, title: "", querySelectorAll() { return []; }, getElementById(id) { return nodes.get(id) || null; }, createElement: node, addEventListener() {} };
const context = { document, globalThis: null, localStorage: { getItem() { return null; }, setItem() {} }, location: { hash: "" }, history: { replaceState() {} }, fetch() { return new Promise(() => {}); }, setInterval() {}, addEventListener() {}, navigator: { language: "ru-RU" }, AoaDashboardTheme: { subscribe() {} } };
context.globalThis = context; context.window = context;
vm.runInNewContext(fs.readFileSync("web/preferences.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/i18n.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/ui_state.js", "utf8"), context);
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const data = {
  goal: { goal_id: "goal:current", title: "CURRENT MACHINE TITLE" },
  dag: [{ id: "D4", title: "CURRENT TECHNICAL DAG" }],
  goal_catalog: {
    schema_version: "aoa_dashboard_goal_catalog_projection_v1", state: "stale", currentness: "stale",
    source: { owner: "aoa-session-memory", ref: "aoa-session-memory:goal-lifecycles", owner_schema_version: "aoa_session_memory_goal_catalog_v1", currentness: "stale" },
    items: [{ ref: "019e967f-1747-7ec0-a056-9e626300d531", title: "Развить пространство целей", title_locale: "ru", title_state: "available", lifecycle_state: "complete", group: "completed", first_observed_at: null, last_observed_at: "2026-06-05T09:12:53Z", ambiguity: true }],
    counts_by_group: { completed: 1 }, claim_limit: "bounded owner projection",
  },
};
const item = context.AoaDashboardApp.catalogItemForRef(data, "019e967f-1747-7ec0-a056-9e626300d531");
context.AoaDashboardApp.renderCatalogWorkspace(data, item);
const rendered = JSON.stringify([...nodes.values()]);
process.stdout.write(JSON.stringify({ rendered, heading: nodes.get("catalog-workspace-heading").textContent, lifecycle: nodes.get("catalog-workspace-lifecycle").textContent }));
'''
        )
        self.assertEqual(observed["heading"], "Развить пространство целей")
        self.assertEqual(observed["lifecycle"], "Завершено")
        self.assertIn("Первое наблюдение", observed["rendered"])
        self.assertIn("Время недоступно", observed["rendered"])
        self.assertIn("Подробности этой цели пока не опубликованы", observed["rendered"])
        self.assertIn("Часть ранней активности могла не сохраниться", observed["rendered"])
        self.assertNotIn("019e967f", observed["rendered"])
        self.assertNotIn("CURRENT", observed["rendered"])
        self.assertNotIn("1970", observed["rendered"])

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
