from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(source: str) -> object:
    result = subprocess.run(["node", "-e", source], cwd=ROOT, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


class GoalContextUiProjectionTests(unittest.TestCase):
    def test_public_projection_keeps_empty_states_and_hides_private_payloads(self) -> None:
        observed = run_node(
            r'''
const fs = require("fs");
const vm = require("vm");
const context = {
  document: { documentElement: { lang: "", dataset: {} }, querySelectorAll() { return []; }, getElementById() { return null; }, createElement() { return { dataset: {}, append() {}, setAttribute() {}, addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} } }; } },
  globalThis: null,
  console,
  fetch() { return new Promise(() => {}); },
  setInterval() {},
  location: { hash: "" },
  history: { replaceState() {} },
  AoaDashboardI18n: { createI18n() { return { language: "en", locale: "en-US", t(key, values = {}) { return key + (values.count ? `:${values.count}` : ""); }, status(value) { return String(value); }, plural(key, count) { return `${key}:${count}`; }, subscribe() {} }; } },
};
context.globalThis = context;
context.window = context;
vm.runInNewContext(fs.readFileSync("web/app.js", "utf8"), context);
const data = {
  goal_context: {
    thread_board: {
      state: "current",
      items: [{ item_ref: "item-ref:1", review_state: "reviewed_public_safe", body: "PRIVATE_TRANSCRIPT", prompt: "PRIVATE_PROMPT" }],
      relations: [],
      evidence_refs: [{ ref: "source:thread", kind: "owner" }],
    },
    participant_graph: {
      state: "current",
      records: [{ relation_id: "rel-record:1", state: "present", dimensions: {
        obligation_role: { state: "present" }, task_assignment: { state: "present" }, model_realization: { state: "missing" }, runtime_incarnation: { state: "unknown" },
      }}],
    },
  },
};
const empty = { goal_context: { thread_board: { state: "deferred", items: [] }, participant_graph: { state: "missing", records: [] } } };
const thread = context.AoaDashboardApp.goalThreadItems(data);
const assignments = context.AoaDashboardApp.participantAssignmentItems(data);
const emptyThread = context.AoaDashboardApp.goalThreadItems(empty);
const emptyAssignments = context.AoaDashboardApp.participantAssignmentItems(empty);
process.stdout.write(JSON.stringify({
  threadCount: thread.length,
  threadTitle: thread[0]?.title,
  assignmentCount: assignments.length,
  assignmentTitle: assignments[0]?.title,
  assignmentRole: assignments[0]?.role,
  emptyThread,
  emptyAssignments,
  serialized: JSON.stringify({ thread, assignments }),
}));
'''
        )
        self.assertEqual(observed["threadCount"], 1)
        self.assertEqual(observed["assignmentCount"], 1)
        self.assertEqual(observed["threadTitle"], "thread.boardItem")
        self.assertEqual(observed["assignmentTitle"], "participants.assignment")
        self.assertEqual(observed["assignmentRole"], "present")
        self.assertEqual(observed["emptyThread"], [])
        self.assertEqual(observed["emptyAssignments"], [])
        self.assertNotIn("PRIVATE_TRANSCRIPT", observed["serialized"])
        self.assertNotIn("PRIVATE_PROMPT", observed["serialized"])

    def test_en_ru_keys_and_narrow_inspector_rules_are_present(self) -> None:
        source = (ROOT / "web" / "i18n.js").read_text(encoding="utf-8")
        styles = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        for key in (
            "thread.boardHeading",
            "thread.boardDeferred",
            "thread.boardNoBranch",
            "participants.assignment",
            "participants.assignmentDeferred",
            "evidence.goalThreadBoard",
            "evidence.participantRelations",
        ):
            self.assertGreaterEqual(source.count(f'"{key}"'), 2)
        self.assertIn(".thread-board {", styles)
        self.assertIn(".thread-board-item { min-width: 0;", styles)
        self.assertIn("@media (max-width: 760px)", styles)
        self.assertIn(".workspace-thread { grid-column: 1 / -1;", styles)

    def test_source_provenance_is_optional_detail_and_operation_surface_stays_separate(self) -> None:
        source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function renderGoalThreadBoard", source)
        self.assertIn('details.dataset.detailKey = "thread-board:source"', source)
        self.assertIn("function renderOperateRoute", source)
        self.assertNotIn("window.open", source)
        self.assertNotIn("document.dispatchEvent", source)


if __name__ == "__main__":
    unittest.main()
