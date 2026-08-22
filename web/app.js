const { createI18n } = window.AoaDashboardI18n;
const i18n = createI18n();

const dashboardUI = window.AoaDashboardUiState || {
  LENSES: ["trajectory", "attention", "participants", "evidence", "records"],
  SelectionContext: {
    fields: ["goal_ref", "lens", "focus_ref", "branch_path", "thread_ref", "expanded_branch_refs", "page_by_list", "observation_cursor_or_generation"],
    empty() {
      return { goal_ref: null, lens: "trajectory", focus_ref: null, branch_path: [], thread_ref: null, expanded_branch_refs: [], page_by_list: {}, observation_cursor_or_generation: null };
    },
    normalize(value) { return { ...this.empty(), ...(value || {}) }; },
  },
  encodeRoute(value) { return value?.goal_ref ? `#goal/${encodeURIComponent(value.goal_ref)}/${value.lens || "trajectory"}` : "#"; },
  decodeRoute() { return { status: "home", error: null, selection: this.SelectionContext.empty() }; },
  pageWindow(items, page, pageSize) {
    const values = Array.isArray(items) ? items : [];
    const size = pageSize > 0 ? pageSize : 1;
    const current = Math.min(Math.max(Number(page) || 0, 0), Math.max(0, Math.ceil(values.length / size) - 1));
    return { items: values.slice(current * size, (current + 1) * size), page: current, pageCount: Math.max(1, Math.ceil(values.length / size)), total: values.length, omitted: Math.max(0, values.length - size), hasPrevious: current > 0, hasNext: (current + 1) * size < values.length };
  },
  qualifiedCatalog() { return { state: "missing", items: [], source: null, currentness: "missing", claim_limit: null }; },
  optionalRecord(value) { return value && typeof value === "object" ? value : { state: "missing", count: null, latest: [], evidence_refs: [], claim_limit: null }; },
};

const LIFECYCLE = [
  "planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "wake requested", "reentered",
];
const QUALITY = ["missing", "unknown", "stale", "deferred", "invalid"];
const LENSES = dashboardUI.LENSES;
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
const ADMITTED_ROUTE_CURRENTNESS = new Set(["current", "current_at_read"]);
const SelectionContext = dashboardUI.SelectionContext;

let currentProjection = null;
let lastGoodProjection = null;
let refreshState = "loading";
let lastGoodAt = null;
let lastAnnouncement = "";
let workspaceMode = "observe";
let contextThreadOpen = true;
let selectionQuality = null;
let selection = SelectionContext.empty();
let routeState = "home";
let routeError = null;
let interactionState = null;
let refreshInFlight = false;

const byId = (id) => document.getElementById(id);
const clear = (element) => { if (element) while (element.firstChild) element.removeChild(element.firstChild); };
const t = (key, variables = {}) => i18n.t(key, variables);
const statusLabel = (value) => i18n.status(value);
const arrayOrEmpty = (value) => Array.isArray(value) ? value : [];
const plural = (key, count, variables = {}) => i18n.plural
  ? i18n.plural(`plural.${key}`, count, variables)
  : t(`bounded.${key}`, { ...variables, count });
const catalogInfo = (data) => dashboardUI.qualifiedCatalog(data?.goal_catalog);
const recordInfo = (data, key) => dashboardUI.optionalRecord(data?.[key]);

function stableKey(value, fallback = "unknown") {
  const textValue = String(value || fallback);
  return textValue.replace(/[^a-zA-Z0-9_.:#/-]+/g, "_").slice(0, 180) || fallback;
}

function detailRef(kind, value) {
  return `detail:${kind}:${stableKey(value)}`;
}

function pageFor(listKey) {
  return Number.isInteger(selection.page_by_list?.[listKey]) ? selection.page_by_list[listKey] : 0;
}

function setPage(listKey, page) {
  setSelection({ page_by_list: { ...selection.page_by_list, [listKey]: Math.max(0, Number(page) || 0) } });
}

function showPageControls(target, listKey, windowed) {
  if (!target || windowed.pageCount <= 1) return;
  const controls = document.createElement("nav");
  controls.className = "bounded-pager";
  controls.setAttribute("aria-label", t("bounded.pageLabel"));
  const previous = document.createElement("button");
  previous.type = "button";
  previous.className = "secondary";
  previous.textContent = t("bounded.previousPage");
  previous.disabled = !windowed.hasPrevious;
  previous.setAttribute("data-focus-key", `pager:${listKey}:previous`);
  previous.addEventListener("click", () => setPage(listKey, windowed.page - 1));
  const next = document.createElement("button");
  next.type = "button";
  next.className = "secondary";
  next.textContent = t("bounded.nextPage");
  next.disabled = !windowed.hasNext;
  next.setAttribute("data-focus-key", `pager:${listKey}:next`);
  next.addEventListener("click", () => setPage(listKey, windowed.page + 1));
  controls.append(previous, text("span", t("bounded.pageStatus", { page: windowed.page + 1, pages: windowed.pageCount, total: windowed.total }), "mono"), next);
  target.append(controls);
}

function selectDetail(ref, listKey, page) {
  const pages = { ...selection.page_by_list };
  if (listKey !== undefined) pages[listKey] = page;
  setSelection({ focus_ref: ref, thread_ref: ref, branch_path: [ref], page_by_list: pages });
}

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

function renderRouteState() {
  const target = byId("route-status");
  if (!target) return;
  clear(target);
  if (routeState === "invalid") {
    target.className = "route-status state-invalid";
    target.append(badge("invalid"), text("span", t("route.invalid")), text("code", routeError || t("fallback.unavailable")));
  } else {
    target.className = "route-status hidden";
  }
}

function captureInteractionState() {
  const snapshot = {
    details: {},
    scroll: {},
    drafts: {},
    focusKey: null,
    threadOpen: contextThreadOpen,
  };
  for (const node of document.querySelectorAll("details")) {
    const key = node.dataset.detailKey;
    if (key) snapshot.details[key] = Boolean(node.open);
  }
  for (const id of ["center-surface", "lens-surface", "context-thread"]) {
    const node = byId(id);
    if (node) snapshot.scroll[id] = { top: node.scrollTop || 0, left: node.scrollLeft || 0 };
  }
  const active = document.activeElement;
  if (active) snapshot.focusKey = active.dataset?.focusKey || active.id || null;
  for (const form of [byId("annotation-form"), byId("intent-form")]) {
    if (!form?.id) continue;
    const values = {};
    for (const control of Array.from(form.elements || [])) {
      if (!control.name) continue;
      values[control.name] = control.type === "checkbox" || control.type === "radio"
        ? { checked: Boolean(control.checked) }
        : { value: control.value };
    }
    snapshot.drafts[form.id] = values;
  }
  return snapshot;
}

function restoreInteractionState(snapshot = interactionState) {
  if (!snapshot) return;
  contextThreadOpen = snapshot.threadOpen !== false;
  const thread = byId("context-thread");
  if (thread) thread.classList.toggle("collapsed", !contextThreadOpen);
  const toggle = byId("thread-toggle");
  if (toggle) toggle.setAttribute("aria-expanded", String(contextThreadOpen));
  for (const node of document.querySelectorAll("details")) {
    const key = node.dataset.detailKey;
    if (key && Object.prototype.hasOwnProperty.call(snapshot.details, key)) node.open = snapshot.details[key];
  }
  for (const [id, position] of Object.entries(snapshot.scroll || {})) {
    const node = byId(id);
    if (node) {
      node.scrollTop = position.top;
      node.scrollLeft = position.left;
    }
  }
  for (const [formId, values] of Object.entries(snapshot.drafts || {})) {
    const form = byId(formId);
    if (!form) continue;
    for (const control of Array.from(form.elements || [])) {
      const saved = values[control.name];
      if (!control.name || !saved) continue;
      if (control.type === "checkbox" || control.type === "radio") control.checked = saved.checked;
      else if (saved.value !== undefined) control.value = saved.value;
    }
  }
  if (snapshot.focusKey) {
    const focus = Array.from(document.querySelectorAll("[data-focus-key]"))
      .find((node) => node.dataset.focusKey === snapshot.focusKey) || byId(snapshot.focusKey);
    if (focus?.focus) focus.focus({ preventScroll: true });
  }
}

function clearAlert() {
  const alert = byId("alert");
  if (!alert) return;
  alert.textContent = "";
  alert.classList.add("hidden");
}

function setProjectionBusy(value) {
  refreshInFlight = Boolean(value);
  for (const id of ["center-surface", "workspace-view"]) {
    const node = byId(id);
    if (node?.setAttribute) node.setAttribute("aria-busy", refreshInFlight ? "true" : "false");
  }
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
  if (values.length > limit) list.append(text("p", plural("reference", values.length - limit), "claim"));
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
  if (!window.history || !window.location) return;
  const hash = dashboardUI.encodeRoute(selection);
  try { window.history.replaceState(null, "", hash); } catch (_error) { /* a native WebView may not expose history */ }
}

function readRoute() {
  const raw = window.location?.hash || "";
  const route = dashboardUI.decodeRoute(raw);
  routeState = route.status || "invalid";
  routeError = route.error || null;
  selection = SelectionContext.normalize ? SelectionContext.normalize(route.selection) : route.selection;
}

function setSelection(patch) {
  selection = SelectionContext.normalize ? SelectionContext.normalize({ ...selection, ...patch }) : { ...selection, ...patch };
  if (Object.prototype.hasOwnProperty.call(patch, "goal_ref") && !patch.goal_ref) selectionQuality = null;
  if (Object.prototype.hasOwnProperty.call(patch, "focus_ref")) selectionQuality = null;
  routeState = selection.goal_ref ? "valid" : "home";
  routeError = null;
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
  const quality = selectionQuality === "missing" ? "missing" : selectionQuality === "stale" ? "stale" : qualityForData(data);
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
    if (selection.goal_ref) selector.append(text("p", t("selection.missing"), "claim"), text("code", selection.goal_ref, "mono"));
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

  const catalog = catalogInfo(data);
  catalogState.className = `empty-state state-${catalog.state === "bound" ? "bound" : catalog.state === "admitted-empty" ? "deferred" : "missing"}`;
  catalogState.append(badge(catalog.state === "bound" ? "bound" : catalog.state === "admitted-empty" ? "deferred" : "missing"));
  catalogState.append(text("span", catalog.state === "bound" ? t("home.catalogReady") : catalog.state === "admitted-empty" ? t("home.catalogEmpty") : t("home.catalogMissing")));
  if (catalog.state === "missing") catalogState.append(text("span", t("home.categoryLimit"), "claim"));
  if (catalog.state !== "missing") {
    catalogState.append(text("span", t("home.catalogSource", { value: catalog.source.ref || t("fallback.missing") }), "mono"));
    catalogState.append(text("span", t("home.catalogCurrentness", { value: statusLabel(catalog.currentness) }), "mono"));
    catalogState.append(text("span", catalog.claim_limit, "claim"));
  }
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
  details.dataset.detailKey = "workspace:summary";
  const summary = document.createElement("summary");
  summary.append(text("strong", goal.title || t("goal.unnamed")), badge(goal.state || "unknown"), badge(qualityForData(data)));
  details.append(summary);
  details.append(text("p", t("workspace.goalId", { value: goal.goal_id || t("fallback.missing") }), "mono"));
  details.append(text("p", t("workspace.currentness", { value: statusLabel(currentnessForData(data)) }), "mono"));
  details.append(text("p", t("workspace.digest", { value: goal.anchor_digest || t("fallback.missing") }), "mono"));
  const catalog = catalogInfo(data);
  details.append(text("p", t("workspace.historyLimit", { value: catalog.state === "bound" ? t("home.catalogReady") : catalog.state === "admitted-empty" ? t("home.catalogEmpty") : t("home.catalogMissing") }), "claim"));
  if (catalog.state !== "missing") {
    details.append(text("p", t("home.catalogSource", { value: catalog.source.ref || t("fallback.missing") }), "mono"));
    details.append(text("p", t("home.catalogCurrentness", { value: statusLabel(catalog.currentness) }), "mono"));
    details.append(text("p", catalog.claim_limit, "claim"));
  }
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
  const critical = arrayOrEmpty(inbox.items)
    .filter((item) => item.next_route?.critical && routeMatchesSelection(item))
    .map((item) => ({ ...item.next_route, pressure_ref: item.pressure_ref, goal_id: item.goal_id, claim_limit: item.claim_limit }));
  const items = arrayOrEmpty(inbox.items);
  const head = document.createElement("div");
  head.className = "attention-head";
  head.append(text("div", t("lens.attention"), "section-kicker"), badge(inbox.status || "missing"));
  target.append(head);
  const summary = document.createElement("div");
  summary.className = "attention-summary";
  summary.append(text("strong", `${plural("admitted", items.length)} · ${plural("critical", critical.length)} · ${plural("legacy", arrayOrEmpty(inbox.legacy_candidates).length)}`));
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
  const windowed = dashboardUI.pageWindow(entries, pageFor("trajectory"), MAX_TRAJECTORY_ITEMS, selection.focus_ref);
  const list = document.createElement("div");
  list.className = "trajectory-list";
  for (const item of windowed.items) {
    const card = document.createElement("article");
    card.className = `trajectory-card${selection.focus_ref === item.ref ? " selected" : ""}`;
    const head = document.createElement("div");
    head.className = "trajectory-card-head";
    const select = document.createElement("button");
    select.type = "button";
    select.className = "trajectory-select";
    select.setAttribute("aria-pressed", String(selection.focus_ref === item.ref));
    select.setAttribute("data-focus-key", item.ref);
    select.setAttribute("aria-label", t("trajectory.select", { value: item.label }));
    select.append(text("strong", item.label), text("span", t("trajectory.item"), "mono muted"));
    select.addEventListener("click", () => {
      setSelection({ focus_ref: item.ref, thread_ref: item.ref, branch_path: [item.ref], page_by_list: { ...selection.page_by_list, trajectory: windowed.page } });
      announce(`${t("trajectory.selected")}: ${item.label}`);
    });
    head.append(select, badge(item.state || "unknown"));
    card.append(head);
    card.append(text("p", item.observation || t("fallback.unavailable"), "claim"));
    const details = document.createElement("details");
    details.dataset.detailKey = item.ref;
    details.open = selection.focus_ref === item.ref;
    details.append(text("summary", t("evidence.metadata")));
    details.append(evidenceList(item.evidence_refs));
    details.append(text("pre", boundedJson(item.detail, 1800)));
    card.append(details);
    list.append(card);
  }
  target.append(list);
  showPageControls(target, "trajectory", windowed);
  if (windowed.omitted) target.append(text("p", plural("trajectory", windowed.total - windowed.items.length), "claim"), text("p", t("trajectory.moreClaim"), "claim"));
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

function sourceRefsFrom(value, limit = MAX_REFS_PER_ITEM) {
  const refs = [];
  const seen = new Set();
  function visit(item) {
    if (refs.length >= limit || item == null) return;
    if (Array.isArray(item)) {
      for (const child of item) visit(child);
      return;
    }
    if (typeof item !== "object") return;
    if (typeof item.ref === "string" && item.ref) {
      const key = `${item.kind || "ref"}:${item.ref}:${item.sha256 || ""}`;
      if (!seen.has(key)) {
        seen.add(key);
        refs.push(item);
      }
    }
    for (const [key, child] of Object.entries(item)) {
      if (["claim_limit", "observation", "body", "raw", "text"].includes(key)) continue;
      visit(child);
    }
  }
  visit(value);
  return refs;
}

function diagnosticEntries(data) {
  const entries = [];
  const firstPopulated = (...values) => values.find((value) => {
    if (Array.isArray(value)) return value.length > 0;
    return value !== null && value !== undefined && value !== "";
  }) ?? null;
  const add = (kind, label, value, claimLimit, fallbackEvidence = []) => {
    if (value == null) return;
    const values = Array.isArray(value) ? value : [value];
    if (!values.length) return;
    entries.push({
      ref: detailRef("diagnostic", kind),
      kind,
      label,
      value: values,
      evidence_refs: [...sourceRefsFrom(values), ...sourceRefsFrom(fallbackEvidence)].slice(0, MAX_REFS_PER_ITEM),
      claim_limit: claimLimit || t("workspace.claim"),
    });
  };
  const correlation = data.correlation || {};
  const readModel = data.correlation_read_model || {};
  const inbox = data.pressure_inbox || {};
  add("correlation-errors", t("diagnostic.correlationErrors"), firstPopulated(correlation.degradation, correlation.errors), correlation.claim_limit, correlation);
  add("correlation-conflicts", t("diagnostic.correlationConflicts"), firstPopulated(readModel.conflicts, correlation.conflicts), readModel.claim_limits?.conflicts || readModel.authority, readModel);
  add("correlation-duplicates", t("diagnostic.correlationDuplicates"), firstPopulated(readModel.duplicates, correlation.duplicates), readModel.claim_limits?.duplicates || readModel.authority, readModel);
  add("correlation-invalid", t("diagnostic.correlationInvalid"), firstPopulated(correlation.invalid_records, readModel.rebuild?.errors), correlation.claim_limit || readModel.authority, correlation);
  add("correlation-claim-limits", t("diagnostic.claimLimits"), firstPopulated(correlation.claim_limits, readModel.claim_limits), correlation.claim_limit || readModel.authority, correlation);
  add("owner-receipts", t("diagnostic.ownerReceipts"), correlation.envelopes?.map((item) => item.wake_observation?.provenance || item.wake_observation?.ref).filter(Boolean), correlation.claim_limit, correlation.envelopes);
  add("pressure-errors", t("diagnostic.pressureErrors"), firstPopulated(inbox.errors, inbox.invalid_records), inbox.claim_limit, inbox);
  add("pressure-conflicts", t("diagnostic.pressureConflicts"), firstPopulated(inbox.conflicts, inbox.duplicates), inbox.claim_limit, inbox);
  add("pressure-claim-limits", t("diagnostic.pressureClaimLimits"), inbox.claim_limit, inbox.claim_limit, inbox);
  return entries;
}

function renderDiagnosticRoutes(data, target) {
  const entries = diagnosticEntries(data);
  const panel = document.createElement("section");
  panel.className = "diagnostic-routes";
  panel.append(text("h4", t("diagnostic.heading")), text("p", t("diagnostic.claim"), "claim"));
  if (!entries.length) {
    panel.append(text("p", t("diagnostic.none"), "claim"));
    target.append(panel);
    return;
  }
  for (const entry of entries.slice(0, MAX_REFS_PER_ITEM * 2)) {
    const card = document.createElement("article");
    card.className = `diagnostic-card${selection.focus_ref === entry.ref ? " selected" : ""}`;
    const heading = document.createElement("div");
    heading.className = "diagnostic-head";
    const select = document.createElement("button");
    select.type = "button";
    select.className = "secondary";
    select.textContent = entry.label;
    select.setAttribute("data-focus-key", entry.ref);
    select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
    select.addEventListener("click", () => selectDetail(entry.ref));
    heading.append(select, badge(entry.value.length ? "invalid" : "unknown"));
    card.append(heading);
    const details = document.createElement("details");
    details.dataset.detailKey = entry.ref;
    details.open = selection.focus_ref === entry.ref;
    details.append(text("summary", t("diagnostic.open")), evidenceList(entry.evidence_refs), text("pre", boundedJson(entry.value, 2200)), text("p", entry.claim_limit, "claim"));
    card.append(details);
    panel.append(card);
  }
  target.append(panel);
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
  currentnessDetails.dataset.detailKey = "correlation:currentness";
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
  retention.append(text("p", `${plural("observation", arrayOrEmpty(readModel.observations).length)} · ${plural("conflict", arrayOrEmpty(readModel.conflicts).length)} · ${t("label.winnerSelection", { value: readModel.retention?.winner_selection || t("fallback.unknown") })}`));
  retention.append(evidenceList([readModel.cursor, readModel.checkpoint, readModel.rebuild].filter(Boolean)));
  target.append(retention);

  const envelopeItems = arrayOrEmpty(correlation.envelopes).map((envelope) => ({
    ref: `return:${envelope.return_observation?.return_id || envelope.correlation_id || t("fallback.return")}`,
    envelope,
  }));
  const envelopes = dashboardUI.pageWindow(envelopeItems, pageFor("correlation"), MAX_CORRELATION_ENVELOPES, selection.focus_ref);
  for (const entry of envelopes.items) {
    const envelope = entry.envelope;
    const card = document.createElement("article");
    card.className = `correlation-card${selection.focus_ref === entry.ref ? " selected" : ""}`;
    const headBlock = document.createElement("div");
    headBlock.className = "correlation-head";
    const returnId = envelope.return_observation?.return_id || envelope.correlation_id || t("fallback.return");
    const select = document.createElement("button");
    select.type = "button";
    select.className = "secondary";
    select.textContent = t("label.lunaReturn", { value: returnId });
    select.setAttribute("data-focus-key", entry.ref);
    select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
    select.addEventListener("click", () => selectDetail(entry.ref, "correlation", envelopes.page));
    headBlock.append(select, badge(envelope.state || "invalid"));
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
    details.dataset.detailKey = entry.ref;
    details.open = selection.focus_ref === entry.ref;
    details.append(text("summary", t("label.wakeDetails")));
    details.append(text("p", t("label.wakeFreshness", { source: wake.source_family || t("fallback.unknownSource"), freshness: statusLabel(wake.freshness || "unknown"), missingness: statusLabel(wake.missingness || "unknown") }), "claim"));
    details.append(evidenceList([wake.ref, { label: t("label.rawOwnerReceipt"), kind: wake.source_schema_version || t("fallback.wakeReceipt"), ref: wake.provenance?.raw_owner_ref || wake.ref?.ref, sha256: wake.provenance?.raw_owner_content_sha256 || wake.ref?.sha256, observed_at: wake.observed_at }]));
    const sourceSummary = { source_schema_version: wake.source_schema_version, owner_repo: wake.provenance?.owner_repo, owner_ref: wake.provenance?.owner_ref, contract_ref: wake.provenance?.contract_ref, failure: wake.failure };
    details.append(text("pre", JSON.stringify(sourceSummary, null, 2)));
    details.append(text("pre", boundedJson({ return: envelope.return_observation, claim_limits: envelope.claim_limits, degradation: envelope.degradation }, 2200)));
    details.append(text("p", envelope.claim_limits?.join ? envelope.claim_limits.join(" ") : envelope.claim_limits || correlation.claim_limit || t("workspace.claim"), "claim"));
    card.append(details);
    target.append(card);
  }
  showPageControls(target, "correlation", envelopes);
  if (envelopes.omitted) target.append(text("p", plural("envelope", envelopes.total - envelopes.items.length), "claim"));
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
  summary.append(badge(inbox.status || "missing"), text("span", `${plural("admitted", items.length)} · ${plural("critical", critical.length)} · ${plural("legacy", arrayOrEmpty(inbox.legacy_candidates).length)}`, "mono"));
  target.append(summary);
  const list = document.createElement("div");
  list.className = "pressure-list";
  const all = [
    ...items.map((item) => ({ ref: `pressure:${item.pressure_ref?.id || item.pressure_ref?.ref || t("fallback.pressure")}`, type: "item", item })),
    ...arrayOrEmpty(inbox.legacy_candidates).map((item) => ({ ref: `pressure:${item.pressure_ref?.id || item.pressure_ref?.ref || t("fallback.pressure")}`, type: "legacy", item })),
  ];
  const windowed = dashboardUI.pageWindow(all, pageFor("pressure"), MAX_PRESSURE_ITEMS, selection.focus_ref);
  for (const entry of windowed.items) {
    if (entry.type === "legacy") {
      const candidate = entry.item;
      const card = document.createElement("article");
      card.className = `pressure-card legacy${selection.focus_ref === entry.ref ? " selected" : ""}`;
      const select = document.createElement("button");
      select.type = "button";
      select.className = "secondary";
      select.textContent = candidate.pressure_ref?.id || t("pressure.legacyCandidate");
      select.setAttribute("data-focus-key", entry.ref);
      select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
      select.addEventListener("click", () => selectDetail(entry.ref, "pressure", windowed.page));
      card.append(select, badge("deferred"), text("p", candidate.legacy_obligation_redacted || t("fallback.legacyObligationRedacted"), "claim"), text("p", t("pressure.sourceDigest", { value: candidate.legacy_obligation_digest || t("fallback.unavailable") }), "mono muted"), text("p", t("pressure.missingFields", { value: arrayOrEmpty(candidate.missing_fields).join(", ") || t("fallback.unknown") }), "claim"));
      const details = document.createElement("details");
      details.dataset.detailKey = entry.ref;
      details.open = selection.focus_ref === entry.ref;
      details.append(text("summary", t("pressure.details")), evidenceList([candidate.source_evidence_ref, candidate.pressure_ref]), text("pre", boundedJson(candidate, 1800)), text("p", candidate.claim_limit || inbox.claim_limit || t("workspace.claim"), "claim"));
      card.append(details);
      list.append(card);
      continue;
    }
    const item = entry.item;
    const card = document.createElement("article");
    card.className = `pressure-card${item.next_route?.critical ? " critical" : ""}${selection.focus_ref === entry.ref ? " selected" : ""}`;
    const head = document.createElement("div");
    head.className = "pressure-head";
    const select = document.createElement("button");
    select.type = "button";
    select.className = "secondary";
    select.textContent = item.pressure_ref?.id || t("fallback.pressure");
    select.setAttribute("data-focus-key", entry.ref);
    select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
    select.addEventListener("click", () => selectDetail(entry.ref, "pressure", windowed.page));
    head.append(select, badge(item.outcome?.state || "invalid"));
    card.append(head, text("p", item.affected_goal_criterion || t("fallback.goalCriterionMissing"), "pressure-criterion"), text("p", t("pressure.ifOmitted", { value: item.consequence_of_omission || t("fallback.consequenceMissing") }), "claim"));
    const route = document.createElement("div");
    route.className = "pressure-route";
    route.append(text("span", item.next_route?.critical ? t("pressure.criticalNextRoute") : t("pressure.nextRoute"), "pressure-route-label"), text("strong", item.next_route?.route || t("fallback.routeMissing")), text("span", t("pressure.routeMeta", { owner: item.next_route?.owner || t("fallback.ownerMissing"), effect: item.next_route?.effect || t("fallback.unknown"), authority: item.next_route?.authority || t("fallback.unknown") }), "mono"));
    card.append(route);
    const details = document.createElement("details");
    details.dataset.detailKey = entry.ref;
    details.open = selection.focus_ref === entry.ref;
    details.append(text("summary", t("pressure.details")), text("p", t("pressure.naturalOwner", { owner: item.natural_owner?.owner || t("fallback.missing"), ref: item.natural_owner?.owner_ref || t("fallback.ownerRefMissing") }), "claim"), text("p", t("pressure.trigger", { value: item.recommended_trigger_strength || t("fallback.missing") }), "claim"), text("p", t("pressure.stopLine", { value: item.stop_line || t("fallback.missing") }), "claim"), text("p", t("pressure.wakeCondition", { value: item.wake_condition || t("fallback.missing") }), "claim"), evidenceList(item.evidence), text("pre", boundedJson({ checked_existing_surfaces: item.checked_existing_surfaces, independence_signals: item.independence_signals, outcome: item.outcome }, 1800)), text("p", t("pressure.claimLimit", { value: item.claim_limit || "" }), "claim"));
    card.append(details);
    list.append(card);
  }
  showPageControls(list, "pressure", windowed);
  if (windowed.omitted) list.append(text("p", plural("pressure", windowed.total - windowed.items.length), "claim"));
  if (!all.length) list.append(text("p", t("attention.noPressure"), "claim"));
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
  intro.append(text("strong", summary.actor_count == null ? plural("actor", null) : plural("actor", summary.actor_count)), badge(activity.state || "unknown"), text("p", activity.observation || t("fallback.actorActivityUnavailable")));
  target.append(intro);
  const actors = arrayOrEmpty(activity.actors);
  if (!actors.length) {
    target.append(text("p", t("fallback.noActorEnvelope"), "claim"));
    return;
  }
  const actorItems = actors.map((actor) => ({
    ref: `actor:${actor.actor_key || actor.actor_id || t("fallback.actorKeyUnknown")}`,
    actor,
  }));
  const windowed = dashboardUI.pageWindow(actorItems, pageFor("actors"), MAX_ACTOR_CARDS, selection.focus_ref);
  target.append(text("p", plural("participantsShown", windowed.total, { shown: windowed.items.length }), "claim"));
  for (const entry of windowed.items) {
    const actor = entry.actor;
    const card = document.createElement("article");
    card.className = `actor-card${selection.focus_ref === entry.ref ? " selected" : ""}`;
    const head = document.createElement("div");
    head.className = "actor-head";
    const title = document.createElement("div");
    const select = document.createElement("button");
    select.type = "button";
    select.className = "secondary";
    select.textContent = actor.identity?.label || actor.actor_id || actor.actor_key || t("fallback.actorIdentityUnknown");
    select.setAttribute("data-focus-key", entry.ref);
    select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
    select.addEventListener("click", () => selectDetail(entry.ref, "actors", windowed.page));
    title.append(select, text("div", actor.actor_key || t("fallback.actorKeyUnknown"), "mono muted"));
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
    details.dataset.detailKey = entry.ref;
    details.open = selection.focus_ref === entry.ref;
    details.append(text("summary", t("activity.technicalDetails")), evidenceList(actor.evidence_refs), text("pre", boundedJson({ incarnation: actor.identity?.incarnation_id, model: actor.identity?.model_id || actor.model, task: actor.task, process: actor.process, session: actor.session, terminal: actor.terminal, usage: actor.usage, provenance: actor.provenance }, 2600)));
    card.append(details, text("p", actor.claim_limit || "", "claim"));
    target.append(card);
  }
  showPageControls(target, "actors", windowed);
  if (windowed.omitted) target.append(text("p", plural("actor", windowed.total - windowed.items.length), "claim"));
}

function renderSources(data, target) {
  const sourceItems = arrayOrEmpty(data.sources).map((item) => ({ ref: `source:${item.id || t("fallback.unavailable")}`, item }));
  const sources = dashboardUI.pageWindow(sourceItems, pageFor("sources"), MAX_SOURCE_CARDS, selection.focus_ref);
  const grid = document.createElement("div");
  grid.className = "source-grid";
  for (const entry of sources.items) {
    const item = entry.item;
    const card = document.createElement("article");
    card.className = `source-card${selection.focus_ref === entry.ref ? " selected" : ""}`;
    const head = document.createElement("div");
    head.className = "source-head";
    const select = document.createElement("button");
    select.type = "button";
    select.className = "secondary";
    select.textContent = item.id;
    select.setAttribute("data-focus-key", entry.ref);
    select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
    select.addEventListener("click", () => selectDetail(entry.ref, "sources", sources.page));
    head.append(select, badge(item.state || "unknown"));
    card.append(head, text("div", item.owner || t("fallback.ownerMissing"), "source-owner"), text("p", item.observation || t("fallback.unavailable")));
    const freshness = document.createElement("div");
    freshness.append(text("span", t("sources.freshness"), "muted"), badge(item.freshness || "unknown"));
    card.append(freshness);
    const details = document.createElement("details");
    details.dataset.detailKey = entry.ref;
    details.open = selection.focus_ref === entry.ref;
    details.append(text("summary", t("sources.metadataEvidence")), evidenceList(item.evidence_refs), text("pre", boundedJson(item.metadata || {}, 2000)), text("p", t("sources.claimLimit", { value: item.claim_limit || "" }), "claim"));
    card.append(details);
    grid.append(card);
  }
  if (!sources.items.length) grid.append(text("p", t("evidence.noSources"), "claim"));
  target.append(grid);
  showPageControls(target, "sources", sources);
  if (sources.omitted) target.append(text("p", plural("source", sources.total - sources.items.length), "claim"));
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
  const ownerItems = arrayOrEmpty(data.owner_surfaces).map((item, index) => ({ ref: `owner:${item.owner || index}`, item }));
  const owners = dashboardUI.pageWindow(ownerItems, pageFor("owners"), MAX_OWNER_ROWS, selection.focus_ref);
  for (const entry of owners.items) {
    const item = entry.item;
    const rowNode = document.createElement("tr");
    rowNode.className = selection.focus_ref === entry.ref ? "selected" : "";
    const ownerCell = document.createElement("td");
    const select = document.createElement("button");
    select.type = "button";
    select.className = "secondary";
    select.textContent = item.owner || t("fallback.ownerMissing");
    select.setAttribute("data-focus-key", entry.ref);
    select.setAttribute("aria-pressed", String(selection.focus_ref === entry.ref));
    select.addEventListener("click", () => selectDetail(entry.ref, "owners", owners.page));
    ownerCell.append(select);
    rowNode.append(ownerCell, text("td", item.authority || t("fallback.unknown")), text("td", item.source_path || t("fallback.unavailable"), "mono"));
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
  showPageControls(target, "owners", owners);
  if (owners.omitted) target.append(text("p", plural("owner", owners.total - owners.items.length), "claim"));
}

function renderRecords(data, target) {
  const annotations = recordInfo(data, "annotations");
  const intents = recordInfo(data, "action_intents");
  const grid = document.createElement("div");
  grid.className = "records-grid";
  const recordBlock = (headingKey, summary, countKey, recordKey) => {
    const block = document.createElement("article");
    block.className = "record-card";
    block.append(text("h4", t(headingKey)), badge(summary.state || "unknown"), text("strong", summary.count == null ? t("records.countUnknown") : plural(summary === annotations ? "annotation" : "intent", summary.count)));
    const latest = arrayOrEmpty(summary.latest);
    if (latest.length) {
      for (const item of latest.slice(-3).reverse()) block.append(text("p", t("records.latest", { created: item.created_at || t("fallback.record"), target: item.target_ref || t("fallback.target") }), "mono"));
    } else block.append(text("p", summary.state === "missing" ? t("records.sourceMissing") : t("records.empty"), "claim"));
    block.append(text("p", t(recordKey), "claim"));
    block.append(evidenceList(summary.evidence_refs), text("p", summary.claim_limit || t("records.sourceMissing"), "claim"));
    return block;
  };
  grid.append(recordBlock("records.annotations", annotations, "records.annotationCount", "annotations.claim"), recordBlock("records.intents", intents, "records.intentCount", "actionIntents.suffix"));
  target.append(grid);
}

function renderLimits(data, target) {
  const details = document.createElement("details");
  details.className = "claim-details";
  details.dataset.detailKey = "workspace:claim-limits";
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
  renderDiagnosticRoutes(data, target);
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
  renderDiagnosticRoutes(data, target);
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

function envelopeMatchesSelection(envelope) {
  const goal = envelope?.goal || {};
  if (goal.goal_id !== selection.goal_ref) return false;
  if (selection.thread_ref && goal.master_thread_id !== selection.thread_ref && selection.thread_ref !== selection.goal_ref && selection.thread_ref !== selection.focus_ref) return false;
  if (!selection.focus_ref) return false;
  return `return:${envelope.return_observation?.return_id || envelope.correlation_id || t("fallback.return")}` === selection.focus_ref;
}

function routeMatchesSelection(item, selected = selection) {
  if (!selected.goal_ref || !item) return false;
  const itemGoal = item.goal_id || item.goal_ref || item.goal?.goal_id;
  if (!itemGoal || itemGoal !== selected.goal_ref) return false;
  const itemThread = item.thread_ref || item.master_thread_id || item.context_thread_ref;
  if (selected.thread_ref && itemThread !== selected.thread_ref) return false;
  const selectedFocus = selected.focus_ref;
  if (!selectedFocus) return true;
  const pressureRef = item.pressure_ref || {};
  return [item.context_ref, item.target_ref, item.focus_ref, pressureRef.id, pressureRef.ref, `pressure:${pressureRef.id || pressureRef.ref || ""}`].filter(Boolean).includes(selectedFocus);
}

function routeReadiness(item, selected = selection) {
  if (!routeMatchesSelection(item, selected)) return { ready: false, reason: "context" };
  const route = item.next_route || {};
  const currentness = route.currentness || item.currentness || item.pressure_ref?.currentness;
  const ready = Boolean(
    route.owner && route.route && route.effect === "none" && route.authority
    && item.stop_line && item.wake_condition && arrayOrEmpty(item.evidence).length
    && ADMITTED_ROUTE_CURRENTNESS.has(currentness)
  );
  return { ready, route, currentness, reason: ready ? null : "contract" };
}

function selectedEnvelope(data) {
  return arrayOrEmpty(data.correlation?.envelopes).find(envelopeMatchesSelection) || null;
}

function selectedOperateRoute(data) {
  return arrayOrEmpty(data.pressure_inbox?.items)
    .map((item) => ({ item, readiness: routeReadiness(item) }))
    .find((candidate) => candidate.readiness.ready) || null;
}

function renderThread(data) {
  const target = byId("thread-items");
  clear(target);
  const quality = byId("thread-quality");
  const selected = selection.thread_ref || selection.focus_ref || selection.goal_ref;
  const envelope = selectedEnvelope(data);
  setBadge(quality, selectionQuality === "missing" ? "missing" : envelope || !selection.focus_ref ? (data?.thread_projection?.state || "missing") : "missing");
  const selectionLabel = byId("thread-selection");
  if (selectionLabel) selectionLabel.textContent = selected ? t("thread.selection", { value: selected }) : t("thread.noSelection");
  if (!selected) {
    target.append(text("p", t("thread.noSelection"), "empty-state"));
  } else {
    const metadata = document.createElement("article");
    metadata.className = "thread-item thread-unavailable";
    metadata.append(text("strong", t("thread.metadataOnly")), text("p", t("thread.unavailable"), "claim"), text("p", t("thread.rawUnavailable"), "claim"));
    target.append(metadata);
    if (envelope) {
      const ret = document.createElement("article");
      ret.className = "thread-item";
      ret.append(text("strong", t("thread.returnItem")), badge(envelope.state || "invalid"), text("p", envelope.return_observation?.filter_disposition ? statusLabel(envelope.return_observation.filter_disposition) : t("fallback.missing"), "claim"), evidenceList([envelope.return_observation?.ref, envelope.accepted_turn?.basis_ref]), text("p", envelope.claim_limits?.join ? envelope.claim_limits.join(" ") : envelope.claim_limits || t("thread.claimLimit"), "claim"));
      target.append(ret);
      const wake = envelope.wake_observation || {};
      const wakeItem = document.createElement("article");
      wakeItem.className = "thread-item";
      wakeItem.append(text("strong", t("thread.wakeItem")), badge(wake.outcome || "missing"), text("p", t("label.wakeFreshness", { source: wake.source_family || t("fallback.unknownSource"), freshness: statusLabel(wake.freshness || "unknown"), missingness: statusLabel(wake.missingness || "unknown") }), "claim"), evidenceList([wake.ref, { label: t("label.rawOwnerReceipt"), kind: wake.source_schema_version || t("fallback.wakeReceipt"), ref: wake.provenance?.raw_owner_ref, sha256: wake.provenance?.raw_owner_content_sha256 }]));
      target.append(wakeItem);
    } else if (selection.focus_ref || selectionQuality === "stale") {
      target.append(text("p", t("thread.noMatchingEvidence"), "empty-state"), text("code", selection.focus_ref || selected, "mono"));
    }
    const annotationSurface = recordInfo(data, "annotations");
    const annotations = arrayOrEmpty(annotationSurface.latest).filter((item) => item.target_ref === selected || (selected === selection.goal_ref && item.target_ref === selection.goal_ref));
    for (const item of annotations.slice(-4).reverse()) {
      const card = document.createElement("article");
      card.className = "thread-item";
      card.append(text("strong", t("thread.annotationItem")), text("p", item.body || t("fallback.unavailable")), text("p", `${item.author_ref || t("fallback.unknown")} · ${item.created_at || t("fallback.unknown")}`, "mono muted"), text("p", t("thread.claimLimit"), "claim"));
      target.append(card);
    }
    const intentSurface = recordInfo(data, "action_intents");
    const intents = arrayOrEmpty(intentSurface.latest).filter((item) => item.target_ref === selected || (selected === selection.goal_ref && item.target_ref === selection.goal_ref));
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
    const candidate = selectedOperateRoute(data);
    const item = candidate?.item;
    const readiness = candidate?.readiness || { ready: false, route: {}, currentness: null };
    const route = readiness.route || {};
    routeCard.className = `operate-route-card ${readiness.ready ? "route-ready" : "route-missing"}`;
    routeCard.append(text("strong", readiness.ready ? t("operate.routeReady") : t("operate.routeMissing")), text("span", t("operate.target", { value: selected || t("fallback.missing") }), "mono"), text("span", t("operate.owner", { value: route.owner || t("fallback.ownerMissing") }), "mono"), text("span", t("operate.stopLine", { value: item?.stop_line || t("fallback.missing") }), "mono"), text("span", t("operate.returnRoute", { value: item?.wake_condition || t("fallback.missing") }), "mono"), text("span", t("operate.currentness", { value: readiness.currentness || t("fallback.unknown") }), "mono"), text("span", t("operate.effectCeiling"), "mono"));
    if (item) routeCard.append(evidenceList(item.evidence));
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
  interactionState = captureInteractionState();
  const retained = selectionQuality === "missing"
    && lastGoodProjection
    && goalRef(lastGoodProjection) === selection.goal_ref
    ? lastGoodProjection
    : data;
  renderRefreshState();
  renderRouteState();
  renderHeader(retained);
  renderHome(data);
  const hasGoal = Boolean(goalRef(retained));
  const workspace = byId("workspace-view");
  const home = byId("home-view");
  const selectedCurrentGoal = hasGoal && selection.goal_ref === goalRef(retained);
  if (workspace) workspace.classList.toggle("hidden", !selectedCurrentGoal);
  if (home) home.classList.toggle("hidden", selectedCurrentGoal);
  const fallback = byId("fallback-evidence");
  if (fallback) fallback.classList.toggle("hidden", selectedCurrentGoal || Boolean(data));
  if (selectedCurrentGoal) {
    renderBreadcrumb(retained);
    renderGoalSummary(retained);
    renderAttentionStrip(retained);
    renderRailQuality(retained);
    renderLens(retained);
    renderThread(retained);
  }
  updateLensButtons();
  updateModeButtons();
  restoreInteractionState(interactionState);
}

function knownFocusRefs(data) {
  return new Set([
    ...arrayOrEmpty(data.dag).map((item) => `dag:${item.id}`),
    ...arrayOrEmpty(data.lifecycle).map((item) => `lifecycle:${item.step}`),
    ...arrayOrEmpty(data.correlation?.envelopes).map((item) => `return:${item.return_observation?.return_id || item.correlation_id || t("fallback.return")}`),
    ...arrayOrEmpty(data.pressure_inbox?.items).map((item) => `pressure:${item.pressure_ref?.id || item.pressure_ref?.ref || t("fallback.pressure")}`),
    ...arrayOrEmpty(data.pressure_inbox?.legacy_candidates).map((item) => `pressure:${item.pressure_ref?.id || item.pressure_ref?.ref || t("fallback.pressure")}`),
    ...arrayOrEmpty(data.actor_activity?.actors).map((item) => `actor:${item.actor_key || item.actor_id || t("fallback.actorKeyUnknown")}`),
    ...arrayOrEmpty(data.sources).map((item) => `source:${item.id || t("fallback.unavailable")}`),
    ...arrayOrEmpty(data.owner_surfaces).map((item, index) => `owner:${item.owner || index}`),
    ...diagnosticEntries(data).map((item) => item.ref),
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
  setProjectionBusy(true);
  try {
    const response = await fetch("/api/projection", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || t("error.projectionRequestFailed"));
    const alertWasVisible = !byId("alert")?.classList.contains("hidden");
    const wasDegraded = refreshState !== "current" || alertWasVisible;
    currentProjection = data;
    if (!selection.goal_ref || goalRef(data) === selection.goal_ref || !lastGoodProjection) lastGoodProjection = data;
    lastGoodAt = data.generated_at || new Date().toISOString();
    refreshState = "current";
    if (selection.goal_ref && selection.goal_ref !== goalRef(data)) selectionQuality = "missing";
    else if (selection.focus_ref && !knownFocusRefs(data).has(selection.focus_ref)) selectionQuality = "stale";
    else if (!selectionQuality || selectionQuality === "missing" || selectionQuality === "stale") selectionQuality = null;
    selection.observation_cursor_or_generation = data.generated_at || null;
    renderProjection(data);
    clearAlert();
    setProjectionBusy(false);
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
    setProjectionBusy(false);
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
    if (interactionState?.drafts) delete interactionState.drafts[form.id];
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

window.AoaDashboardApp = Object.freeze({
  captureInteractionState,
  restoreInteractionState,
  setProjectionBusy,
  routeReadiness,
  refresh,
  getSelection: () => ({ ...selection, branch_path: [...selection.branch_path], expanded_branch_refs: [...selection.expanded_branch_refs], page_by_list: { ...selection.page_by_list } }),
});

refresh();
setInterval(refresh, 5000);
