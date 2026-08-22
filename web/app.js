const { createI18n } = window.AoaDashboardI18n;
const i18n = createI18n();

const LIFECYCLE = [
  "planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "wake requested", "reentered",
];
const QUALITY = ["missing", "unknown", "stale", "deferred", "invalid"];
const LENSES = ["trajectory", "attention", "participants", "evidence", "records"];
const PRESENTATION_HANDLER_NAME = "aoaDashboardPresentation";
const PRESENTATION_LANGUAGES = new Set(["en", "ru"]);
const PRESENTATION_THEMES = new Set(["system", "light", "dark"]);
const MAX_TRAJECTORY_ITEMS = 18;
const MAX_CORRELATION_ENVELOPES = 10;
const MAX_ACTOR_CARDS = 24;
const MAX_PRESSURE_ITEMS = 12;
const MAX_SOURCE_CARDS = 18;
const MAX_OWNER_ROWS = 24;
const MAX_REFS_PER_ITEM = 8;
const SelectionContext = Object.freeze({
  fields: Object.freeze(["goal_ref", "lens", "focus_ref", "branch_path", "thread_ref", "expanded_branch_refs", "observation_cursor_or_generation"]),
  empty() {
    return {
      goal_ref: null,
      lens: "trajectory",
      focus_ref: null,
      branch_path: [],
      thread_ref: null,
      expanded_branch_refs: [],
      observation_cursor_or_generation: null,
    };
  },
});

let currentProjection = null;
let lastGoodProjection = null;
let refreshState = "loading";
let lastGoodAt = null;
let lastAnnouncement = "";
let workspaceMode = "observe";
let contextThreadOpen = true;
let selectionQuality = null;
let selection = SelectionContext.empty();

const byId = (id) => document.getElementById(id);
const clear = (element) => { if (element) while (element.firstChild) element.removeChild(element.firstChild); };
const t = (key, variables = {}) => i18n.t(key, variables);
const statusLabel = (value) => i18n.status(value);
const arrayOrEmpty = (value) => Array.isArray(value) ? value : [];

function text(tag, value, className = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null ? "" : String(value);
  return node;
}

function badge(value) {
  const canonicalValue = value == null || value === "" ? "unknown" : String(value);
  return text("span", statusLabel(canonicalValue), `badge state-${canonicalValue.replaceAll(" ", "-")}`);
}

function setBadge(node, value) {
  if (!node) return;
  const canonicalValue = value == null || value === "" ? "unknown" : String(value);
  node.textContent = statusLabel(canonicalValue);
  node.className = `badge state-${canonicalValue.replaceAll(" ", "-")}`;
}

function bounded(items, limit, selectedRef = null) {
  const values = arrayOrEmpty(items);
  if (values.length <= limit) return { items: values, total: values.length, omitted: 0 };
  const first = values.slice(0, limit);
  if (selectedRef) {
    const selected = values.find((item) => item && item.ref === selectedRef);
    if (selected && !first.includes(selected)) first[first.length - 1] = selected;
  }
  return { items: first, total: values.length, omitted: values.length - first.length };
}

function boundedJson(value, limit = 5000) {
  let serialized = "";
  try { serialized = JSON.stringify(value, null, 2); } catch (_error) { serialized = t("fallback.unavailable"); }
  return serialized.length > limit ? `${serialized.slice(0, limit)}\n… ${t("bounded.truncated")}` : serialized;
}

function announce(message) {
  if (!message || message === lastAnnouncement) return;
  lastAnnouncement = message;
  const target = byId("live-region");
  if (target) target.textContent = message;
}

function applyStaticTranslations() {
  document.documentElement.lang = i18n.language;
  if (document.title !== t("app.title")) document.title = t("app.title");
  if (window.AoaDashboardTheme?.setLabels) {
    window.AoaDashboardTheme.setLabels({
      label: t("theme.label"),
      ariaLabel: t("theme.ariaLabel"),
      system: t("theme.system"),
      light: t("theme.light"),
      dark: t("theme.dark"),
    });
  }
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  for (const node of document.querySelectorAll("[data-i18n-aria-label]")) node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
  for (const button of document.querySelectorAll("[data-language]")) button.setAttribute("aria-pressed", String(button.dataset.language === i18n.language));
  updateLensButtons();
  updateModeButtons();
}

function publishNativePresentationPreference() {
  const language = i18n.language;
  const theme = window.AoaDashboardTheme?.getMode?.();
  const handler = window.webkit?.messageHandlers?.[PRESENTATION_HANDLER_NAME];
  if (!PRESENTATION_LANGUAGES.has(language) || !PRESENTATION_THEMES.has(theme)) return;
  if (!handler || typeof handler.postMessage !== "function") return;
  handler.postMessage({ language, theme });
}

function activityValue(group, key) {
  const value = group?.[key];
  return value == null || value === "" ? statusLabel("unknown") : value;
}

function evidenceList(refs, limit = MAX_REFS_PER_ITEM) {
  const list = document.createElement("div");
  list.className = "ref-list";
  const values = arrayOrEmpty(refs).filter(Boolean);
  for (const ref of values.slice(0, limit)) {
    const digest = ref.sha256 ? ` · ${t("evidence.sha256", { value: ref.sha256 })}` : "";
    const observed = ref.observed_at ? ` · ${t("evidence.observed", { value: ref.observed_at })}` : "";
    const label = ref.label || ref.kind || t("evidence.ref");
    const location = ref.ref || ref.path || t("evidence.unresolved");
    const code = text("code", `${label}: ${location}${digest}${observed}`);
    list.append(code);
  }
  if (values.length > limit) list.append(text("p", t("bounded.refsOmitted", { count: values.length - limit }), "claim"));
  return list;
}

function goalRef(data) {
  return data?.goal?.goal_id || data?.goal?.goal_ref || null;
}

function goalTitle(data) {
  return data?.goal?.title || t("goal.unnamed");
}

function qualityForData(data) {
  const observed = [
    data?.correlation?.state,
    data?.correlation_read_model?.status,
    data?.pressure_inbox?.status,
    data?.actor_activity?.state,
  ].map((value) => String(value || "").toLowerCase());
  for (const value of ["invalid", "deferred", "stale", "missing", "unknown"]) if (observed.includes(value)) return value;
  return "unknown";
}

function lifecycleForData(data) {
  const values = arrayOrEmpty(data?.lifecycle);
  for (const step of [...LIFECYCLE].reverse()) {
    const item = values.find((candidate) => candidate?.step === step && candidate.state && !QUALITY.includes(candidate.state));
    if (item) return item.state;
  }
  return data?.goal?.state || "unknown";
}

function currentnessForData(data) {
  return data?.correlation?.master_filter?.currentness?.state
    || data?.correlation_read_model?.rebuild?.source_currentness
    || data?.correlation?.freshness
    || "unknown";
}

function updateLensButtons() {
  for (const button of document.querySelectorAll("[data-lens]")) {
    const active = button.dataset.lens === selection.lens;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
}

function updateModeButtons() {
  for (const button of document.querySelectorAll("[data-mode]")) {
    const active = button.dataset.mode === workspaceMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function syncRoute() {
  if (!selection.goal_ref || !window.history || !window.location) return;
  const focus = selection.focus_ref ? `?focus=${encodeURIComponent(selection.focus_ref)}${selection.thread_ref ? `&thread=${encodeURIComponent(selection.thread_ref)}` : ""}` : "";
  const hash = `#goal/${encodeURIComponent(selection.goal_ref)}/${selection.lens}${focus}`;
  try { window.history.replaceState(null, "", hash); } catch (_error) { /* a native WebView may not expose history */ }
}

function readRoute() {
  const raw = window.location?.hash || "";
  const match = raw.match(/^#goal\/([^/]+)\/([^?]+)(?:\?(.+))?$/);
  if (!match) return;
  const params = new URLSearchParams(match[3] || "");
  const lens = LENSES.includes(match[2]) ? match[2] : "trajectory";
  selection = {
    ...selection,
    goal_ref: decodeURIComponent(match[1]),
    lens,
    focus_ref: params.get("focus"),
    thread_ref: params.get("thread"),
  };
}

function setSelection(patch) {
  selection = { ...selection, ...patch };
  if (Object.prototype.hasOwnProperty.call(patch, "goal_ref") && !patch.goal_ref) selectionQuality = null;
  if (Object.prototype.hasOwnProperty.call(patch, "focus_ref")) selectionQuality = null;
  if (!Array.isArray(selection.branch_path)) selection.branch_path = [];
  if (!Array.isArray(selection.expanded_branch_refs)) selection.expanded_branch_refs = [];
  if (selection.goal_ref && !selection.thread_ref) selection.thread_ref = selection.goal_ref;
  if (selection.focus_ref && !selection.branch_path.length) selection.branch_path = [selection.focus_ref];
  syncRoute();
  if (currentProjection) renderProjection(currentProjection);
}

function createPanel(kickerKey, titleKey, claimKey) {
  const panel = document.createElement("article");
  panel.className = "panel lens-panel";
  if (kickerKey) panel.append(text("div", t(kickerKey), "section-kicker"));
  const heading = document.createElement("h3");
  heading.textContent = t(titleKey);
  panel.append(heading);
  if (claimKey) panel.append(text("p", t(claimKey), "claim"));
  const body = document.createElement("div");
  body.className = "lens-panel-body";
  panel.append(body);
  return { panel, body };
}

function renderRefreshState() {
  const target = byId("refresh-status");
  if (!target || typeof document.createElement !== "function") return;
  clear(target);
  target.className = `quality-banner state-${refreshState}`;
  if (refreshState === "loading") {
    target.append(text("strong", t("refresh.loading")), text("span", t("refresh.noCounts")));
  } else if (refreshState === "current") {
    target.append(text("strong", t("refresh.current")), text("span", lastGoodAt ? t("refresh.lastGood", { value: lastGoodAt }) : t("refresh.updated")));
  } else if (refreshState === "stale") {
    target.append(text("strong", t("refresh.stale")), text("span", t("refresh.lastGood", { value: lastGoodAt || t("fallback.unknown") })), text("span", t("refresh.retry")));
  } else {
    target.append(text("strong", t("refresh.disconnected")), text("span", t("refresh.retry")));
  }
}

function renderHeader(data) {
  const goal = data.goal || {};
  const generated = data.generated_at || t("fallback.unknown");
  const goalId = goal.goal_id || t("goal.idMissing");
  const title = goal.title || t("goal.unnamed");
  const quality = qualityForData(data);
  const lifecycle = lifecycleForData(data);
  const connection = byId("connection");
  if (connection) {
    connection.textContent = refreshState === "current" ? t("connection.hostLocalRead") : t("connection.projectionUnavailable");
    connection.className = `badge state-${refreshState === "current" ? "bound" : refreshState === "stale" ? "stale" : "invalid"}`;
  }
  const generatedNode = byId("generated");
  if (generatedNode) generatedNode.textContent = t("label.generated", { value: generated });
  const workspaceGenerated = byId("workspace-generated");
  if (workspaceGenerated) workspaceGenerated.textContent = t("label.generated", { value: generated });
  const heading = byId("workspace-heading");
  if (heading) heading.textContent = title;
  const workspaceGoal = byId("workspace-goal-button");
  if (workspaceGoal) {
    workspaceGoal.textContent = title;
    workspaceGoal.setAttribute("aria-label", t("home.openWorkspace"));
  }
  const workspaceId = byId("workspace-goal-id");
  if (workspaceId) workspaceId.textContent = goalId;
  setBadge(byId("workspace-lifecycle"), lifecycle);
  setBadge(byId("workspace-quality"), quality);
}

function renderHome(data) {
  const selector = byId("goal-selector");
  const catalogState = byId("catalog-state");
  clear(selector);
  clear(catalogState);
  const goal = data?.goal || {};
  if (!goal.goal_id) {
    selector.append(text("p", t("home.goalUnavailable"), "claim"));
    catalogState.className = "empty-state state-missing";
    catalogState.append(badge("missing"), text("span", t("home.goalUnavailable")));
    return;
  }
  const card = document.createElement("article");
  card.className = "goal-selector-card";
  const main = document.createElement("div");
  main.className = "goal-selector-main";
  main.append(text("div", t("home.currentGoal"), "section-kicker"));
  main.append(text("h3", goal.title || t("goal.unnamed")));
  main.append(text("div", goal.goal_id, "mono muted"));
  const states = document.createElement("div");
  states.className = "goal-card-states";
  states.append(badge(lifecycleForData(data)), badge(qualityForData(data)));
  main.append(states);
  const open = document.createElement("button");
  open.type = "button";
  open.className = "goal-open-button";
  open.textContent = t("home.openWorkspace");
  open.setAttribute("aria-label", `${t("home.openWorkspace")}: ${goal.title || goal.goal_id}`);
  open.addEventListener("click", () => {
    setSelection({ goal_ref: goalRef(data), lens: "trajectory", focus_ref: null, branch_path: [], thread_ref: goal.master_thread_id || goal.goal_id });
    const center = byId("center-surface");
    if (center?.focus) center.focus();
  });
  card.append(main, open);
  selector.append(card);

  const hasCatalog = Array.isArray(data.goal_catalog) && data.goal_catalog.length > 0;
  catalogState.className = `empty-state ${hasCatalog ? "state-bound" : "state-missing"}`;
  catalogState.append(badge(hasCatalog ? "bound" : "missing"), text("span", hasCatalog ? t("home.catalogReady") : t("home.catalogMissing")));
  if (!hasCatalog) catalogState.append(text("span", t("home.categoryLimit"), "claim"));
  if (selectionQuality === "missing" && selection.goal_ref && selection.goal_ref !== goalRef(data)) {
    const retained = document.createElement("div");
    retained.className = "empty-state state-missing";
    retained.append(badge("missing"), text("span", t("selection.missing")), text("span", t("selection.ref", { value: selection.goal_ref }), "mono"));
    selector.append(retained);
  }
}

function renderGoalSummary(data) {
  const target = byId("goal-summary");
  clear(target);
  const goal = data.goal || {};
  const details = document.createElement("details");
  details.className = "summary-details";
  const summary = document.createElement("summary");
  summary.append(text("strong", goal.title || t("goal.unnamed")), badge(goal.state || "unknown"), badge(qualityForData(data)));
  details.append(summary);
  details.append(text("p", t("workspace.goalId", { value: goal.goal_id || t("fallback.missing") }), "mono"));
  details.append(text("p", t("workspace.currentness", { value: statusLabel(currentnessForData(data)) }), "mono"));
  details.append(text("p", t("workspace.digest", { value: goal.anchor_digest || t("fallback.missing") }), "mono"));
  details.append(text("p", t("workspace.historyLimit", { value: Array.isArray(data.goal_catalog) ? t("home.catalogReady") : t("home.catalogMissing") }), "claim"));
  if (selectionQuality === "stale") details.append(text("p", t("selection.stale"), "claim"));
  if (selectionQuality === "missing") details.append(text("p", t("selection.missing"), "claim"));
  const holder = data.current_holder || {};
  details.append(text("p", t("activity.masterContext", {
    value: holder.label || holder.holder || holder.actor_id || t("fallback.masterHolderUnknown"),
  }), "claim"));
  details.append(evidenceList(goal.source_refs));
  details.append(text("p", goal.claim_limit || t("workspace.claim"), "claim"));
  target.append(details);
}

function renderRailQuality(data) {
  const target = byId("rail-quality");
  if (!target) return;
  clear(target);
  target.append(badge(qualityForData(data)), text("p", t("workspace.currentness", { value: statusLabel(currentnessForData(data)) }), "mono"), text("p", t("workspace.claim"), "claim"));
}

function renderAttentionStrip(data) {
  const target = byId("attention-strip");
  clear(target);
  const inbox = data.pressure_inbox || {};
  const critical = arrayOrEmpty(inbox.critical_next_routes);
  const items = arrayOrEmpty(inbox.items);
  const head = document.createElement("div");
  head.className = "attention-head";
  head.append(text("div", t("lens.attention"), "section-kicker"), badge(inbox.status || "missing"));
  target.append(head);
  const summary = document.createElement("div");
  summary.className = "attention-summary";
  summary.append(text("strong", t("pressure.summary", { admitted: items.length, critical: critical.length, legacy: arrayOrEmpty(inbox.legacy_candidates).length })));
  summary.append(text("span", t("workspace.quality") + ": " + statusLabel(qualityForData(data)), "mono"));
  target.append(summary);
  if (critical.length) {
    const route = critical[0];
    target.append(text("p", `${t("pressure.criticalNextRoute")}: ${route.route || route.next_route?.route || t("fallback.routeMissing")}`, "attention-route"));
  } else {
    target.append(text("p", t("attention.noPressure"), "claim"));
  }
}

function renderBreadcrumb(data) {
  const target = byId("breadcrumb");
  clear(target);
  const home = text("button", t("workspace.backToGoals"), "breadcrumb-button");
  home.type = "button";
  home.addEventListener("click", () => setSelection({ goal_ref: null, focus_ref: null, branch_path: [], thread_ref: null }));
  target.append(home);
  target.append(text("span", "/", "breadcrumb-separator"));
  target.append(text("span", goalTitle(data), "breadcrumb-current"));
  for (const ref of selection.branch_path || []) {
    target.append(text("span", "/", "breadcrumb-separator"));
    const item = text("button", ref, "breadcrumb-button mono");
    item.type = "button";
    item.addEventListener("click", () => setSelection({ focus_ref: ref, thread_ref: ref, branch_path: [ref] }));
    target.append(item);
  }
}

function renderTrajectoryItems(data, target) {
  const entries = [];
  for (const item of arrayOrEmpty(data.dag)) entries.push({ ref: `dag:${item.id}`, label: item.title || item.id, state: item.state, observation: item.observation, evidence_refs: item.evidence_refs, detail: item });
  for (const item of arrayOrEmpty(data.lifecycle)) entries.push({ ref: `lifecycle:${item.step}`, label: item.step, state: item.state, observation: item.observation, evidence_refs: item.evidence_refs, detail: item });
  for (const envelope of arrayOrEmpty(data.correlation?.envelopes)) {
    const returnId = envelope.return_observation?.return_id || envelope.correlation_id || t("fallback.return");
    entries.push({
      ref: `return:${returnId}`,
      label: t("label.lunaReturn", { value: returnId }),
      state: envelope.state || envelope.return_observation?.filter_disposition || "unknown",
      observation: envelope.return_observation?.filter_disposition ? statusLabel(envelope.return_observation.filter_disposition) : t("thread.metadataOnly"),
      evidence_refs: [envelope.return_observation?.ref, envelope.wake_observation?.ref, envelope.accepted_turn?.basis_ref],
      detail: { correlation_id: envelope.correlation_id, return_observation: envelope.return_observation, lifecycle: envelope.lifecycle },
    });
  }
  for (const item of arrayOrEmpty(data.pressure_inbox?.items)) {
    const pressureId = item.pressure_ref?.id || item.pressure_ref?.ref || t("fallback.pressure");
    entries.push({
      ref: `pressure:${pressureId}`,
      label: pressureId,
      state: item.outcome?.state || data.pressure_inbox?.status || "deferred",
      observation: item.affected_goal_criterion || t("fallback.goalCriterionMissing"),
      evidence_refs: item.evidence,
      detail: { pressure_ref: item.pressure_ref, next_route: item.next_route, natural_owner: item.natural_owner, claim_limit: item.claim_limit },
    });
  }
  if (!entries.length) {
    target.append(text("p", t("trajectory.noItems"), "empty-state"));
    return;
  }
  const expanded = selection.expanded_branch_refs.includes("trajectory:all");
  const windowed = expanded ? entries : entries.slice(0, MAX_TRAJECTORY_ITEMS);
  const list = document.createElement("div");
  list.className = "trajectory-list";
  for (const item of windowed) {
    const card = document.createElement("article");
    card.className = `trajectory-card${selection.focus_ref === item.ref ? " selected" : ""}`;
    const head = document.createElement("div");
    head.className = "trajectory-card-head";
    const select = document.createElement("button");
    select.type = "button";
    select.className = "trajectory-select";
    select.setAttribute("aria-pressed", String(selection.focus_ref === item.ref));
    select.setAttribute("aria-label", t("trajectory.select", { value: item.label }));
    select.append(text("strong", item.label), text("span", t("trajectory.item"), "mono muted"));
    select.addEventListener("click", () => {
      setSelection({ focus_ref: item.ref, thread_ref: item.ref, branch_path: [item.ref] });
      announce(`${t("trajectory.selected")}: ${item.label}`);
    });
    head.append(select, badge(item.state || "unknown"));
    card.append(head);
    card.append(text("p", item.observation || t("fallback.unavailable"), "claim"));
    const details = document.createElement("details");
    details.append(text("summary", t("evidence.metadata")));
    details.append(evidenceList(item.evidence_refs));
    details.append(text("pre", boundedJson(item.detail, 1800)));
    card.append(details);
    list.append(card);
  }
  target.append(list);
  if (!expanded && entries.length > windowed.length) {
    const more = document.createElement("button");
    more.type = "button";
    more.className = "secondary bounded-more";
    more.textContent = t("trajectory.more", { count: entries.length - windowed.length });
    more.addEventListener("click", () => setSelection({ expanded_branch_refs: [...selection.expanded_branch_refs, "trajectory:all"] }));
    target.append(more, text("p", t("trajectory.moreClaim"), "claim"));
  }
  target.append(text("p", t("trajectory.focusHelp"), "claim"));
}

function renderLifecycle(data, target) {
  const list = document.createElement("div");
  list.className = "timeline";
  for (const item of arrayOrEmpty(data.lifecycle).slice(0, LIFECYCLE.length)) {
    const row = document.createElement("div");
    row.className = "timeline-row";
    row.append(text("div", item.step, "timeline-step"));
    const body = document.createElement("div");
    body.className = "timeline-body";
    body.append(badge(item.state), text("p", item.observation));
    if (!item.observation) body.append(text("p", t("fallback.unavailable")));
    body.append(evidenceList(item.evidence_refs));
    row.append(body);
    list.append(row);
  }
  target.append(list);
}

function renderDag(data, target) {
  const list = document.createElement("div");
  list.className = "dag-list";
  for (const item of arrayOrEmpty(data.dag).slice(0, MAX_TRAJECTORY_ITEMS)) {
    const row = document.createElement("div");
    row.className = "dag-row";
    row.append(text("div", item.id, "dag-id"));
    const body = document.createElement("div");
    body.className = "dag-body";
    body.append(text("strong", item.title || item.id), badge(item.state));
    body.append(text("p", `${item.observation || t("fallback.unavailable")} ${t("label.pressure", { value: item.pressure ?? t("fallback.unknown") })}`));
    row.append(body);
    list.append(row);
  }
  target.append(list);
}

function renderInventory(data, target) {
  const list = document.createElement("div");
  list.className = "inventory";
  for (const item of arrayOrEmpty(data.state_inventory)) {
    const card = document.createElement("div");
    card.className = `inventory-item ${item.category === "lifecycle" ? "lifecycle" : "quality"}`;
    card.append(text("span", statusLabel(item.state), "label"), text("span", item.observed_count, "count"), text("span", item.observation, "note"));
    list.append(card);
  }
  target.append(list);
}

function renderCorrelation(data, target) {
  const correlation = data.correlation || {};
  const identity = document.createElement("div");
  identity.className = "correlation-identity";
  identity.append(text("div", t("label.masterThread", { value: correlation.master_thread_id || t("fallback.missing") }), "mono"));
  identity.append(text("div", t("label.surfaceFreshness", { surface: statusLabel(correlation.state || "missing"), freshness: statusLabel(correlation.freshness || "unknown") }), "mono"));
  identity.append(text("p", correlation.claim_limit || ""));
  // The source label "master-filter current-head evidence" remains visible
  // through the localized summary; it is not translated into authority.
  const currentness = correlation.master_filter?.currentness || {};
  const currentnessDetails = document.createElement("details");
  currentnessDetails.append(text("summary", t("label.masterFilterCurrentHead")));
  const head = currentness.head || {};
  currentnessDetails.append(text("p", t("label.currentness", { state: statusLabel(currentness.state || "unknown"), sequence: head.sequence ?? t("fallback.unknown"), head: head.sha256 || t("fallback.missing") }), "claim"));
  currentnessDetails.append(evidenceList(currentness.evidence_refs));
  if (arrayOrEmpty(currentness.degradation).length) currentnessDetails.append(text("p", t("label.diagnostics", { value: currentness.degradation.join(", ") }), "claim"));
  currentnessDetails.append(text("p", currentness.claim_limit || t("fallback.currentnessClaimLimit"), "claim"));
  identity.append(currentnessDetails);
  target.append(identity);

  const readModel = data.correlation_read_model || {};
  const cursor = readModel.cursor || {};
  const retention = document.createElement("div");
  retention.className = "correlation-identity";
  retention.append(text("div", t("label.goalLocalCursor", { status: statusLabel(readModel.status || "missing") }), "mono"));
  retention.append(text("div", t("label.schemaPositionRebuild", { schema: readModel.schema_version || t("fallback.missing"), position: cursor.position ?? t("fallback.unknown"), rebuild: readModel.rebuild?.mode || t("fallback.unknown") }), "mono"));
  retention.append(text("p", t("label.retainedObservations", { observations: arrayOrEmpty(readModel.observations).length, conflicts: arrayOrEmpty(readModel.conflicts).length, winner: readModel.retention?.winner_selection || t("fallback.unknown") })));
  target.append(retention);

  const envelopes = bounded(correlation.envelopes, MAX_CORRELATION_ENVELOPES);
  for (const envelope of envelopes.items) {
    const card = document.createElement("article");
    card.className = "correlation-card";
    const headBlock = document.createElement("div");
    headBlock.className = "correlation-head";
    const returnId = envelope.return_observation?.return_id || envelope.correlation_id || t("fallback.return");
    headBlock.append(text("strong", t("label.lunaReturn", { value: returnId })), badge(envelope.state || "invalid"));
    card.append(headBlock);
    const chain = document.createElement("div");
    chain.className = "correlation-chain";
    const wake = envelope.wake_observation || {};
    const stages = [
      ["label.goalThread", envelope.goal?.anchor_ref, envelope.goal?.master_thread_id],
      ["label.lunaReturnStage", envelope.return_observation?.ref, envelope.return_observation?.filter_disposition ? statusLabel(envelope.return_observation.filter_disposition) : t("fallback.missing")],
      ["label.wakeAdmission", wake.ref, wake.outcome ? statusLabel(wake.outcome) : t("fallback.outcomeMissing")],
      ["label.acceptedTurn", envelope.accepted_turn?.basis_ref, envelope.accepted_turn?.accepted_turn_id || t("fallback.missing")],
      ["label.masterFilter", envelope.master_filter?.ref, envelope.master_filter?.disposition ? statusLabel(envelope.master_filter.disposition) : t("fallback.missing")],
      ["label.reentry", null, envelope.lifecycle?.reentered?.state ? statusLabel(envelope.lifecycle.reentered.state) : t("fallback.missing")],
    ];
    for (const [labelKey, ref, value] of stages) {
      const stage = document.createElement("div");
      stage.className = "correlation-stage";
      stage.append(text("span", t(labelKey), "correlation-stage-label"), text("strong", value || t("fallback.missing"), "mono"));
      if (ref) stage.append(evidenceList([ref]));
      chain.append(stage);
    }
    card.append(chain);
    const details = document.createElement("details");
    details.append(text("summary", t("label.wakeDetails")));
    details.append(text("p", t("label.wakeFreshness", { source: wake.source_family || t("fallback.unknownSource"), freshness: statusLabel(wake.freshness || "unknown"), missingness: statusLabel(wake.missingness || "unknown") }), "claim"));
    details.append(evidenceList([wake.ref, { label: t("label.rawOwnerReceipt"), kind: wake.source_schema_version || t("fallback.wakeReceipt"), ref: wake.provenance?.raw_owner_ref || wake.ref?.ref, sha256: wake.provenance?.raw_owner_content_sha256 || wake.ref?.sha256, observed_at: wake.observed_at }]));
    const sourceSummary = { source_schema_version: wake.source_schema_version, owner_repo: wake.provenance?.owner_repo, owner_ref: wake.provenance?.owner_ref, contract_ref: wake.provenance?.contract_ref, failure: wake.failure };
    details.append(text("pre", JSON.stringify(sourceSummary, null, 2)));
    card.append(details);
    target.append(card);
  }
  if (envelopes.omitted) target.append(text("p", t("bounded.envelopesOmitted", { count: envelopes.omitted }), "claim"));
  const obligations = arrayOrEmpty(correlation.new_obligations);
  const obligationBlock = document.createElement("div");
  obligationBlock.className = "correlation-obligations";
  obligationBlock.append(text("strong", t("label.newObligations")));
  if (obligations.length) {
    const list = document.createElement("ul");
    for (const obligation of obligations.slice(0, MAX_REFS_PER_ITEM)) {
      const digest = obligation && typeof obligation === "object" ? obligation.sha256 || t("fallback.unavailable") : t("fallback.unavailable");
      const redacted = obligation && typeof obligation === "object" ? obligation.redacted : null;
      list.append(text("li", `${redacted || t("fallback.redactedLegacyObligation")} · sha256:${digest}`));
    }
    obligationBlock.append(list);
  } else obligationBlock.append(text("p", t("label.noNewObligation")));
  target.append(obligationBlock);
}

function renderPressureInbox(data, target) {
  const inbox = data.pressure_inbox || {};
  const summary = document.createElement("div");
  summary.className = "pressure-summary";
  const items = arrayOrEmpty(inbox.items);
  const critical = arrayOrEmpty(inbox.critical_next_routes);
  summary.append(badge(inbox.status || "missing"), text("span", t("pressure.summary", { admitted: items.length, critical: critical.length, legacy: arrayOrEmpty(inbox.legacy_candidates).length }), "mono"));
  target.append(summary);
  const list = document.createElement("div");
  list.className = "pressure-list";
  for (const item of items.slice(0, MAX_PRESSURE_ITEMS)) {
    const card = document.createElement("article");
    card.className = `pressure-card${item.next_route?.critical ? " critical" : ""}`;
    const head = document.createElement("div");
    head.className = "pressure-head";
    head.append(text("strong", item.pressure_ref?.id || t("fallback.pressure")), badge(item.outcome?.state || "invalid"));
    card.append(head, text("p", item.affected_goal_criterion || t("fallback.goalCriterionMissing"), "pressure-criterion"), text("p", t("pressure.ifOmitted", { value: item.consequence_of_omission || t("fallback.consequenceMissing") }), "claim"));
    const route = document.createElement("div");
    route.className = "pressure-route";
    route.append(text("span", item.next_route?.critical ? t("pressure.criticalNextRoute") : t("pressure.nextRoute"), "pressure-route-label"), text("strong", item.next_route?.route || t("fallback.routeMissing")), text("span", t("pressure.routeMeta", { owner: item.next_route?.owner || t("fallback.ownerMissing"), effect: item.next_route?.effect || t("fallback.unknown"), authority: item.next_route?.authority || t("fallback.unknown") }), "mono"));
    card.append(route);
    const details = document.createElement("details");
    details.append(text("summary", t("pressure.details")), text("p", t("pressure.naturalOwner", { owner: item.natural_owner?.owner || t("fallback.missing"), ref: item.natural_owner?.owner_ref || t("fallback.ownerRefMissing") }), "claim"), text("p", t("pressure.trigger", { value: item.recommended_trigger_strength || t("fallback.missing") }), "claim"), text("p", t("pressure.stopLine", { value: item.stop_line || t("fallback.missing") }), "claim"), text("p", t("pressure.wakeCondition", { value: item.wake_condition || t("fallback.missing") }), "claim"), evidenceList(item.evidence), text("pre", boundedJson({ checked_existing_surfaces: item.checked_existing_surfaces, independence_signals: item.independence_signals, outcome: item.outcome }, 1800)), text("p", t("pressure.claimLimit", { value: item.claim_limit || "" }), "claim"));
    card.append(details);
    list.append(card);
  }
  if (items.length > MAX_PRESSURE_ITEMS) list.append(text("p", t("bounded.pressureOmitted", { count: items.length - MAX_PRESSURE_ITEMS }), "claim"));
  for (const candidate of arrayOrEmpty(inbox.legacy_candidates).slice(0, MAX_PRESSURE_ITEMS)) {
    const card = document.createElement("article");
    card.className = "pressure-card legacy";
    card.append(text("strong", candidate.pressure_ref?.id || t("pressure.legacyCandidate")), badge("deferred"), text("p", candidate.legacy_obligation_redacted || t("fallback.legacyObligationRedacted"), "claim"), text("p", t("pressure.sourceDigest", { value: candidate.legacy_obligation_digest || t("fallback.unavailable") }), "mono muted"), text("p", t("pressure.missingFields", { value: arrayOrEmpty(candidate.missing_fields).join(", ") || t("fallback.unknown") }), "claim"));
    list.append(card);
  }
  if (!items.length && !arrayOrEmpty(inbox.legacy_candidates).length) list.append(text("p", t("attention.noPressure"), "claim"));
  target.append(list);
}

function activityGroup(labelKey, group, fields) {
  const block = document.createElement("div");
  block.className = "activity-group";
  const heading = document.createElement("div");
  heading.className = "activity-group-head";
  heading.append(text("strong", t(labelKey)), badge(group?.state || "unknown"));
  block.append(heading);
  for (const [labelKeyForField, key] of fields) {
    const row = document.createElement("div");
    row.className = "activity-field";
    row.append(text("span", t(labelKeyForField), "muted"), text("span", activityValue(group, key), "mono"));
    block.append(row);
  }
  return block;
}

function renderActorActivity(data, target) {
  const activity = data.actor_activity || {};
  const summary = activity.summary || {};
  const intro = document.createElement("div");
  intro.className = "activity-summary";
  intro.append(text("strong", t("activity.observed", { count: summary.actor_count == null ? statusLabel("unknown") : summary.actor_count })), badge(activity.state || "unknown"), text("p", activity.observation || t("fallback.actorActivityUnavailable")));
  target.append(intro);
  const actors = arrayOrEmpty(activity.actors);
  if (!actors.length) {
    target.append(text("p", t("fallback.noActorEnvelope"), "claim"));
    return;
  }
  const windowed = bounded(actors, MAX_ACTOR_CARDS, selection.focus_ref);
  target.append(text("p", t("participants.bounded", { shown: windowed.items.length, total: windowed.total }), "claim"));
  for (const actor of windowed.items) {
    const card = document.createElement("article");
    card.className = "actor-card";
    const head = document.createElement("div");
    head.className = "actor-head";
    const title = document.createElement("div");
    title.append(text("strong", actor.identity?.label || actor.actor_id || actor.actor_key || t("fallback.actorIdentityUnknown")), text("div", actor.actor_key || t("fallback.actorKeyUnknown"), "mono muted"));
    head.append(title, badge(actor.state || "unknown"));
    card.append(head);
    const grid = document.createElement("div");
    grid.className = "activity-grid";
    grid.append(activityGroup("activity.identity", actor.identity, [["activity.actorId", "actor_id"], ["activity.incarnation", "incarnation_id"], ["activity.role", "role_id"], ["activity.model", "model_id"]]));
    grid.append(activityGroup("activity.assignment", actor.task, [["activity.task", "task_id"], ["activity.state", "state"]]));
    grid.append(activityGroup("activity.responsibility", actor.responsibility, [["activity.state", "responsibility_state"], ["activity.holder", "holder"], ["activity.mandate", "mandate_id"], ["activity.obligation", "obligation_id"]]));
    grid.append(activityGroup("activity.process", actor.process, [["activity.processId", "process_id"], ["activity.posture", "posture"]]));
    grid.append(activityGroup("activity.session", actor.session, [["activity.sessionId", "session_id"], ["activity.posture", "posture"]]));
    grid.append(activityGroup("activity.terminal", actor.terminal, [["activity.terminalId", "terminal_id"], ["activity.posture", "posture"], ["activity.exitCode", "exit_code"]]));
    grid.append(activityGroup("activity.usage", actor.usage, [["activity.evidenceStatus", "observation_status"], ["activity.inputTokens", "input_tokens"], ["activity.outputTokens", "output_tokens"], ["activity.totalTokens", "total_tokens"], ["activity.toolCalls", "tool_calls"], ["activity.durationSeconds", "duration_seconds"]]));
    card.append(grid);
    const wakeReturn = document.createElement("div");
    wakeReturn.className = "activity-return";
    wakeReturn.append(text("strong", t("activity.wakeReturn")), badge(actor.wake_return?.return_state || "unknown"), text("span", t("activity.wakeReentryAccepted", { wake: activityValue(actor.wake_return, "wake_state"), reentry: activityValue(actor.wake_return, "reentry_state"), turn: activityValue(actor.wake_return, "accepted_turn_id") }), "mono"));
    card.append(wakeReturn);
    const details = document.createElement("details");
    details.append(text("summary", t("activity.technicalDetails")), evidenceList(actor.evidence_refs), text("pre", boundedJson({ incarnation: actor.identity?.incarnation_id, model: actor.identity?.model_id || actor.model, task: actor.task, process: actor.process, session: actor.session, terminal: actor.terminal, usage: actor.usage, provenance: actor.provenance }, 2600)));
    card.append(details, text("p", actor.claim_limit || "", "claim"));
    target.append(card);
  }
  if (windowed.omitted) target.append(text("p", t("participants.more", { count: windowed.omitted }), "claim"));
}

function renderSources(data, target) {
  const sources = bounded(data.sources, MAX_SOURCE_CARDS);
  const grid = document.createElement("div");
  grid.className = "source-grid";
  for (const item of sources.items) {
    const card = document.createElement("article");
    card.className = "source-card";
    const head = document.createElement("div");
    head.className = "source-head";
    head.append(text("strong", item.id), badge(item.state || "unknown"));
    card.append(head, text("div", item.owner || t("fallback.ownerMissing"), "source-owner"), text("p", item.observation || t("fallback.unavailable")));
    const freshness = document.createElement("div");
    freshness.append(text("span", t("sources.freshness"), "muted"), badge(item.freshness || "unknown"));
    card.append(freshness);
    const details = document.createElement("details");
    details.append(text("summary", t("sources.metadataEvidence")), evidenceList(item.evidence_refs), text("pre", boundedJson(item.metadata || {}, 2000)), text("p", t("sources.claimLimit", { value: item.claim_limit || "" }), "claim"));
    card.append(details);
    grid.append(card);
  }
  if (!sources.items.length) grid.append(text("p", t("evidence.noSources"), "claim"));
  target.append(grid);
  if (sources.omitted) target.append(text("p", t("bounded.sourcesOmitted", { count: sources.omitted }), "claim"));
}

function renderOwners(data, target) {
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrap";
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.textContent = t("evidence.ownerMap");
  table.append(caption);
  const head = document.createElement("thead");
  const row = document.createElement("tr");
  for (const key of ["table.owner", "table.authority", "table.source", "table.observedBinding", "table.kag"]) {
    const cell = text("th", t(key));
    cell.scope = "col";
    row.append(cell);
  }
  head.append(row);
  table.append(head);
  const body = document.createElement("tbody");
  for (const item of arrayOrEmpty(data.owner_surfaces).slice(0, MAX_OWNER_ROWS)) {
    const rowNode = document.createElement("tr");
    rowNode.append(text("td", item.owner || t("fallback.ownerMissing")), text("td", item.authority || t("fallback.unknown")), text("td", item.source_path || t("fallback.unavailable"), "mono"));
    const observed = document.createElement("td");
    const snapshot = item.source_snapshot || {};
    observed.append(badge(snapshot.state || "unknown"));
    if (snapshot.head) observed.append(text("div", t("owners.snapshot", { branch: snapshot.branch || t("fallback.detached"), head: snapshot.head.slice(0, 12), dirty: ` · ${snapshot.dirty ? statusLabel("dirty") : statusLabel("clean")}` }), "mono"));
    if (item.runtime_snapshot) observed.append(text("div", t("owners.runtime", { value: statusLabel(item.runtime_snapshot.state || "unknown") }), "mono"));
    rowNode.append(observed, text("td", statusLabel(item.kag_snapshot_state || "unknown")));
    body.append(rowNode);
  }
  table.append(body);
  wrapper.append(table);
  target.append(wrapper);
  if (arrayOrEmpty(data.owner_surfaces).length > MAX_OWNER_ROWS) target.append(text("p", t("bounded.ownersOmitted", { count: arrayOrEmpty(data.owner_surfaces).length - MAX_OWNER_ROWS }), "claim"));
}

function renderRecords(data, target) {
  const annotations = data.annotations || { count: 0 };
  const intents = data.action_intents || { count: 0 };
  const grid = document.createElement("div");
  grid.className = "records-grid";
  const recordBlock = (headingKey, summary, countKey, recordKey) => {
    const block = document.createElement("article");
    block.className = "record-card";
    block.append(text("h4", t(headingKey)), text("strong", t(countKey, { count: summary.count ?? 0 })));
    const latest = arrayOrEmpty(summary.latest);
    if (latest.length) {
      for (const item of latest.slice(-3).reverse()) block.append(text("p", t("records.latest", { created: item.created_at || t("fallback.record"), target: item.target_ref || t("fallback.target") }), "mono"));
    } else block.append(text("p", t("records.empty"), "claim"));
    block.append(text("p", t(recordKey), "claim"));
    return block;
  };
  grid.append(recordBlock("records.annotations", annotations, "records.annotationCount", "annotations.claim"), recordBlock("records.intents", intents, "records.intentCount", "actionIntents.suffix"));
  target.append(grid);
}

function renderLimits(data, target) {
  const details = document.createElement("details");
  details.className = "claim-details";
  details.append(text("summary", t("claimLimits.heading")));
  const list = document.createElement("ul");
  for (const item of arrayOrEmpty(data.claim_limits).slice(0, MAX_REFS_PER_ITEM * 2)) list.append(text("li", item));
  details.append(list);
  target.append(details);
}

function renderTrajectoryLens(data, target) {
  const panel = createPanel("section.currentCorrelation", "lens.trajectoryHeading", "lens.trajectoryClaim");
  renderTrajectoryItems(data, panel.body);
  target.append(panel.panel);
  const lifecycle = createPanel("section.goalLifecycle", "goalLifecycle.heading", "workspace.claim");
  renderLifecycle(data, lifecycle.body);
  target.append(lifecycle.panel);
  const dag = createPanel("section.openDag", "openDag.heading", "lens.trajectoryClaim");
  renderDag(data, dag.body);
  target.append(dag.panel);
}

function renderAttentionLens(data, target) {
  const panel = createPanel("section.pressureInbox", "lens.attentionHeading", "lens.attentionClaim");
  renderPressureInbox(data, panel.body);
  target.append(panel.panel);
  const quality = createPanel("section.statusVocabulary", "statusVocabulary.heading", "statusVocabulary.claim");
  renderInventory(data, quality.body);
  target.append(quality.panel);
  const correlation = createPanel("section.currentCorrelation", "evidence.correlation", "currentCorrelation.claim");
  renderCorrelation(data, correlation.body);
  target.append(correlation.panel);
}

function renderParticipantsLens(data, target) {
  const panel = createPanel("section.liveActivity", "lens.participantsHeading", "lens.participantsClaim");
  renderActorActivity(data, panel.body);
  target.append(panel.panel);
}

function renderEvidenceLens(data, target) {
  const source = createPanel("section.sourceProvenance", "lens.evidenceHeading", "lens.evidenceClaim");
  renderSources(data, source.body);
  target.append(source.panel);
  const owners = createPanel("section.ownerMap", "evidence.ownerMap", "sourceProvenance.claim");
  renderOwners(data, owners.body);
  target.append(owners.panel);
  const correlation = createPanel("section.currentCorrelation", "evidence.correlation", "currentCorrelation.claim");
  renderCorrelation(data, correlation.body);
  target.append(correlation.panel);
}

function renderRecordsLens(data, target) {
  const panel = createPanel("section.annotations", "lens.recordsHeading", "lens.recordsClaim");
  renderRecords(data, panel.body);
  target.append(panel.panel);
  const limits = createPanel("section.claimLimits", "claimLimits.heading", "workspace.claim");
  renderLimits(data, limits.body);
  target.append(limits.panel);
}

function renderLens(data) {
  const target = byId("lens-surface");
  clear(target);
  if (!target) return;
  const heading = text("p", `${t(`lens.${selection.lens}`)} · ${goalTitle(data)}`, "lens-current-label");
  target.append(heading);
  if (selection.lens === "attention") renderAttentionLens(data, target);
  else if (selection.lens === "participants") renderParticipantsLens(data, target);
  else if (selection.lens === "evidence") renderEvidenceLens(data, target);
  else if (selection.lens === "records") renderRecordsLens(data, target);
  else renderTrajectoryLens(data, target);
}

function renderThread(data) {
  const target = byId("thread-items");
  clear(target);
  const quality = byId("thread-quality");
  setBadge(quality, data?.thread_projection?.state || "missing");
  const selected = selection.thread_ref || selection.focus_ref || selection.goal_ref;
  const selectionLabel = byId("thread-selection");
  if (selectionLabel) selectionLabel.textContent = selected ? t("thread.selection", { value: selected }) : t("thread.noSelection");
  if (!selected) {
    target.append(text("p", t("thread.noSelection"), "empty-state"));
  } else {
    const metadata = document.createElement("article");
    metadata.className = "thread-item thread-unavailable";
    metadata.append(text("strong", t("thread.metadataOnly")), text("p", t("thread.unavailable"), "claim"), text("p", t("thread.rawUnavailable"), "claim"));
    target.append(metadata);
    const correlation = data.correlation || {};
    const envelopes = arrayOrEmpty(correlation.envelopes);
    const envelope = envelopes.find((candidate) => `return:${candidate.return_observation?.return_id || candidate.correlation_id}` === selection.focus_ref) || envelopes[0];
    if (envelope) {
      const ret = document.createElement("article");
      ret.className = "thread-item";
      ret.append(text("strong", t("thread.returnItem")), badge(envelope.state || "invalid"), text("p", envelope.return_observation?.filter_disposition ? statusLabel(envelope.return_observation.filter_disposition) : t("fallback.missing"), "claim"), evidenceList([envelope.return_observation?.ref, envelope.accepted_turn?.basis_ref]));
      target.append(ret);
      const wake = envelope.wake_observation || {};
      const wakeItem = document.createElement("article");
      wakeItem.className = "thread-item";
      wakeItem.append(text("strong", t("thread.wakeItem")), badge(wake.outcome || "missing"), text("p", t("label.wakeFreshness", { source: wake.source_family || t("fallback.unknownSource"), freshness: statusLabel(wake.freshness || "unknown"), missingness: statusLabel(wake.missingness || "unknown") }), "claim"), evidenceList([wake.ref]));
      target.append(wakeItem);
    }
    const annotations = arrayOrEmpty(data.annotations?.latest).filter((item) => !item.target_ref || item.target_ref === selected || item.target_ref === selection.goal_ref);
    for (const item of annotations.slice(-4).reverse()) {
      const card = document.createElement("article");
      card.className = "thread-item";
      card.append(text("strong", t("thread.annotationItem")), text("p", item.body || t("fallback.unavailable")), text("p", `${item.author_ref || t("fallback.unknown")} · ${item.created_at || t("fallback.unknown")}`, "mono muted"), text("p", t("thread.claimLimit"), "claim"));
      target.append(card);
    }
    const intents = arrayOrEmpty(data.action_intents?.latest).filter((item) => !item.target_ref || item.target_ref === selected || item.target_ref === selection.goal_ref);
    for (const item of intents.slice(-4).reverse()) {
      const card = document.createElement("article");
      card.className = "thread-item";
      card.append(text("strong", t("thread.intentItem")), badge(item.state || "deferred"), text("p", item.summary || t("fallback.unavailable")), text("p", `${item.owner_route || t("fallback.ownerMissing")} · effect:${item.effect || "none"}`, "mono muted"), text("p", t("thread.claimLimit"), "claim"));
      target.append(card);
    }
  }
  const operate = byId("operate-panel");
  if (operate) operate.classList.toggle("hidden", workspaceMode !== "operate");
  const routeCard = byId("operate-route-card");
  if (routeCard) {
    clear(routeCard);
    const route = arrayOrEmpty(data.pressure_inbox?.items).find((item) => item.next_route?.critical) || arrayOrEmpty(data.pressure_inbox?.items)[0];
    const owner = route?.next_route?.owner || route?.natural_owner?.owner;
    const stopLine = route?.stop_line;
    const returnRoute = route?.wake_condition;
    routeCard.className = `operate-route-card ${owner && stopLine ? "route-ready" : "route-missing"}`;
    routeCard.append(text("strong", owner && stopLine ? t("operate.routeReady") : t("operate.routeMissing")), text("span", t("operate.target", { value: selected || t("fallback.missing") }), "mono"), text("span", t("operate.owner", { value: owner || t("fallback.ownerMissing") }), "mono"), text("span", t("operate.stopLine", { value: stopLine || t("fallback.missing") }), "mono"), text("span", t("operate.returnRoute", { value: returnRoute || t("fallback.missing") }), "mono"), text("span", t("operate.effectCeiling"), "mono"));
  }
  setFormTargets(selected || selection.goal_ref || "goal:unknown");
}

function setFormTargets(targetRef) {
  for (const form of [byId("annotation-form"), byId("intent-form")]) {
    const input = form?.querySelector?.('input[name="target_ref"]');
    if (input) input.value = targetRef;
  }
}

function renderProjection(data) {
  renderRefreshState();
  renderHeader(data);
  renderHome(data);
  const hasGoal = Boolean(goalRef(data));
  const workspace = byId("workspace-view");
  const home = byId("home-view");
  const selectedCurrentGoal = hasGoal && selection.goal_ref === goalRef(data);
  if (workspace) workspace.classList.toggle("hidden", !selectedCurrentGoal);
  if (home) home.classList.toggle("hidden", selectedCurrentGoal);
  const fallback = byId("fallback-evidence");
  if (fallback) fallback.classList.add("hidden");
  if (!selectedCurrentGoal) return;
  renderBreadcrumb(data);
  renderGoalSummary(data);
  renderAttentionStrip(data);
  renderRailQuality(data);
  renderLens(data);
  renderThread(data);
  updateLensButtons();
  updateModeButtons();
  const center = byId("center-surface");
  if (center) center.setAttribute("aria-busy", refreshState === "loading" ? "true" : "false");
}

function knownFocusRefs(data) {
  return new Set([
    ...arrayOrEmpty(data.dag).map((item) => `dag:${item.id}`),
    ...arrayOrEmpty(data.lifecycle).map((item) => `lifecycle:${item.step}`),
    ...arrayOrEmpty(data.correlation?.envelopes).map((item) => `return:${item.return_observation?.return_id || item.correlation_id || t("fallback.return")}`),
    ...arrayOrEmpty(data.pressure_inbox?.items).map((item) => `pressure:${item.pressure_ref?.id || item.pressure_ref?.ref || t("fallback.pressure")}`),
  ]);
}

function renderNoProjection() {
  renderRefreshState();
  const workspace = byId("workspace-view");
  const home = byId("home-view");
  if (workspace) workspace.classList.add("hidden");
  if (home) home.classList.remove("hidden");
  clear(byId("goal-selector"));
  const catalog = byId("catalog-state");
  if (catalog) {
    catalog.className = "empty-state state-invalid";
    catalog.append(badge("invalid"), text("span", t("refresh.disconnected")));
  }
}

async function refresh() {
  if (!currentProjection) {
    refreshState = "loading";
    renderRefreshState();
  }
  try {
    const response = await fetch("/api/projection", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || t("error.projectionRequestFailed"));
    const wasDegraded = refreshState !== "current";
    currentProjection = data;
    lastGoodProjection = data;
    lastGoodAt = data.generated_at || new Date().toISOString();
    refreshState = "current";
    if (selection.goal_ref && selection.goal_ref !== goalRef(data)) selectionQuality = "missing";
    else if (selection.focus_ref && !knownFocusRefs(data).has(selection.focus_ref)) selectionQuality = "stale";
    else if (!selectionQuality || selectionQuality === "missing" || selectionQuality === "stale") selectionQuality = null;
    selection.observation_cursor_or_generation = data.generated_at || null;
    renderProjection(data);
    if (wasDegraded) announce(t("refresh.updated"));
  } catch (error) {
    const alert = byId("alert");
    if (alert) {
      alert.textContent = t("error.projectionUnavailable", { error: error.message });
      alert.classList.remove("hidden");
    }
    if (lastGoodProjection) refreshState = "stale";
    else refreshState = "disconnected";
    currentProjection = lastGoodProjection;
    if (currentProjection) renderProjection(currentProjection);
    else renderNoProjection();
    const connection = byId("connection");
    if (connection) {
      connection.textContent = t("connection.projectionUnavailable");
      connection.className = `badge state-${refreshState === "stale" ? "stale" : "invalid"}`;
    }
    announce(t("refresh.failed", { value: error.message }));
  }
}

async function submitForm(event, route, form) {
  event.preventDefault();
  if (form.dataset.submitting === "true") return;
  form.dataset.submitting = "true";
  const button = form.querySelector('button[type="submit"]');
  const status = form.querySelector("[data-form-status]");
  const original = button?.textContent;
  if (button) { button.disabled = true; button.textContent = t("form.submitPending"); }
  if (status) status.textContent = "";
  try {
    const body = Object.fromEntries(new FormData(form).entries());
    const response = await fetch(route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || t("error.writeFailed"));
    form.reset();
    if (status) status.textContent = t("form.submitSuccess");
    await refresh();
  } catch (error) {
    if (status) status.textContent = t("form.submitFailed", { value: error.message });
    const alert = byId("alert");
    if (alert) { alert.textContent = error.message; alert.classList.remove("hidden"); }
  } finally {
    form.dataset.submitting = "false";
    if (button) { button.disabled = false; button.textContent = original || t("form.recordAnnotation"); }
  }
}

for (const button of document.querySelectorAll("[data-language]")) button.addEventListener("click", () => i18n.setLanguage(button.dataset.language));
for (const button of document.querySelectorAll("[data-lens]")) button.addEventListener("click", () => setSelection({ lens: button.dataset.lens }));
for (const button of document.querySelectorAll("[data-mode]")) button.addEventListener("click", () => { workspaceMode = button.dataset.mode === "operate" ? "operate" : "observe"; updateModeButtons(); if (currentProjection) renderThread(currentProjection); });
byId("home-button")?.addEventListener("click", () => setSelection({ goal_ref: null, focus_ref: null, branch_path: [], thread_ref: null }));
byId("workspace-goal-button")?.addEventListener("click", () => setSelection({ lens: "trajectory" }));
byId("thread-toggle")?.addEventListener("click", () => {
  contextThreadOpen = !contextThreadOpen;
  const thread = byId("context-thread");
  if (thread) thread.classList.toggle("collapsed", !contextThreadOpen);
  const toggle = byId("thread-toggle");
  if (toggle) toggle.setAttribute("aria-expanded", String(contextThreadOpen));
});
i18n.subscribe(() => {
  applyStaticTranslations();
  if (currentProjection) renderProjection(currentProjection);
  publishNativePresentationPreference();
});
window.AoaDashboardTheme?.subscribe?.(publishNativePresentationPreference);
if (window.addEventListener) window.addEventListener("hashchange", () => { readRoute(); if (currentProjection) renderProjection(currentProjection); });
readRoute();
applyStaticTranslations();
publishNativePresentationPreference();

byId("annotation-form")?.addEventListener("submit", (event) => submitForm(event, "/api/annotations", event.currentTarget));
byId("intent-form")?.addEventListener("submit", (event) => submitForm(event, "/api/action-intents", event.currentTarget));

refresh();
setInterval(refresh, 5000);
