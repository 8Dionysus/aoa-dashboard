const { createI18n } = window.AoaDashboardI18n;
const i18n = createI18n();

const dashboardUI = window.AoaDashboardUiState || {
  LENSES: ["trajectory", "attention", "participants", "evidence", "records"],
  SelectionContext: {
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

const LIFECYCLE = ["planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "wake requested", "reentered"];
const QUALITY = ["missing", "unknown", "stale", "deferred", "invalid"];
const LENSES = dashboardUI.LENSES;
const PRESENTATION_HANDLER_NAME = "aoaDashboardPresentation";
const PRESENTATION_LANGUAGES = new Set(["en", "ru"]);
const PRESENTATION_THEMES = new Set(["system", "light", "dark"]);
const PRESENTATION_DENSITIES = new Set(["comfortable", "compact"]);
const MAX_DIRECTIONS = 12;
const MAX_PEOPLE = 6;
const MAX_SOURCES = 12;
const MAX_REFS = 12;
const MAX_HUMAN_TEXT = 96;
const MAX_GOAL_DISPLAY = 68;
const ADMITTED_ROUTE_CURRENTNESS = new Set(["current", "current_at_read"]);

const SelectionContext = dashboardUI.SelectionContext;
let currentProjection = null;
let lastGoodProjection = null;
let refreshState = "loading";
let lastGoodAt = null;
let lastAnnouncement = "";
let workspaceMode = "observe";
let contextThreadOpen = false;
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
const plural = (key, count, variables = {}) => i18n.plural(`plural.${key}`, count, variables);
const catalogInfo = (data) => dashboardUI.qualifiedCatalog(data?.goal_catalog);
const recordInfo = (data, key) => dashboardUI.optionalRecord(data?.[key]);

function catalogItemForRef(data, ref) {
  if (!ref) return null;
  return catalogInfo(data).items.find((item) => item.ref === ref) || null;
}

function safeDate(value) {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  return Number.isFinite(date.getTime()) ? date : null;
}

function formatAbsoluteMinute(value) {
  const date = safeDate(value);
  if (!date) return t("time.unknown");
  const options = {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  };
  try {
    const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (timeZone) options.timeZone = timeZone;
  } catch (_error) {
    // The platform's local timezone remains the fallback.
  }
  return new Intl.DateTimeFormat(i18n.locale, options).format(date);
}

function formatHumanRecency(value, now = new Date()) {
  const date = safeDate(value);
  const reference = safeDate(now) || new Date();
  if (!date) return t("time.unknown");
  const delta = date.getTime() - reference.getTime();
  const absoluteSeconds = Math.abs(delta) / 1000;
  const relative = new Intl.RelativeTimeFormat(i18n.locale, { numeric: "auto" });
  if (absoluteSeconds < 90 * 60) return relative.format(Math.round(delta / 60000), "minute");
  if (absoluteSeconds < 36 * 60 * 60) return relative.format(Math.round(delta / 3600000), "hour");
  if (absoluteSeconds < 60 * 60 * 48) return relative.format(Math.round(delta / 86400000), "day");
  return formatAbsoluteMinute(date);
}

function humanize(value, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback;
  const textValue = String(value).replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!textValue) return fallback;
  return textValue.length > MAX_HUMAN_TEXT ? `${textValue.slice(0, MAX_HUMAN_TEXT - 1)}…` : textValue;
}

function boundedHumanText(value, fallback = "") {
  const candidate = String(value || "").replace(/\s+/g, " ").trim();
  if (!candidate) return fallback;
  return candidate.length > MAX_HUMAN_TEXT ? `${candidate.slice(0, MAX_HUMAN_TEXT - 1)}…` : candidate;
}

function isTechnicalValue(value) {
  const candidate = String(value || "").trim();
  return /^(?:actor|detail|goal|master-thread|owner|source|thread):/i.test(candidate)
    || /^(?:dag|lifecycle|pressure|return|task|thread):/i.test(candidate)
    || /^D\d+\b/i.test(candidate)
    || /^(?:one-shot|return|holder|incarnation|external codex|codex|wake|handoff)\b/i.test(candidate)
    || /^\/(?:home|srv|tmp|var)\//i.test(candidate)
    || /\/(?:home|srv|tmp|var)\//i.test(candidate)
    || /sha256:[0-9a-f]{16,}/i.test(candidate)
    || /(?:schema_version|claim_limit|evidence_refs|source_path)/i.test(candidate)
    || /\bsource\s+(?:dashboard|owner|route|path|surface):/i.test(candidate)
    || /\b(?:dashboard|correlation[_\s-]*read[_\s-]*model|cursor|checkpoint|task-local|task local|master[_\s-]*filter|current[_\s-]*head|runtime|event drift)\b/i.test(candidate)
    || /\b(?:filter|route)\s+(?:exact|the exact|a request|this route)\b/i.test(candidate)
    || /^[{\[]/.test(candidate)
    || /^[A-Za-z0-9.-]+(?:_[A-Za-z0-9.-]+)+$/.test(candidate)
    || /^[0-9a-f]{32,}$/i.test(candidate);
}

function humanValue(value, fallback = "") {
  if (isTechnicalValue(value)) return fallback;
  return humanize(value, fallback);
}

function presentationRoot(data) {
  const value = data?.presentation || data?.human_presentation;
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function presentationEntry(data, groups, key = null) {
  const root = presentationRoot(data);
  const names = Array.isArray(groups) ? groups : [groups];
  for (const name of names) {
    const collection = root[name];
    if (!collection || typeof collection !== "object") continue;
    if (key === null || key === undefined) return collection;
    if (Array.isArray(collection)) {
      const match = collection.find((item) => item && typeof item === "object" && [item.id, item.ref, item.key].includes(key));
      if (match) return match;
      continue;
    }
    if (Object.prototype.hasOwnProperty.call(collection, key)) return collection[key];
    if (collection.default && typeof collection.default === "object") return collection.default;
  }
  return null;
}

function localizedHumanValue(value, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "object" && !Array.isArray(value)) {
    const localized = value[i18n.language] ?? value.en ?? value.ru;
    return localized === undefined ? fallback : localizedHumanValue(localized, fallback);
  }
  return humanValue(value, fallback);
}

function localizedBoundLabel(value, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "object" && !Array.isArray(value)) {
    const localized = value[i18n.language];
    return localized === undefined ? fallback : localizedBoundLabel(localized, fallback);
  }
  return humanValue(value, fallback);
}

function presentationField(entry, field, fallback = "") {
  if (entry === null || entry === undefined) return fallback;
  if (typeof entry !== "object" || Array.isArray(entry)) return localizedHumanValue(entry, fallback);
  return localizedHumanValue(Object.prototype.hasOwnProperty.call(entry, field) ? entry[field] : entry, fallback);
}

function mergePresentation(...entries) {
  return entries.reduce((result, entry) => {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return result;
    return { ...result, ...entry };
  }, {});
}

function itemPresentation(data, groups, key, item) {
  return mergePresentation(presentationEntry(data, groups, key), item?.presentation, item?.human_presentation);
}

function humanOwner(value, fallback = "") {
  if (value === null || value === undefined || value === "") return fallback;
  const source = String(value).trim();
  const normalized = source.toLowerCase();
  const known = {
    "aoa-agents": t("owner.responsibility"),
    "master-thread": t("owner.master"),
    "aoa-dashboard": t("owner.goalSpace"),
    "goal-anchor": t("evidence.goalAnchor"),
    "aoa-session-memory": t("evidence.sessionHistory"),
    ".aoa/session memory": t("evidence.sessionHistory"),
    ".aoa/session-memory": t("evidence.sessionHistory"),
    "task-local-correlation": t("evidence.currentCorrelation"),
    "task-local-actor-activity": t("evidence.peopleUpdates"),
    "aoa-stats-source-coverage": t("evidence.measurements"),
    "actor-responsibility-receipts": t("evidence.ownerReceipts"),
    "aoa-kag-projection": t("evidence.knowledgeProjection"),
    "aoa-evals-surface": t("evidence.proofSurface"),
    "aoa-memo-surface": t("evidence.reviewedMemory"),
    "abyss-stack-surface": t("evidence.runtimeSurface"),
    "goal-thread-board": t("evidence.goalThreadBoard"),
    "participant-relations": t("evidence.participantRelations"),
    "aoa-evals": t("evidence.proofSurface"),
    "aoa-memo": t("evidence.reviewedMemory"),
    "abyss-stack": t("evidence.runtimeSurface"),
    "aoa-kag": t("evidence.knowledgeProjection"),
    "aoa-stats": t("evidence.measurements"),
    "operator:local": t("owner.operator"),
  };
  if (normalized.startsWith("master-thread:")) return known["master-thread"];
  if (normalized.startsWith("owner:")) return humanOwner(source.slice("owner:".length), fallback);
  if (source.length > 40 || /\b(?:independent|reviewer|contract|incarnation|return|holder)\b/i.test(source)) return fallback;
  if (isTechnicalValue(value)) return fallback;
  return known[normalized] || humanValue(source, fallback);
}

function humanSourceLabel(value) {
  const labels = {
    "goal-anchor": "evidence.goalAnchor",
    "aoa-session-memory": "evidence.sessionHistory",
    "task-local-correlation": "evidence.currentCorrelation",
    "task-local-actor-activity": "evidence.peopleUpdates",
    "aoa-stats-source-coverage": "evidence.measurements",
    "actor-responsibility-receipts": "evidence.ownerReceipts",
    "aoa-kag-projection": "evidence.knowledgeProjection",
    "aoa-evals-surface": "evidence.proofSurface",
    "aoa-memo-surface": "evidence.reviewedMemory",
    "abyss-stack-surface": "evidence.runtimeSurface",
    "goal-thread-board": "evidence.goalThreadBoard",
    "participant-relations": "evidence.participantRelations",
  };
  const key = labels[String(value || "").toLowerCase()];
  return key ? t(key) : humanValue(value, t("evidence.connectedSource"));
}

function currentOwnerGoal(data) {
  const goal = data?.goal;
  const owner = data?.owner_goal;
  if (!owner || typeof owner !== "object") return null;
  const exact = owner.goal;
  if (owner.state !== "bound" || owner.currentness !== "current_at_read") return null;
  if (!exact || typeof exact !== "object" || typeof exact.title !== "string" || typeof exact.thread_id !== "string") return null;
  if (goal?.title_source !== "codex_app_server_thread_goal" || goal.currentness !== "current_at_read") return null;
  if (goal.master_thread_id !== exact.thread_id || goal.title !== exact.title) return null;
  return goal;
}

function goalTitle(data) {
  const goal = data?.goal || {};
  const ownerGoal = currentOwnerGoal(data);
  if (ownerGoal) return boundedHumanText(ownerGoal.title, t("goal.titleUnavailable"));
  if (Object.prototype.hasOwnProperty.call(data || {}, "owner_goal") || goal.title_source === "codex_app_server_thread_goal") return t("goal.titleUnavailable");
  const configured = localizedBoundLabel(presentationEntry(data, "goal")?.title, "");
  const ownerLocalized = localizedBoundLabel(goal.title_by_locale || goal.localized_title, "");
  if (configured) return boundedHumanText(configured, t("goal.titleUnavailable"));
  if (ownerLocalized) return boundedHumanText(ownerLocalized, t("goal.titleUnavailable"));
  if (goal.title_locale === i18n.language) return boundedHumanText(goal.title, t("goal.titleUnavailable"));
  return t("goal.titleUnavailable");
}

function catalogItemTitle(item) {
  if (!item || item.title_state !== "available") return t("goal.titleUnavailable");
  const localized = localizedBoundLabel(item.title_by_locale, "");
  if (localized) return boundedHumanText(localized, t("goal.titleUnavailable"));
  if (item.title_locale === i18n.language && item.title) return boundedHumanText(item.title, t("goal.titleUnavailable"));
  return t("goal.titleUnavailable");
}

function selectedProjectionTitle(projection) {
  if (!projection || typeof projection !== "object") return "";
  const localized = localizedBoundLabel(projection.title_by_locale, "")
    || (projection.title_locale === i18n.language ? humanValue(projection.title, "") : "");
  if (localized) return boundedHumanText(localized, t("goal.titleUnavailable"));
  const presentation = localizedBoundLabel(projection.presentation?.title, "");
  return presentation ? boundedHumanText(presentation, t("goal.titleUnavailable")) : "";
}

function compactDisplayText(value, limit = MAX_GOAL_DISPLAY) {
  const candidate = String(value || "").replace(/\s+/g, " ").trim();
  if (!candidate || candidate.length <= limit) return candidate;
  const words = candidate.split(" ");
  let compact = "";
  for (const word of words) {
    const next = compact ? `${compact} ${word}` : word;
    if (next.length > limit - 1) break;
    compact = next;
  }
  if (!compact) compact = candidate.slice(0, limit - 1).trimEnd();
  return `${compact}…`;
}

function compactGoalTitle(data) {
  const full = goalTitle(data);
  if (currentOwnerGoal(data)) return compactDisplayText(full);
  const configured = presentationEntry(data, "goal");
  const explicit = presentationField(configured, "short_title", "")
    || presentationField(configured, "compact_title", "");
  return compactDisplayText(explicit || full);
}

function setDisplayTitle(node, visible, full) {
  if (!node) return;
  node.textContent = visible || full || "";
  if (full && visible && visible !== full) {
    node.setAttribute("aria-label", full);
    node.title = full;
    node.dataset.fullTitleAvailable = "true";
  } else {
    node.removeAttribute?.("aria-label");
    node.removeAttribute?.("title");
    if (node.dataset) delete node.dataset.fullTitleAvailable;
  }
}

function goalRef(data) {
  const goal = currentOwnerGoal(data);
  return goal?.goal_id || goal?.goal_ref || null;
}

function selectedCurrentGoalForData(data) {
  const ref = goalRef(data);
  return Boolean(ref && selection.goal_ref === ref);
}

function statusClass(value) {
  return String(value == null || value === "" ? "unknown" : value).toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

function badge(value) {
  const canonical = value == null || value === "" ? "unknown" : String(value);
  return text("span", statusLabel(canonical), `badge state-${statusClass(canonical)}`);
}

function setBadge(node, value) {
  if (!node) return;
  const canonical = value == null || value === "" ? "unknown" : String(value);
  node.textContent = statusLabel(canonical);
  node.className = `badge state-${statusClass(canonical)}`;
}

function text(tag, value, className = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null ? "" : String(value);
  return node;
}

function evidenceList(refs, limit = MAX_REFS) {
  const list = document.createElement("div");
  list.className = "ref-list";
  for (const ref of arrayOrEmpty(refs).filter(Boolean).slice(0, limit)) {
    const label = ref.label || ref.kind || t("diagnostics.refs");
    const location = ref.ref || ref.path || "unresolved";
    const digest = ref.sha256 ? ` · sha256:${ref.sha256}` : "";
    list.append(text("code", `${label}: ${location}${digest}`));
  }
  return list;
}

function detailRef(kind, value) {
  return `detail:${kind}:${String(value || "unknown").replace(/[^a-zA-Z0-9_.:#/-]+/g, "_").slice(0, 160)}`;
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
  controls.setAttribute("aria-label", t("trajectory.directions"));
  const previous = text("button", "‹", "pager-button");
  previous.type = "button";
  previous.setAttribute("aria-label", t("pager.previous"));
  previous.title = t("pager.previous");
  previous.disabled = !windowed.hasPrevious;
  previous.addEventListener("click", () => setPage(listKey, windowed.page - 1));
  const next = text("button", "›", "pager-button");
  next.type = "button";
  next.setAttribute("aria-label", t("pager.next"));
  next.title = t("pager.next");
  next.disabled = !windowed.hasNext;
  next.addEventListener("click", () => setPage(listKey, windowed.page + 1));
  controls.append(previous, text("span", `${windowed.page + 1} / ${windowed.pageCount}`, "pager-status"), next);
  target.append(controls);
}

function selectDetail(ref, listKey, page) {
  const pages = { ...selection.page_by_list };
  if (listKey !== undefined) pages[listKey] = page;
  contextThreadOpen = true;
  setSelection({ focus_ref: ref, thread_ref: ref, branch_path: [ref], page_by_list: pages });
}

function toggleTopologyBranch(ref) {
  const expanded = new Set(arrayOrEmpty(selection.expanded_branch_refs));
  if (expanded.has(ref)) expanded.delete(ref); else expanded.add(ref);
  setSelection({ expanded_branch_refs: [...expanded] });
}

function selectTopologyDetail(path) {
  const refs = arrayOrEmpty(path);
  const ref = refs[refs.length - 1];
  if (!ref) return;
  contextThreadOpen = true;
  setSelection({ focus_ref: ref, thread_ref: ref, branch_path: refs });
}

function announce(message) {
  if (!message || message === lastAnnouncement) return;
  lastAnnouncement = message;
  const target = byId("live-region");
  if (target) target.textContent = message;
}

function captureInteractionState() {
  const snapshot = { details: {}, scroll: {}, drafts: {}, focusKey: null, threadOpen: contextThreadOpen };
  for (const node of document.querySelectorAll("details")) {
    if (node.dataset.detailKey) snapshot.details[node.dataset.detailKey] = Boolean(node.open);
  }
  for (const id of ["center-surface", "lens-surface", "context-thread"]) {
    const node = byId(id);
    if (node) snapshot.scroll[id] = { top: node.scrollTop || 0, left: node.scrollLeft || 0 };
  }
  const active = document.activeElement;
  if (active) snapshot.focusKey = active.dataset?.focusKey || active.id || null;
  for (const form of [byId("annotation-form"), byId("intent-form")]) {
    if (!form?.id) continue;
    snapshot.drafts[form.id] = {};
    for (const control of Array.from(form.elements || [])) {
      if (control.name) snapshot.drafts[form.id][control.name] = { value: control.value };
    }
  }
  return snapshot;
}

function updateThreadVisibility() {
  const thread = byId("context-thread");
  byId("workspace-grid")?.classList?.toggle?.("thread-collapsed", !contextThreadOpen);
  if (thread) {
    thread.classList?.toggle?.("collapsed", !contextThreadOpen);
    thread.setAttribute?.("aria-hidden", String(!contextThreadOpen));
  }
  const toggle = byId("thread-toggle");
  if (toggle) {
    toggle.setAttribute?.("aria-expanded", String(contextThreadOpen));
    toggle.textContent = contextThreadOpen ? t("thread.close") : t("thread.toggle");
  }
}

function restoreInteractionState(snapshot = interactionState) {
  if (!snapshot) return;
  contextThreadOpen = snapshot.threadOpen === true || Boolean(selection.focus_ref);
  for (const node of document.querySelectorAll("details")) {
    const key = node.dataset.detailKey;
    if (key && Object.prototype.hasOwnProperty.call(snapshot.details, key)) node.open = snapshot.details[key];
  }
  for (const [id, position] of Object.entries(snapshot.scroll || {})) {
    const node = byId(id);
    if (node) { node.scrollTop = position.top; node.scrollLeft = position.left; }
  }
  for (const [formId, values] of Object.entries(snapshot.drafts || {})) {
    const form = byId(formId);
    if (!form) continue;
    for (const control of Array.from(form.elements || [])) {
      if (control.name && values[control.name]?.value !== undefined) control.value = values[control.name].value;
    }
  }
  updateThreadVisibility();
  if (snapshot.focusKey) {
    const focus = Array.from(document.querySelectorAll("[data-focus-key]"))
      .find((node) => node.dataset.focusKey === snapshot.focusKey) || byId(snapshot.focusKey);
    if (focus?.focus) focus.focus({ preventScroll: true });
  }
}

function clearAlert() {
  const alert = byId("alert");
  if (alert) { alert.textContent = ""; alert.classList.add("hidden"); }
}

function setProjectionBusy(value) {
  refreshInFlight = Boolean(value);
  for (const id of ["center-surface", "workspace-view"]) {
    const node = byId(id);
    node?.setAttribute?.("aria-busy", refreshInFlight ? "true" : "false");
  }
}

function applyStaticTranslations() {
  document.documentElement.lang = i18n.language;
  document.title = t("app.title");
  if (window.AoaDashboardTheme?.setLabels) {
    window.AoaDashboardTheme.setLabels({ label: t("theme.label"), ariaLabel: t("theme.ariaLabel"), system: t("theme.system"), light: t("theme.light"), dark: t("theme.dark") });
  }
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  for (const node of document.querySelectorAll("[data-i18n-aria-label]")) node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
  for (const button of document.querySelectorAll("[data-language]")) button.setAttribute("aria-pressed", String(button.dataset.language === i18n.language));
  const density = byId("density-mode");
  if (density && window.AoaDashboardTheme?.getDensity) density.value = window.AoaDashboardTheme.getDensity();
  updateLensButtons();
  updateModeButtons();
  updateThreadVisibility();
}

function publishNativePresentationPreference() {
  const language = i18n.language;
  const theme = window.AoaDashboardTheme?.getMode?.();
  if (!PRESENTATION_LANGUAGES.has(language) || !PRESENTATION_THEMES.has(theme)) return;
  const handler = window.webkit?.messageHandlers?.[PRESENTATION_HANDLER_NAME];
  if (handler && typeof handler.postMessage === "function") handler.postMessage({ language, theme });
}

function qualityForData(data) {
  const observed = [
    data?.goal_catalog?.state,
    data?.goal_catalog?.currentness,
    data?.goal_context?.state,
    data?.goal_context?.currentness,
    data?.goal_topology?.state,
    data?.goal_topology?.currentness,
    data?.correlation?.state,
    data?.correlation?.freshness,
    data?.correlation_read_model?.status,
    data?.correlation_read_model?.currentness,
    data?.correlation_read_model?.rebuild?.source_currentness,
    data?.pressure_inbox?.status,
    data?.actor_activity?.state,
    data?.owner_goal_context?.state,
    data?.participant_context?.state,
  ]
    .map((value) => String(value || "").toLowerCase());
  for (const value of ["invalid", "deferred", "stale", "missing", "unknown"]) if (observed.includes(value)) return value;
  return "unknown";
}

function workspaceNeedsReview(data) {
  const observed = [
    data?.goal_catalog?.state,
    data?.goal_catalog?.currentness,
    data?.goal_context?.state,
    data?.goal_context?.currentness,
    data?.goal_topology?.state,
    data?.goal_topology?.currentness,
    data?.correlation?.state,
    data?.correlation?.freshness,
    data?.correlation_read_model?.status,
    data?.correlation_read_model?.currentness,
    data?.correlation_read_model?.rebuild?.source_currentness,
  ].map((value) => String(value || "").toLowerCase());
  return observed.some((value) => QUALITY.includes(value)) || ["missing", "stale"].includes(selectionQuality);
}

function lifecycleForData(data) {
  const ownerState = currentOwnerGoal(data)?.state;
  if (ownerState) return ownerState;
  const values = arrayOrEmpty(data?.lifecycle);
  for (const step of [...LIFECYCLE].reverse()) {
    const item = values.find((candidate) => candidate?.step === step && candidate.state && !QUALITY.includes(candidate.state));
    if (item) return item.state;
  }
  return data?.goal?.state || "unknown";
}

function observedAt(value) {
  if (!value || typeof value !== "object") return null;
  return value.observed_at || value.generated_at || value.metadata?.observed_at || null;
}

function currentnessForData(data) {
  return data?.correlation?.master_filter?.currentness?.state || data?.correlation_read_model?.rebuild?.source_currentness || data?.correlation?.freshness || "unknown";
}

function cleanDirectionTitle(value, fallback) {
  const result = humanValue(value, fallback);
  if (!result) return fallback;
  return result.replace(/^D\d+\s*/i, "").replace(/^pressure[:\s]*/i, "").trim() || fallback;
}

function directionItems(data) {
  const items = [];
  for (const item of arrayOrEmpty(data?.dag)) {
    const configured = itemPresentation(data, ["directions", "dag"], item.id || item.ref, item);
    const ownerTopology = item.source_kind === "master_goal_topology";
    items.push({
      ref: `dag:${item.id || items.length}`,
      kind: "direction",
      title: presentationField(configured, "title", "") || (ownerTopology ? boundedHumanText(item.title, t("trajectory.direction")) : cleanDirectionTitle(item.title, t("trajectory.direction"))),
      state: item.state || "unknown",
      owner: humanOwner(item.owner, t("trajectory.master")),
      relationship: presentationField(configured, "relationship", "") || (ownerTopology && arrayOrEmpty(item.depends_on).length ? plural("direction", item.depends_on.length) : humanValue(item.pressure, t("trajectory.related"))),
      focus: presentationField(configured, "focus", "") || (ownerTopology ? boundedHumanText(item.observation, t("trajectory.focusUnavailable")) : humanValue(item.observation, t("trajectory.focusUnavailable"))),
      next: presentationField(configured, "next", "") || (ownerTopology ? "" : humanValue(item.next, t("trajectory.nextUnavailable"))),
      evidence_refs: arrayOrEmpty(item.evidence_refs),
      raw: item,
    });
  }
  for (const item of arrayOrEmpty(data?.pressure_inbox?.items)) {
    const pressure = item.pressure_ref || {};
    const ref = `pressure:${pressure.id || pressure.ref || items.length}`;
    if (items.some((candidate) => candidate.ref === ref)) continue;
    const configured = itemPresentation(data, ["pressures", "pressure"], pressure.id || pressure.ref || ref, item);
    items.push({
      ref,
      kind: "direction",
      title: presentationField(configured, "title", "") || cleanDirectionTitle(item.affected_goal_criterion, t("trajectory.direction")),
      state: item.outcome?.state || data?.pressure_inbox?.status || "unknown",
      owner: humanOwner(item.natural_owner?.owner || item.next_route?.owner, t("trajectory.master")),
      relationship: presentationField(configured, "relationship", "") || humanValue(item.next_route?.route, t("trajectory.related")),
      focus: presentationField(configured, "focus", "") || humanValue(item.consequence_of_omission, t("attention.consequenceUnavailable")),
      next: presentationField(configured, "next", "") || humanValue(item.next_route?.route, t("attention.nextUnavailable")),
      evidence_refs: arrayOrEmpty(item.evidence),
      raw: item,
    });
  }
  if (!items.length) {
    for (const item of arrayOrEmpty(data?.lifecycle).filter((candidate) => ["running", "paused", "returned", "deferred"].includes(candidate.state))) {
      const configured = itemPresentation(data, ["directions", "lifecycle"], `lifecycle:${item.step}`, item);
      items.push({ ref: `lifecycle:${item.step}`, kind: "direction", title: presentationField(configured, "title", "") || humanValue(item.step, t("trajectory.direction")), state: item.state, owner: t("trajectory.master"), relationship: presentationField(configured, "relationship", t("trajectory.related")), focus: presentationField(configured, "focus", "") || humanValue(item.observation, t("trajectory.focusUnavailable")), next: presentationField(configured, "next", t("trajectory.nextUnavailable")), evidence_refs: arrayOrEmpty(item.evidence_refs), raw: item });
    }
  }
  return items;
}

function topologyDirectionItems(data) {
  const topology = data?.goal_topology;
  if (topology?.state !== "bound") return [];
  const rootIds = new Set(arrayOrEmpty(topology.root_ids));
  return arrayOrEmpty(topology.nodes).map((node) => ({
    ref: `dag:${node.id}`,
    kind: "direction",
    title: boundedHumanText(node.title, t("trajectory.direction")),
    state: rootIds.has(node.id) ? lifecycleForData(data) : "unknown",
    owner: humanOwner(node.owner, ""),
    relationship: t("trajectory.supportingDirection"),
    focus: boundedHumanText(node.scope, t("trajectory.focusUnavailable")),
    next: "",
    user_facing: node.user_facing === true,
    evidence_refs: arrayOrEmpty(topology.evidence_refs),
    raw: { ...node, source_kind: "master_goal_topology" },
  }));
}

function isUserFacingDirection(item) {
  return item?.raw?.user_facing === true
    || item?.raw?.presentation?.user_facing === true
    || item?.user_facing === true;
}

function goalDirectionItem(data) {
  const goal = data?.goal || {};
  if (!currentOwnerGoal(data) || !goalRef(data)) return null;
  const configured = presentationEntry(data, ["trajectory", "goal_direction"], "primary");
  const sourceRefs = arrayOrEmpty(goal.source_refs);
  return {
    ref: "goal-direction",
    kind: "direction",
    title: presentationField(configured, "title", t("trajectory.goalDirectionTitle")),
    state: lifecycleForData(data),
    owner: humanOwner(data.current_holder?.label || data.current_holder?.holder, t("trajectory.master")),
    relationship: presentationField(configured, "relationship", t("trajectory.goalDirectionRelationship")),
    focus: presentationField(configured, "focus", t("trajectory.goalDirectionFocus")),
    next: presentationField(configured, "next", t("trajectory.goalDirectionNext")),
    evidence_refs: sourceRefs,
    raw: {
      source_kind: "goal_owner_presentation",
      source: data.owner_goal?.source || null,
      evidence_refs: sourceRefs,
      claim_limit: "Localized Goal direction is dashboard presentation over the exact owner Goal read; it does not replace Goal semantics or acceptance.",
    },
  };
}

function primaryDirectionItems(data) {
  const ownerDirections = directionItems(data)
    .filter((item) => !item.ref.startsWith("pressure:") && isUserFacingDirection(item));
  if (ownerDirections.length) return ownerDirections;
  const goalDirection = goalDirectionItem(data);
  return goalDirection ? [goalDirection] : [];
}

function trajectoryDirectionItems(data) {
  return primaryDirectionItems(data);
}

function participantPresentation(data, actor) {
  const configured = presentationEntry(data, "participants") || {};
  const identity = actor?.identity || {};
  const keys = [actor?.actor_key, actor?.actor_id, identity.actor_id, identity.identity_key].filter(Boolean);
  const items = configured.items || configured.people;
  const named = Array.isArray(items)
    ? items.find((item) => item && typeof item === "object" && keys.some((key) => [item.id, item.ref, item.key].includes(key)))
    : null;
  const role = configured.roles?.[identity.role_id];
  return mergePresentation(named, role ? { role } : null);
}

function humanParticipantName(value, fallback = "") {
  const candidate = humanValue(value, fallback);
  if (!candidate || candidate.length > 40 || !/^\p{L}[\p{L}.'-]*(?:\s+\p{L}[\p{L}.'-]*){0,2}$/u.test(candidate) || /\b(?:one-shot|return|holder|incarnation|external codex|codex|wake|handoff|independent|owner|reviewer|contract|task|role)\b/i.test(candidate)) return fallback;
  return candidate;
}

function explicitParticipantLabel(participant, identity, configured) {
  const candidates = [
    presentationField(configured, "name", ""),
    presentationField(configured, "label", ""),
    presentationField(configured, "display_name", ""),
    participant?.display_name,
    identity?.display_name,
  ];
  for (const candidate of candidates) {
    const label = humanParticipantName(candidate, "");
    if (label) return label;
  }
  return "";
}

function humanModelName(value, fallback = "") {
  const candidate = String(value || "").trim();
  if (!candidate || candidate.length > 64 || !/^[A-Za-z0-9][A-Za-z0-9._:/+-]*$/.test(candidate)) return fallback;
  return candidate;
}

function participantContextItems(data) {
  if (data?.participant_context?.state === "invalid") return [];
  return arrayOrEmpty(data?.participant_context?.participants).filter((participant) => {
    const identity = participant?.identity || {};
    return participant?.quality !== "invalid"
      && identity.display_name_state === "present"
      && Boolean(identity.display_name || participant?.display_name);
  }).map((participant, index) => {
    const identity = participant.identity || {};
    const task = participant.task_context || {};
    const model = participant.model_realization || {};
    const configured = participantPresentation(data, { actor_key: participant.ref, identity });
    const role = presentationField(configured, "role", "") || humanValue(identity.role_name, t("participants.roleUnknown"));
    const publishedLabel = explicitParticipantLabel(participant, identity, configured);
    if (!publishedLabel) return null;
    const title = publishedLabel;
    const taskValue = presentationField(configured, "task", "")
      || humanValue(task.summary, t("participants.workUnavailable"));
    const threadState = task.goal_thread?.state;
    const relationship = presentationField(configured, "relationship", "")
      || (threadState === "present" ? t("participants.goalThreadAvailable") : t("participants.relationshipUnavailable"));
    const quality = participant.quality || "unknown";
    return {
      ref: participant.ref || `actor:${index}`,
      kind: "person",
      title,
      state: quality,
      owner: null,
      role,
      model: model.state === "present" ? t("participants.modelAvailable") : null,
      model_state: model.state || "unknown",
      task: taskValue,
      relationship,
      focus: threadState === "present" ? t("participants.goalThreadAvailable") : t("participants.contextDeferred"),
      evidence_refs: arrayOrEmpty(participant.evidence_refs),
      raw: participant,
    };
  }).filter(Boolean);
}

function participantItems(data) {
  if (data?.participant_context && Array.isArray(data.participant_context.participants)) return participantContextItems(data);
  if (["invalid", "missing"].includes(data?.actor_activity?.state)) return [];
  return arrayOrEmpty(data?.actor_activity?.actors).filter((actor) => {
    const identity = actor?.identity || {};
    return Boolean(identity.display_name || actor?.display_name);
  }).map((actor, index) => {
    const identity = actor.identity || {};
    const task = actor.task || {};
    const responsibility = actor.responsibility || {};
    const configured = participantPresentation(data, actor);
    const role = presentationField(configured, "role", "") || humanValue(identity.role_name, t("participants.roleUnknown"));
    const publishedLabel = explicitParticipantLabel(actor, identity, configured);
    if (!publishedLabel) return null;
    const title = publishedLabel;
    const model = presentationField(configured, "model", "") || humanModelName(identity.model_id, "");
    const taskValue = presentationField(configured, "task", "")
      || humanValue(task.summary || task.title, t("participants.workUnavailable"));
    const relationship = presentationField(configured, "relationship", "") || humanValue(responsibility.responsibility_state, t("participants.relationshipUnavailable"));
    return {
      ref: `actor:${actor.actor_key || actor.actor_id || index}`,
      kind: "person",
      title,
      state: actor.state || responsibility.state || "unknown",
      owner: humanParticipantName(responsibility.owner_display_name || responsibility.owner_label, "") || null,
      role,
      model: model || null,
      task: taskValue,
      relationship,
      focus: statusLabel(task.state || "unknown"),
      evidence_refs: arrayOrEmpty(actor.evidence_refs),
      raw: actor,
    };
  }).filter(Boolean);
}

function contextDisplayState(value) {
  return value === "current" ? "current_at_read" : value || "unknown";
}

function goalThreadBoard(data) {
  const value = data?.goal_context?.thread_board;
  return value && typeof value === "object" ? value : { state: "missing", items: [], relations: [], diagnostics: [] };
}

function participantGraph(data) {
  const value = data?.goal_context?.participant_graph;
  return value && typeof value === "object" ? value : { state: "missing", records: [], diagnostics: [] };
}

function goalThreadItems(data) {
  const board = goalThreadBoard(data);
  if (board.state !== "current") return [];
  return arrayOrEmpty(board.items).slice(0, 24).map((item, index) => ({
    ref: `thread-item:${item.item_ref || index}`,
    kind: "thread_item",
    title: t("thread.boardItem"),
    state: contextDisplayState(item.review_state || board.state),
    owner: null,
    relationship: t("thread.boardOrder"),
    focus: t("thread.boardItem"),
    evidence_refs: arrayOrEmpty(board.evidence_refs),
    raw: { item_kind: item.item_kind || null, order_state: item.order_state || null, review_state: item.review_state || null },
  }));
}

function goalThreadRelationItems(data) {
  const board = goalThreadBoard(data);
  if (board.state !== "current") return [];
  return arrayOrEmpty(board.relations).slice(0, 24).map((item, index) => ({
    ref: `thread-relation:${item.relation_ref || index}`,
    kind: "thread_relation",
    title: t("thread.boardRelation"),
    state: contextDisplayState(item.relation_state || "present"),
    owner: null,
    relationship: t("thread.boardOrder"),
    focus: t("thread.boardRelation"),
    evidence_refs: arrayOrEmpty(board.evidence_refs),
    raw: { relation_kind: item.relation_kind || null, relation_state: item.relation_state || null, semantic_branch_state: item.semantic_branch_state || null },
  }));
}

function participantAssignmentItems(data) {
  const graph = participantGraph(data);
  if (graph.state !== "current") return [];
  return arrayOrEmpty(graph.records).slice(0, 24).map((record, index) => {
    const dimensions = record?.dimensions || {};
    const state = record?.state || "unknown";
    return {
      ref: `assignment:${record.relation_id || index}`,
      kind: "assignment",
      title: t("participants.assignment"),
      state,
      owner: null,
      role: statusLabel(dimensions.obligation_role?.state || "unknown"),
      task: statusLabel(dimensions.task_assignment?.state || "unknown"),
      model: statusLabel(dimensions.model_realization?.state || "unknown"),
      model_state: dimensions.model_realization?.state || "unknown",
      runtime: statusLabel(dimensions.runtime_incarnation?.state || "unknown"),
      relationship: t("participants.assignmentState", { value: statusLabel(state) }),
      focus: t("participants.assignmentTask", { value: statusLabel(dimensions.task_assignment?.state || "unknown") }),
      evidence_refs: arrayOrEmpty(graph.evidence_refs),
      raw: {
        state,
        dimensions: Object.fromEntries(Object.entries(dimensions).map(([key, value]) => [key, { state: value?.state || "unknown" }])),
      },
    };
  });
}

function sourceItems(data) {
  return arrayOrEmpty(data?.sources).map((item) => {
    const configured = itemPresentation(data, ["sources", "evidence"], item.id || item.ref, item);
    const state = item.state || "unknown";
    return {
      ref: `source:${item.id || "unknown"}`,
      kind: "source",
      title: presentationField(configured, "title", "") || humanSourceLabel(item.id),
      state,
      owner: humanOwner(item.owner, t("trajectory.master")),
      relationship: presentationField(configured, "relationship", "") || (state === "missing" ? t("evidence.sourceUnavailable") : t("evidence.connectedSource")),
      focus: presentationField(configured, "focus", "") || (state === "missing" ? t("evidence.sourceMissing") : t("evidence.sourceObserved")),
      evidence_refs: arrayOrEmpty(item.evidence_refs),
      raw: item,
    };
  });
}

function contextForRef(data, ref) {
  if (!ref) return null;
  return primaryDirectionItems(data).find((item) => item.ref === ref)
    || directionItems(data).find((item) => item.ref === ref)
    || topologyDirectionItems(data).find((item) => item.ref === ref)
    || participantItems(data).find((item) => item.ref === ref)
    || participantAssignmentItems(data).find((item) => item.ref === ref)
    || goalThreadItems(data).find((item) => item.ref === ref)
    || goalThreadRelationItems(data).find((item) => item.ref === ref)
    || sourceItems(data).find((item) => item.ref === ref)
    || null;
}

function contextForSelection(data) {
  return contextForRef(data, selection.focus_ref);
}

function nextFocus(data) {
  const directions = primaryDirectionItems(data);
  const critical = directionItems(data).find((item) => item.ref.startsWith("pressure:") && item.raw?.next_route?.critical);
  return directions[0] || critical || null;
}

function attentionFocus(data) {
  return directionItems(data).find((item) => item.ref.startsWith("pressure:") && item.raw?.next_route?.critical)
    || null;
}

function renderRouteState() {
  const target = byId("route-status");
  if (!target) return;
  clear(target);
  if (routeState === "invalid") {
    target.className = "route-status state-invalid";
    target.append(badge("invalid"), text("span", t("route.invalid")));
  } else target.className = "route-status hidden";
}

function renderConnectionState(data = currentProjection) {
  const target = byId("connection");
  if (!target) return;
  const needsReview = refreshState === "current" && selectedCurrentGoalForData(data) && workspaceNeedsReview(data);
  const presentation = {
    loading: { label: "connection.loading", className: "loading" },
    current: needsReview
      ? { label: "connection.needsReview", className: "needs-review" }
      : { label: "connection.available", className: "ready" },
    stale: { label: "connection.degraded", className: "stale" },
    disconnected: { label: "connection.unavailable", className: "disconnected" },
  }[refreshState] || { label: "connection.unavailable", className: "disconnected" };
  target.textContent = t(presentation.label);
  target.className = `connection-state state-${presentation.className}`;
}

function renderRefreshState(data = currentProjection) {
  renderConnectionState(data);
  const target = byId("refresh-status");
  if (!target || typeof target.append !== "function") return;
  clear(target);
  const needsReview = refreshState === "current" && selectedCurrentGoalForData(data) && workspaceNeedsReview(data);
  target.className = `refresh-note state-${refreshState}${needsReview ? " state-needs-review" : ""}`;
  if (refreshState === "loading") target.append(text("strong", t("refresh.loading")), text("span", t("refresh.noCounts")));
  else if (refreshState === "current" && needsReview) target.append(text("strong", t("refresh.needsReview")), text("span", t("refresh.needsReviewDetail")));
  else if (refreshState === "current") target.append(text("strong", t("refresh.current")), text("span", formatHumanRecency(lastGoodAt)));
  else if (refreshState === "stale") target.append(text("strong", t("refresh.stale")), text("span", formatHumanRecency(lastGoodAt)), text("span", t("refresh.retry")));
  else target.append(text("strong", t("refresh.disconnected")), text("span", t("refresh.retry")));
}

function renderHeader(data) {
  const title = goalTitle(data);
  const lifecycle = lifecycleForData(data);
  const quality = selectionQuality === "missing" ? "missing" : selectionQuality === "stale" ? "stale" : qualityForData(data);
  const heading = byId("workspace-heading");
  setDisplayTitle(heading, compactGoalTitle(data), title);
  const focus = nextFocus(data);
  const summary = byId("workspace-summary");
  if (summary) summary.textContent = t(focus ? "workspace.summary" : "workspace.summaryNoFocus", { state: statusLabel(lifecycle), focus: focus?.title || t("trajectory.nextFocusEmpty") });
  const recency = byId("workspace-recency");
  if (recency) {
    const recencyKey = workspaceNeedsReview(data) ? "workspace.observed" : "workspace.recency";
    recency.textContent = t(recencyKey, { value: formatHumanRecency(data.generated_at || lastGoodAt) });
    if (data.generated_at) recency.dateTime = data.generated_at;
    recency.title = formatAbsoluteMinute(data.generated_at || lastGoodAt);
  }
  setBadge(byId("workspace-lifecycle"), lifecycle);
  setBadge(byId("workspace-quality"), quality);
}

function catalogTimeFact(labelKey, value) {
  const wrapper = document.createElement("div");
  wrapper.className = "catalog-fact";
  wrapper.append(text("dt", t(labelKey)));
  const description = document.createElement("dd");
  const time = text("time", formatAbsoluteMinute(value));
  if (value) {
    time.dateTime = value;
    time.title = formatAbsoluteMinute(value);
  }
  description.append(time);
  wrapper.append(description);
  return wrapper;
}

function renderCatalogWorkspace(data, item) {
  const heading = byId("catalog-workspace-heading");
  const summary = byId("catalog-workspace-summary");
  const lifecycle = byId("catalog-workspace-lifecycle");
  const recency = byId("catalog-workspace-recency");
  const body = byId("catalog-workspace-body");
  clear(body);
  if (!item) {
    if (heading) heading.textContent = t("workspace.historyUnavailableTitle");
    if (summary) summary.textContent = t("workspace.historyUnavailable");
    setBadge(lifecycle, "missing");
    if (recency) { recency.textContent = ""; recency.removeAttribute?.("datetime"); recency.removeAttribute?.("title"); }
    body?.append(text("p", t("workspace.historyUnavailable"), "catalog-disclosure state-missing"));
    return;
  }
  const selectedProjection = data?.selected_goal_projection?.goal_ref === item.ref ? data.selected_goal_projection : null;
  const projectionTitle = selectedProjectionTitle(selectedProjection);
  const fullTitle = projectionTitle || catalogItemTitle(item);
  setDisplayTitle(heading, compactDisplayText(fullTitle), fullTitle);
  const projectionState = selectedProjection?.state;
  const projectionBound = selectedProjection?.source?.owner === "aoa-session-memory"
    && ["current", "current_at_read", "stale"].includes(projectionState);
  const localizedSummary = selectedProjection?.summary && typeof selectedProjection.summary === "object"
    ? localizedBoundLabel(selectedProjection.summary, "")
    : "";
  const projectionSummary = projectionBound
    ? localizedSummary || t("workspace.ownerProjectionSummary")
    : t("workspace.historySummary");
  if (summary) summary.textContent = projectionSummary;
  setBadge(lifecycle, projectionBound ? selectedProjection.lifecycle_state : item.lifecycle_state);
  if (recency) {
    recency.textContent = t("workspace.recency", { value: formatHumanRecency(item.last_observed_at) });
    if (item.last_observed_at) recency.dateTime = item.last_observed_at;
    recency.title = formatAbsoluteMinute(item.last_observed_at);
  }
  const facts = document.createElement("dl");
  facts.className = "catalog-facts";
  facts.append(
    catalogTimeFact("workspace.historyFirstSeen", item.first_observed_at),
    catalogTimeFact("workspace.historyLastSeen", item.last_observed_at),
  );
  body?.append(facts);
  const catalog = catalogInfo(data);
  const notes = document.createElement("div");
  notes.className = "catalog-disclosures";
  if (projectionBound) {
    notes.append(text("p", t("workspace.ownerProjectionAvailable"), "catalog-disclosure"));
    if (selectedProjection.public_items?.length) notes.append(text("p", t("workspace.ownerProjectionItems", { count: selectedProjection.public_items.length }), "catalog-disclosure"));
    if (selectedProjection.omissions && Object.keys(selectedProjection.omissions).length) notes.append(text("p", t("workspace.ownerProjectionOmissions"), "catalog-disclosure"));
  } else {
    notes.append(text("p", t("workspace.historyDetailsMissing"), "catalog-disclosure"));
    if (selectedProjection?.state === "deferred" || selectedProjection?.state === "missing") notes.append(text("p", t("workspace.ownerProjectionDeferred"), "catalog-disclosure"));
  }
  const sourceLag = arrayOrEmpty(catalog.sources).some((source) =>
    !["current", "current_at_read"].includes(source?.currentness)
  );
  if (["stale", "deferred", "unknown"].includes(catalog.state) || sourceLag) {
    notes.append(text("p", t("workspace.historyMayLag"), "catalog-disclosure"));
  }
  if (item.ambiguity) notes.append(text("p", t("workspace.historyIncomplete"), "catalog-disclosure"));
  body?.append(notes);
}

function renderHome(data) {
  const selector = byId("goal-selector");
  const catalogState = byId("catalog-state");
  clear(selector);
  clear(catalogState);
  const goal = data?.goal || {};
  const catalog = catalogInfo(data);
  const groups = ["active", "attention", "paused", "completed"];
  for (const group of groups) {
    const items = catalog.items.filter((item) => item.group === group);
    if (!items.length) continue;
    const section = document.createElement("section");
    section.className = "goal-group";
    section.append(text("h3", t(`home.group.${group}`), "goal-group-heading"));
    const list = document.createElement("div");
    list.className = "goal-list";
    const windowed = dashboardUI.pageWindow(items, pageFor(`catalog-${group}`), 6, selection.goal_ref);
    for (const item of windowed.items) {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "goal-list-item";
      row.setAttribute("aria-label", `${t("home.openWorkspace")}: ${catalogItemTitle(item)}`);
      row.setAttribute("aria-pressed", String(selection.goal_ref === item.ref));
      const copy = document.createElement("span");
      copy.className = "goal-list-copy";
      const itemTitle = text("strong", "", "goal-display-title");
      const displayTitle = catalogItemTitle(item);
      setDisplayTitle(itemTitle, compactDisplayText(displayTitle), displayTitle);
      copy.append(itemTitle, text("span", statusLabel(item.lifecycle_state), "goal-list-state"));
      const recent = text("time", formatHumanRecency(item.last_observed_at), "goal-list-time");
      if (item.last_observed_at) recent.dateTime = item.last_observed_at;
      row.append(copy, recent);
      row.addEventListener("click", () => {
        contextThreadOpen = false;
        setSelection({ goal_ref: item.ref, lens: "trajectory", focus_ref: null, branch_path: [], thread_ref: item.ref });
        byId("catalog-workspace-view")?.focus?.({ preventScroll: true });
        announce(displayTitle);
      });
      list.append(row);
    }
    section.append(list);
    showPageControls(section, `catalog-${group}`, windowed);
    selector.append(section);
  }

  catalogState.className = `catalog-note state-${catalog.state}`;
  if (catalog.state === "missing" || catalog.state === "invalid") {
    catalogState.className = `empty-state state-${catalog.state}`;
    catalogState.dataset.catalogState = catalog.state;
    catalogState.append(badge(catalog.state), text("span", catalog.state === "missing" ? t("home.catalogMissing") : t("home.catalogUnavailable")));
  } else if (catalog.state === "stale" || catalog.state === "deferred" || catalog.state === "unknown") {
    catalogState.append(text("span", t("home.historyUpdating")));
  } else if (arrayOrEmpty(catalog.sources).some((source) =>
    source?.owner === "aoa-session-memory" && !["current", "current_at_read"].includes(source?.currentness)
  )) {
    catalogState.append(text("span", t("home.historyUpdating")));
  } else if (!catalog.items.length) {
    catalogState.append(text("span", t("home.catalogEmpty")));
  }
  const unavailableCount = catalog.items.filter((item) => catalogItemTitle(item) === t("goal.titleUnavailable")).length;
  if (unavailableCount > 0) catalogState.append(text("span", t("home.unnamedCount", { count: unavailableCount }), "catalog-muted"));
  if (catalog.pagination?.next_cursor) catalogState.append(text("span", t("home.moreAvailable"), "catalog-muted"));
  if (!catalogState.children.length) catalogState.classList.add("hidden");

  const currentGoalRef = goalRef(data);
  if (currentGoalRef) {
    const card = document.createElement("article");
    card.className = "goal-selector-card selected-runtime-goal";
    const main = document.createElement("div");
    main.className = "goal-selector-main";
    const currentTitle = text("h2", "", "goal-display-title");
    setDisplayTitle(currentTitle, compactGoalTitle(data), goalTitle(data));
    main.append(text("p", t("home.currentGoal"), "card-label"), currentTitle);
    const status = document.createElement("div");
    status.className = "goal-card-states";
    status.append(badge(goal.state || "unknown"), badge(qualityForData(data)));
    main.append(status);
    const open = text("button", t("home.openWorkspace"), "goal-open-button");
    open.type = "button";
    open.setAttribute("aria-label", `${t("home.openWorkspace")}: ${goalTitle(data)}`);
    open.addEventListener("click", () => {
      contextThreadOpen = false;
      setSelection({ goal_ref: currentGoalRef, lens: "trajectory", focus_ref: null, branch_path: [], thread_ref: goal.master_thread_id || currentGoalRef });
      byId("center-surface")?.focus?.({ preventScroll: true });
    });
    card.append(main, open);
    selector.append(card);
  } else if (!catalog.items.length && catalog.state === "missing") {
    selector.append(text("p", t("home.goalUnavailable"), "empty-copy"));
  }
}

function renderBreadcrumb(data) {
  const target = byId("breadcrumb");
  clear(target);
  const refs = arrayOrEmpty(selection.branch_path);
  if (!refs.length) return;
  const path = refs.map((ref) => ({ ref, context: contextForRef(data, ref) })).filter((item) => item.context);
  for (const [index, item] of path.entries()) {
    if (index) target.append(text("span", "›", "breadcrumb-separator"));
    if (index === path.length - 1) {
      const current = text("span", item.context.title, "breadcrumb-current");
      current.setAttribute("aria-current", "page");
      target.append(current);
      continue;
    }
    const link = text("button", item.context.title, "breadcrumb-link");
    link.type = "button";
    link.addEventListener("click", () => selectTopologyDetail(path.slice(0, index + 1).map((entry) => entry.ref)));
    target.append(link);
  }
}

function summaryCard(label, value, detail, state) {
  const card = document.createElement("article");
  card.className = "summary-card";
  card.append(text("p", label, "card-label"), text("strong", value, "summary-value"));
  if (state) card.append(badge(state));
  if (detail) card.append(text("p", detail, "summary-detail"));
  return card;
}

function renderGoalSummary(data) {
  const target = byId("goal-summary");
  clear(target);
  const holder = data.current_holder || {};
  const people = participantItems(data);
  const focus = nextFocus(data);
  const focusDetail = focus?.raw?.source_kind === "master_goal_topology"
    ? focus.focus
    : focus
      ? t("trajectory.next", { value: focus.next || t("trajectory.nextFocusEmpty") })
      : t("trajectory.nextFocusHelp");
  const participantSummary = data.participant_context?.summary || {};
  const count = participantSummary.participant_count ?? data.actor_activity?.summary?.actor_count;
  const participantState = data.participant_context?.state || data.actor_activity?.state || "unknown";
  const aggregateCount = participantSummary.aggregate_count ?? participantSummary.invalid_count;
  const aggregateLabel = aggregateCount == null ? "" : `: ${aggregateCount}`;
  const peopleValue = participantState === "invalid"
    ? t("participants.aggregateUnavailable", { count: aggregateLabel })
    : count == null ? plural("person", null) : plural("person", count);
  target.append(
    summaryCard(t("trajectory.master"), humanOwner(holder.label || holder.holder, t("trajectory.masterUnknown")), t("trajectory.masterSummary"), lifecycleForData(data)),
    summaryCard(t("trajectory.people"), peopleValue, t("participants.intro"), participantState),
    summaryCard(t("trajectory.nextFocus"), focus?.title || t("trajectory.nextFocusEmpty"), focusDetail, focus?.state || "unknown"),
  );
  if (people.length && people.length < (count || people.length)) {
    target.lastElementChild.append(text("p", t("trajectory.peopleMore", { count: Math.max(0, (count || people.length) - people.length) }), "summary-detail"));
  }
}

function renderAttentionStrip(data) {
  const target = byId("attention-strip");
  clear(target);
  const focus = attentionFocus(data);
  target.append(text("p", t("attention.heading"), "card-label"));
  if (focus && focus.ref.startsWith("pressure:")) {
    target.append(text("strong", focus.title, "attention-title"));
    if (statusLabel(focus.state) !== statusLabel("unknown")) target.append(badge(focus.state));
    target.append(text("span", t("attention.owner", { value: focus.owner }), "attention-meta"));
  } else target.append(text("strong", workspaceNeedsReview(data) ? t("attention.needsReview") : t("attention.noPressure"), "attention-title"));
}

function updateLensButtons() {
  for (const button of document.querySelectorAll("[data-lens]")) {
    const active = button.dataset.lens === selection.lens;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
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
  try { window.history.replaceState(null, "", dashboardUI.encodeRoute(selection)); } catch (_error) { /* embedded view */ }
}

function readRoute() {
  const route = dashboardUI.decodeRoute(window.location?.hash || "");
  routeState = route.status || "invalid";
  routeError = route.error || null;
  selection = SelectionContext.normalize(route.selection);
  contextThreadOpen = Boolean(selection.focus_ref);
}

function setSelection(patch) {
  const previousGoalRef = selection.goal_ref;
  selection = SelectionContext.normalize({ ...selection, ...patch });
  if (Object.prototype.hasOwnProperty.call(patch, "goal_ref") && !patch.goal_ref) selectionQuality = null;
  if (Object.prototype.hasOwnProperty.call(patch, "focus_ref")) {
    selectionQuality = null;
    if (patch.focus_ref) contextThreadOpen = true;
  }
  routeState = selection.goal_ref ? "valid" : "home";
  routeError = null;
  syncRoute();
  if (currentProjection) renderProjection(currentProjection);
  if (Object.prototype.hasOwnProperty.call(patch, "goal_ref") && patch.goal_ref && patch.goal_ref !== previousGoalRef && currentProjection) refresh();
}

function createSurface(titleKey, introKey) {
  const panel = document.createElement("section");
  panel.className = "surface-panel";
  panel.append(text("p", t(titleKey), "panel-label"), text("h2", t(titleKey), "panel-title"));
  if (introKey) panel.append(text("p", t(introKey), "panel-intro"));
  const body = document.createElement("div");
  body.className = "surface-body";
  panel.append(body);
  return { panel, body };
}

function renderMasterNode(data, target) {
  const holder = data.current_holder || {};
  const card = document.createElement("article");
  card.className = "node-card master-node";
  card.append(text("p", t("trajectory.master"), "node-kicker"), text("h3", humanOwner(holder.label || holder.holder, t("trajectory.masterUnknown"))), badge(lifecycleForData(data)), text("p", t("trajectory.masterSummary"), "node-detail"));
  target.append(card);
}

function renderTopologyBranches(data, item, target, path = [item.ref]) {
  const dependencies = arrayOrEmpty(item.raw?.depends_on);
  if (!dependencies.length) return;
  const expanded = arrayOrEmpty(selection.expanded_branch_refs).includes(item.ref);
  const toggle = text("button", expanded ? t("trajectory.hideSupporting") : t("trajectory.showSupporting", { count: dependencies.length }), "topology-toggle");
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", String(expanded));
  toggle.setAttribute("data-focus-key", `toggle:${item.ref}`);
  toggle.addEventListener("click", () => toggleTopologyBranch(item.ref));
  target.append(toggle);
  if (!expanded) return;

  const byId = new Map(
    topologyDirectionItems(data)
      .filter((candidate) => isUserFacingDirection(candidate))
      .map((candidate) => [candidate.raw.id, candidate]),
  );
  const list = document.createElement("div");
  list.className = "topology-branch-list";
  list.setAttribute("role", "list");
  for (const dependencyId of dependencies) {
    const dependency = byId.get(dependencyId);
    if (!dependency) continue;
    const branch = document.createElement("article");
    branch.className = `topology-branch${selection.focus_ref === dependency.ref ? " selected" : ""}`;
    branch.setAttribute("role", "listitem");
    const select = text("button", dependency.title, "topology-branch-select");
    select.type = "button";
    select.setAttribute("data-focus-key", dependency.ref);
    select.setAttribute("aria-label", t("trajectory.choose", { value: dependency.title }));
    const dependencyPath = [...path, dependency.ref];
    select.addEventListener("click", () => selectTopologyDetail(dependencyPath));
    branch.append(select);
    if (dependency.owner) branch.append(text("p", t("trajectory.owner", { value: dependency.owner }), "topology-branch-meta"));
    if (dependency.focus !== t("trajectory.focusUnavailable")) branch.append(text("p", dependency.focus, "topology-branch-focus"));
    renderTopologyBranches(data, dependency, branch, dependencyPath);
    list.append(branch);
  }
  target.append(list);
}

function renderDirectionCard(item, target, listKey = "directions", data = null) {
  const card = document.createElement("article");
  card.className = `direction-card${selection.focus_ref === item.ref ? " selected" : ""}`;
  const button = text("button", item.title, "direction-select");
  button.type = "button";
  button.setAttribute("data-focus-key", item.ref);
  button.setAttribute("aria-pressed", String(selection.focus_ref === item.ref));
  button.setAttribute("aria-label", t("trajectory.choose", { value: item.title }));
  button.addEventListener("click", () => selectDetail(item.ref, listKey, pageFor(listKey)));
  const head = document.createElement("div");
  head.className = "direction-head";
  head.append(button, badge(item.state));
  card.append(head, text("p", t("trajectory.owner", { value: item.owner }), "direction-meta"), text("p", t("trajectory.relationship", { value: item.relationship }), "direction-meta"), text("p", t("trajectory.focus", { value: item.focus }), "direction-focus"));
  if (item.next && item.next !== t("trajectory.nextFocusEmpty")) card.append(text("p", t("trajectory.next", { value: item.next }), "direction-next"));
  if (data && item.raw?.source_kind === "master_goal_topology") renderTopologyBranches(data, item, card);
  target.append(card);
}

function renderTrajectoryLens(data, target) {
  const surface = createSurface("trajectory.heading", "trajectory.intro");
  const board = document.createElement("div");
  board.className = "trajectory-board";
  const master = document.createElement("div");
  master.className = "trajectory-master";
  renderMasterNode(data, master);
  const directions = document.createElement("section");
  directions.className = "directions-section";
  directions.append(text("p", t("trajectory.directions"), "panel-label"));
  const list = document.createElement("div");
  list.className = "direction-list";
  const windowed = dashboardUI.pageWindow(trajectoryDirectionItems(data), pageFor("directions"), MAX_DIRECTIONS, selection.focus_ref);
  for (const item of windowed.items) renderDirectionCard(item, list, "directions", data);
  if (!windowed.items.length) list.append(text("p", t("trajectory.empty"), "empty-copy"));
  directions.append(list);
  showPageControls(directions, "directions", windowed);
  board.append(master, directions);
  surface.body.append(board);
  target.append(surface.panel);
}

function pressureItems(data) {
  return arrayOrEmpty(data?.pressure_inbox?.items).map((item, index) => ({
    ...item,
    ref: `pressure:${item.pressure_ref?.id || item.pressure_ref?.ref || index}`,
  }));
}

function renderAttentionLens(data, target) {
  const surface = createSurface("attention.heading", "attention.intro");
  const list = document.createElement("div");
  list.className = "attention-list";
  const items = directionItems(data).filter((item) => item.ref.startsWith("pressure:"));
  const windowed = dashboardUI.pageWindow(items, pageFor("attention"), MAX_DIRECTIONS, selection.focus_ref);
  for (const item of windowed.items) {
    const card = document.createElement("article");
    card.className = `attention-card${selection.focus_ref === item.ref ? " selected" : ""}`;
    const select = text("button", item.title, "direction-select");
    select.type = "button";
    select.setAttribute("data-focus-key", item.ref);
    select.setAttribute("aria-label", t("attention.inspect"));
    select.addEventListener("click", () => selectDetail(item.ref, "attention", pageFor("attention")));
    card.append(select, badge(item.state), text("p", t("attention.owner", { value: item.owner }), "direction-meta"), text("p", t("attention.consequence", { value: item.focus }), "direction-focus"), text("p", t("attention.route", { value: item.next }), "direction-next"));
    list.append(card);
  }
  if (!items.length) list.append(text("p", workspaceNeedsReview(data) ? t("attention.needsReview") : t("attention.noPressure"), "empty-copy"));
  surface.body.append(list);
  showPageControls(surface.body, "attention", windowed);
  if (windowed.omitted) surface.body.append(text("p", t("attention.more", { count: windowed.total - windowed.items.length }), "panel-intro"));
  target.append(surface.panel);
}

function renderParticipantsLens(data, target) {
  const surface = createSurface("participants.heading", "participants.intro");
  const list = document.createElement("div");
  list.className = "participant-grid";
  const people = participantItems(data);
  const assignments = participantAssignmentItems(data);
  const entries = [...people, ...assignments];
  const windowed = dashboardUI.pageWindow(entries, pageFor("people"), MAX_PEOPLE, selection.focus_ref);
  for (const person of windowed.items) {
    const card = document.createElement("article");
    card.className = `participant-card${person.kind === "assignment" ? " assignment-card" : ""}${selection.focus_ref === person.ref ? " selected" : ""}`;
    const select = text("button", person.title, "direction-select");
    select.type = "button";
    select.setAttribute("data-focus-key", person.ref);
    select.setAttribute("aria-label", person.kind === "assignment" ? t("participants.assignmentInspect") : t("participants.inspect", { value: person.title }));
    select.addEventListener("click", () => selectDetail(person.ref, "people", pageFor("people")));
    card.append(select, badge(person.state));
    if (person.kind === "assignment") {
      card.append(
        text("p", t("participants.assignmentState", { value: statusLabel(person.state) }), "direction-meta"),
        text("p", t("participants.assignmentRole", { value: person.role }), "direction-meta"),
        text("p", t("participants.assignmentTask", { value: person.task }), "direction-focus"),
      );
    } else {
      card.append(text("p", t("participants.role", { value: person.role }), "direction-meta"), text("p", t("participants.task", { value: person.task }), "direction-focus"));
    }
    list.append(card);
  }
  if (!windowed.items.length) {
    const participantState = data?.participant_context?.state || data?.actor_activity?.state;
    const aggregateCount = data?.participant_context?.summary?.aggregate_count;
    const aggregateLabel = aggregateCount == null ? "" : `: ${aggregateCount}`;
    const graphState = participantGraph(data).state;
    const message = participantState === "invalid"
      ? t("participants.aggregateUnavailable", { count: aggregateLabel })
      : graphState === "deferred"
        ? t("participants.assignmentDeferred")
        : graphState === "missing" || graphState === "current"
          ? t("participants.assignmentMissing")
          : graphState === "invalid" || graphState === "stale" || graphState === "unknown"
            ? t("participants.assignmentUnavailable")
            : t("participants.unknown");
    list.append(text("p", message, "empty-copy"));
  }
  surface.body.append(list);
  showPageControls(surface.body, "people", windowed);
  if (windowed.omitted) surface.body.append(text("p", t("participants.more", { count: windowed.total - windowed.items.length }), "panel-intro"));
  if (people.length && participantGraph(data).state === "deferred") surface.body.append(text("p", t("participants.assignmentDeferred"), "participant-state-note"));
  target.append(surface.panel);
}

function renderEvidenceLens(data, target) {
  const surface = createSurface("evidence.heading", "evidence.intro");
  const list = document.createElement("div");
  list.className = "source-list";
  const sources = sourceItems(data);
  const windowed = dashboardUI.pageWindow(sources, pageFor("sources"), MAX_SOURCES, selection.focus_ref);
  for (const item of windowed.items) {
    const ref = item.ref;
    const card = document.createElement("article");
    card.className = `source-item${selection.focus_ref === ref ? " selected" : ""}`;
    const select = text("button", item.title, "direction-select");
    select.type = "button";
    select.setAttribute("data-focus-key", ref);
    select.setAttribute("aria-label", t("evidence.inspect", { value: item.title }));
    select.addEventListener("click", () => selectDetail(ref, "sources", pageFor("sources")));
    const freshness = observedAt(item.raw) ? formatHumanRecency(observedAt(item.raw)) : t("time.unknown");
    card.append(select, badge(item.state), text("p", t("evidence.sourceState", { owner: item.owner, state: statusLabel(item.state) }), "direction-meta"), text("p", t("evidence.sourceFreshness", { value: freshness }), "direction-focus"));
    list.append(card);
  }
  if (!windowed.items.length) list.append(text("p", t("evidence.sourceMissing"), "empty-copy"));
  surface.body.append(list);
  showPageControls(surface.body, "sources", windowed);
  if (windowed.omitted) surface.body.append(text("p", t("evidence.more", { count: windowed.total - windowed.items.length }), "panel-intro"));
  target.append(surface.panel);
}

function renderRecordsLens(data, target) {
  const surface = createSurface("records.heading", "records.intro");
  const annotations = recordInfo(data, "annotations");
  const intents = recordInfo(data, "action_intents");
  const grid = document.createElement("div");
  grid.className = "record-grid";
  const add = (label, record, key) => {
    const count = record.count == null ? t("records.empty") : t("records.count", { count: record.count });
    const card = document.createElement("article");
    card.className = "record-card";
    card.append(text("p", label, "card-label"), text("strong", count, "summary-value"), badge(record.state || "unknown"), text("p", record.latest?.length ? t("records.inspect") : t("records.empty"), "summary-detail"));
    grid.append(card);
  };
  add(t("records.annotations"), annotations, "annotations");
  add(t("records.requests"), intents, "intents");
  surface.body.append(grid);
  target.append(surface.panel);
}

function safeDiagnosticValue(value, depth = 0) {
  if (depth > 5 || value === null || value === undefined) return value;
  if (Array.isArray(value)) return value.slice(0, 24).map((item) => safeDiagnosticValue(item, depth + 1));
  if (typeof value !== "object") return typeof value === "string" && value.length > 800 ? `${value.slice(0, 797)}…` : value;
  const result = {};
  for (const [key, child] of Object.entries(value).slice(0, 40)) {
    if (["body", "raw", "text", "payload"].includes(key)) continue;
    result[key] = safeDiagnosticValue(child, depth + 1);
  }
  return result;
}

function diagnosticEntries(data, context = contextForSelection(data)) {
  const entries = [];
  const currentness = data?.correlation?.master_filter?.currentness || {};
  const refs = [...arrayOrEmpty(context?.evidence_refs), ...arrayOrEmpty(data?.goal?.source_refs), ...arrayOrEmpty(data?.correlation?.evidence_refs), ...arrayOrEmpty(currentness.evidence_refs)].filter(Boolean).slice(0, MAX_REFS);
  entries.push({ label: context?.title || goalTitle(data), refs, value: safeDiagnosticValue(context?.raw || { goal: data?.goal, currentness: currentnessForData(data) }) });
  if (context?.ref?.startsWith("pressure:")) entries.push({ label: t("attention.heading"), refs: arrayOrEmpty(context.raw?.evidence), value: safeDiagnosticValue(context.raw) });
  if (context?.ref?.startsWith("actor:")) entries.push({ label: t("participants.heading"), refs: arrayOrEmpty(context.raw?.evidence_refs), value: safeDiagnosticValue(context.raw) });
  if (data?.owner_goal_context && typeof data.owner_goal_context === "object") {
    entries.push({
      label: t("thread.ownerContext"),
      refs: arrayOrEmpty(data.owner_goal_context.evidence_refs).slice(0, MAX_REFS),
      value: safeDiagnosticValue({ owner_goal_context: data.owner_goal_context, participant_context: data.participant_context }),
    });
  }
  if (data?.goal_context && typeof data.goal_context === "object") {
    const threadBoard = data.goal_context.thread_board || {};
    const graph = data.goal_context.participant_graph || {};
    entries.push({
      label: t("thread.boardHeading"),
      refs: [...arrayOrEmpty(threadBoard.evidence_refs), ...arrayOrEmpty(graph.evidence_refs)].slice(0, MAX_REFS),
      value: safeDiagnosticValue({
        state: data.goal_context.state,
        thread_board: { state: threadBoard.state, relation_state: threadBoard.relation_state, diagnostics: threadBoard.diagnostics, source: threadBoard.source },
        participant_graph: { state: graph.state, records: graph.records, diagnostics: graph.diagnostics, source: graph.source },
        claim_limit: data.goal_context.claim_limit,
      }),
    });
  }
  if (data?.goal_topology?.state === "bound") {
    entries.push({
      label: t("diagnostics.goalTopology"),
      refs: arrayOrEmpty(data.goal_topology.evidence_refs).slice(0, MAX_REFS),
      value: safeDiagnosticValue({ goal_topology: data.goal_topology }),
    });
  }
  return entries;
}

function renderDiagnosticRoutes(data, target) {
  if (!target) return;
  const context = contextForSelection(data);
  const inspector = document.createElement("details");
  inspector.className = "diagnostics-inspector";
  inspector.dataset.detailKey = "diagnostics:selection";
  inspector.append(text("summary", t("diagnostics.summary")));
  const body = document.createElement("div");
  body.className = "diagnostics-body";
  body.append(text("p", t("diagnostics.description"), "panel-intro"));
  const entries = diagnosticEntries(data, context);
  for (const entry of entries) {
    const item = document.createElement("section");
    item.className = "diagnostic-entry";
    item.append(text("h3", entry.label));
    const developer = document.createElement("details");
    developer.className = "developer-details";
    developer.append(text("summary", t("diagnostics.developer")));
    developer.addEventListener("toggle", () => {
      if (!developer.open || developer.dataset.loaded === "true") return;
      developer.dataset.loaded = "true";
      developer.append(evidenceList(entry.refs), text("p", t("diagnostics.raw"), "panel-intro"), text("pre", JSON.stringify(entry.value, null, 2)));
    });
    item.append(developer);
    body.append(item);
  }
  if (!entries.length) body.append(text("p", t("diagnostics.empty"), "empty-copy"));
  inspector.append(body);
  target.append(inspector);
}

function renderOwnerThreadDetails(data, target) {
  const owner = data?.owner_goal_context;
  if (!owner || typeof owner !== "object") return;
  const details = document.createElement("details");
  details.className = "owner-context-details";
  details.append(text("summary", t("thread.ownerContext")));
  const body = document.createElement("div");
  body.className = "owner-context-body";
  const thread = owner.thread || {};
  body.append(text("p", thread.state === "bound" ? t("thread.ownerThreadAvailable") : t("thread.ownerThreadUnavailable"), "context-detail"));
  const relations = [
    ["spawn_parent", "thread.spawnParent"],
    ["history_fork", "thread.historyFork"],
  ];
  for (const [kind, labelKey] of relations) {
    const relation = owner.relations?.[kind] || {};
    const label = t(labelKey);
    const items = arrayOrEmpty(relation.items);
    const summary = relation.state === "bound" && relation.complete_for_query && items.length
      ? t("thread.relationObserved", { label, count: items.length })
      : relation.state === "deferred"
        ? t("thread.relationDeferred", { label })
        : relation.state === "bound"
          ? t("thread.relationNone", { label })
          : t("thread.relationUnavailable", { label });
    body.append(text("p", summary, "context-detail"));
  }
  details.append(body);
  target.append(details);
}

function threadBoardNotice(state) {
  const key = {
    current: "thread.boardCurrent",
    missing: "thread.boardMissing",
    unknown: "thread.boardUnknown",
    stale: "thread.boardStale",
    deferred: "thread.boardDeferred",
    invalid: "thread.boardInvalid",
  }[state] || "thread.boardUnknown";
  return t(key);
}

function renderGoalThreadBoard(data, target) {
  const board = goalThreadBoard(data);
  const section = document.createElement("section");
  section.className = "thread-board";
  const heading = document.createElement("div");
  heading.className = "thread-board-heading";
  heading.append(text("h3", t("thread.boardHeading")), badge(contextDisplayState(board.state)));
  section.append(heading, text("p", threadBoardNotice(board.state), "context-detail"));

  const items = goalThreadItems(data);
  if (items.length) {
    const list = document.createElement("div");
    list.className = "thread-board-list";
    for (const item of items.slice(0, 6)) {
      const button = text("button", item.title, "thread-board-item");
      button.type = "button";
      button.setAttribute("data-focus-key", item.ref);
      button.setAttribute("aria-label", t("thread.selection", { value: item.title }));
      button.addEventListener("click", () => selectDetail(item.ref, "thread", pageFor("thread")));
      list.append(button);
    }
    section.append(list);
  } else if (board.state === "current") section.append(text("p", t("thread.boardEmpty"), "context-detail"));

  const relationState = board.relation_state;
  const relations = goalThreadRelationItems(data);
  if (relations.length && ["complete", "available"].includes(relationState)) section.append(text("p", t("thread.boardRelationsObserved", { count: relations.length }), "context-detail"));
  else if (relationState === "deferred") section.append(text("p", t("thread.boardRelationsDeferred"), "context-detail"));
  else if (relationState !== "missing" && board.state === "current") section.append(text("p", t("thread.boardRelationsUnavailable"), "context-detail"));
  if (board.branch?.state === "missing") section.append(text("p", t("thread.boardNoBranch"), "context-detail"));
  section.append(text("p", t("thread.boardOrder"), "context-detail"));

  const details = document.createElement("details");
  details.className = "thread-board-details";
  details.dataset.detailKey = "thread-board:source";
  details.append(text("summary", t("thread.boardDetails")));
  const body = document.createElement("div");
  body.className = "thread-board-detail-body";
  body.append(evidenceList(board.evidence_refs), text("p", t("thread.metadata"), "context-detail"));
  details.append(body);
  section.append(details);
  target.append(section);
}

function renderThread(data) {
  const target = byId("thread-items");
  clear(target);
  const context = contextForSelection(data);
  const quality = byId("thread-quality");
  setBadge(quality, context ? (context.evidence_refs?.length ? "present" : context.state) : contextDisplayState(goalThreadBoard(data).state));
  const selectionLabel = byId("thread-selection");
  if (selectionLabel) selectionLabel.textContent = context ? context.title : t("thread.noSelection");
  target.append(text("p", t("thread.deferredNotice"), "thread-deferred"));
  renderGoalThreadBoard(data, target);
  if (!context) target.append(text("p", t("thread.noSelection"), "empty-state"));
  else {
    const card = document.createElement("article");
    card.className = "context-card";
    const contextLabel = context.kind === "person"
      ? t("thread.person")
      : context.kind === "source"
        ? t("evidence.heading")
        : context.kind === "assignment"
          ? t("thread.assignment")
          : context.kind === "thread_item"
            ? t("thread.boardItem")
            : context.kind === "thread_relation"
              ? t("thread.boardRelation")
              : t("thread.direction");
    card.append(text("p", contextLabel, "card-label"), text("h3", context.title));
    if (statusLabel(context.state) !== statusLabel("unknown")) card.append(badge(context.state));
    if (context.owner) card.append(text("p", t("thread.owner", { value: context.owner }), "context-detail"));
    card.append(text("p", t("thread.relationship", { value: context.relationship }), "context-detail"), text("p", t("thread.focus", { value: context.focus }), "context-focus"));
    if (context.kind === "person") {
      card.append(text("p", t("thread.role", { value: context.role }), "context-detail"));
      if (context.model) card.append(text("p", t("thread.model", { value: context.model }), "context-detail"));
      else if (context.model_state) card.append(text("p", t("thread.modelUnavailable"), "context-detail"));
      card.append(text("p", t("thread.task", { value: context.task }), "context-focus"));
    } else if (context.kind === "assignment") {
      card.append(
        text("p", t("participants.assignmentRole", { value: context.role }), "context-detail"),
        text("p", t("participants.assignmentTask", { value: context.task }), "context-focus"),
        text("p", t("participants.assignmentModel", { value: context.model }), "context-detail"),
        text("p", t("participants.assignmentRuntime", { value: context.runtime }), "context-detail"),
      );
    }
    card.append(text("p", `${t("thread.evidence")}: ${context.evidence_refs?.length ? statusLabel("present") : statusLabel("unknown")}`, "context-detail"));
    target.append(card);
    renderOwnerThreadDetails(data, target);
  }
  const operate = byId("operate-panel");
  if (operate) operate.classList.toggle("hidden", workspaceMode !== "operate");
  const routeCard = byId("operate-route-card");
  if (routeCard) renderOperateRoute(data, routeCard, context);
  setFormTargets(selection.goal_ref || "goal:unknown");
}

function routeMatchesSelection(item, selected = selection) {
  if (!selected.goal_ref || !item) return false;
  const itemGoal = item.goal_id || item.goal_ref || item.goal?.goal_id;
  if (!itemGoal || itemGoal !== selected.goal_ref) return false;
  const itemThread = item.thread_ref || item.master_thread_id || item.context_thread_ref;
  if (selected.thread_ref && itemThread !== selected.thread_ref) return false;
  if (!selected.focus_ref) return true;
  const ref = item.pressure_ref || {};
  return [item.context_ref, item.target_ref, item.focus_ref, ref.id, ref.ref, `pressure:${ref.id || ref.ref || ""}`].filter(Boolean).includes(selected.focus_ref);
}

function routeReadiness(item, selected = selection) {
  if (!routeMatchesSelection(item, selected)) return { ready: false, reason: "context" };
  const route = item.next_route || {};
  const currentness = route.currentness || item.currentness || item.pressure_ref?.currentness;
  const ready = Boolean(route.owner && route.route && route.effect === "none" && route.authority && item.stop_line && item.wake_condition && arrayOrEmpty(item.evidence).length && ADMITTED_ROUTE_CURRENTNESS.has(currentness));
  return { ready, route, currentness, reason: ready ? null : "contract" };
}

function selectedOperateRoute(data) {
  return pressureItems(data).map((item) => ({ item, readiness: routeReadiness(item) })).find((candidate) => candidate.readiness.ready) || null;
}

function renderOperateRoute(data, target, context) {
  clear(target);
  const candidate = selectedOperateRoute(data);
  const route = candidate?.readiness?.route || {};
  const item = candidate?.item;
  target.className = `operate-route-card ${candidate?.readiness?.ready ? "route-ready" : "route-missing"}`;
  target.append(text("strong", candidate?.readiness?.ready ? t("operate.routeReady") : t("operate.routeMissing")), text("span", t("operate.owner", { value: humanOwner(route.owner, context?.owner || t("trajectory.master")) }), "context-detail"), text("span", t("operate.effect"), "context-detail"));
  if (item) target.append(text("span", t("operate.stopRecorded"), "context-detail"), text("span", t("operate.returnRecorded"), "context-detail"));
}

function setFormTargets(targetRef) {
  for (const form of [byId("annotation-form"), byId("intent-form")]) {
    const input = form?.querySelector?.('input[name="target_ref"]');
    if (input) input.value = targetRef;
  }
}

function renderLens(data) {
  const target = byId("lens-surface");
  clear(target);
  if (selection.lens === "attention") renderAttentionLens(data, target);
  else if (selection.lens === "participants") renderParticipantsLens(data, target);
  else if (selection.lens === "evidence") renderEvidenceLens(data, target);
  else if (selection.lens === "records") renderRecordsLens(data, target);
  else renderTrajectoryLens(data, target);
}

function renderDiagnosticsSurface(data) {
  const target = byId("diagnostics-surface");
  clear(target);
  if (selection.focus_ref || selection.lens === "evidence") renderDiagnosticRoutes(data, target);
}

function knownFocusRefs(data) {
  return new Set([...primaryDirectionItems(data).map((item) => item.ref), ...directionItems(data).map((item) => item.ref), ...topologyDirectionItems(data).map((item) => item.ref), ...participantItems(data).map((item) => item.ref), ...participantAssignmentItems(data).map((item) => item.ref), ...goalThreadItems(data).map((item) => item.ref), ...goalThreadRelationItems(data).map((item) => item.ref), ...arrayOrEmpty(data.sources).map((item) => `source:${item.id || "unknown"}`)]);
}

function renderProjection(data) {
  interactionState = captureInteractionState();
  renderRefreshState(data);
  renderRouteState();
  renderHome(data);
  const selectedCurrentGoal = selectedCurrentGoalForData(data);
  const selectedCatalogItem = selectedCurrentGoal ? null : catalogItemForRef(data, selection.goal_ref);
  const selectedCatalogGoal = Boolean(selection.goal_ref && selectedCatalogItem);
  const selectedUnavailableGoal = Boolean(selection.goal_ref && !selectedCurrentGoal && !selectedCatalogItem);
  byId("workspace-view")?.classList.toggle("hidden", !selectedCurrentGoal);
  byId("catalog-workspace-view")?.classList.toggle("hidden", !(selectedCatalogGoal || selectedUnavailableGoal));
  byId("home-view")?.classList.toggle("hidden", Boolean(selectedCurrentGoal || selectedCatalogGoal || selectedUnavailableGoal));
  byId("fallback-evidence")?.classList.toggle("hidden", Boolean(data));
  if (selectedCurrentGoal) {
    renderHeader(data);
    renderBreadcrumb(data);
    renderGoalSummary(data);
    renderAttentionStrip(data);
    const rail = byId("rail-quality");
    clear(rail);
    if (rail) rail.append(badge(qualityForData(data)), text("p", statusLabel(currentnessForData(data)), "rail-detail"));
    renderLens(data);
    renderDiagnosticsSurface(data);
    renderThread(data);
  } else if (selectedCatalogGoal || selectedUnavailableGoal) renderCatalogWorkspace(data, selectedCatalogItem);
  updateLensButtons();
  updateModeButtons();
  restoreInteractionState(interactionState);
}

function renderNoProjection() {
  renderRefreshState();
  byId("workspace-view")?.classList.add("hidden");
  byId("catalog-workspace-view")?.classList.add("hidden");
  byId("home-view")?.classList.remove("hidden");
  clear(byId("goal-selector"));
  const catalog = byId("catalog-state");
  if (catalog) { catalog.className = "empty-state state-invalid"; catalog.append(badge("invalid"), text("span", t("refresh.disconnected"))); }
}

async function refresh() {
  if (refreshInFlight) return;
  refreshInFlight = true;
  if (!currentProjection) { refreshState = "loading"; renderRefreshState(); }
  setProjectionBusy(true);
  try {
    const query = selection.goal_ref ? `?goal_ref=${encodeURIComponent(selection.goal_ref)}` : "";
    const response = await fetch(`/api/projection${query}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || t("refresh.failed"));
    const wasDegraded = refreshState !== "current" || !byId("alert")?.classList.contains("hidden");
    currentProjection = data;
    lastGoodProjection = data;
    lastGoodAt = data.generated_at || new Date();
    refreshState = "current";
    if (selection.goal_ref && selection.goal_ref !== goalRef(data) && !catalogItemForRef(data, selection.goal_ref)) selectionQuality = "missing";
    else if (selection.focus_ref && !knownFocusRefs(data).has(selection.focus_ref)) selectionQuality = "stale";
    else if (selectionQuality === "missing" || selectionQuality === "stale") selectionQuality = null;
    selection.observation_cursor_or_generation = data.generated_at || null;
    renderProjection(data);
    clearAlert();
    setProjectionBusy(false);
    if (wasDegraded) announce(selectedCurrentGoalForData(data) && workspaceNeedsReview(data) ? t("refresh.needsReviewAnnouncement") : t("refresh.updated"));
  } catch (error) {
    const alert = byId("alert");
    if (alert) { alert.textContent = t("refresh.failed"); alert.classList.remove("hidden"); }
    refreshState = lastGoodProjection ? "stale" : "disconnected";
    currentProjection = lastGoodProjection;
    if (currentProjection) renderProjection(currentProjection); else renderNoProjection();
    setProjectionBusy(false);
    announce(t("refresh.failed"));
  } finally {
    refreshInFlight = false;
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
  try {
    const body = Object.fromEntries(new FormData(form).entries());
    const response = await fetch(route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || t("form.submitFailed"));
    form.reset();
    if (status) status.textContent = t("form.submitSuccess");
    await refresh();
  } catch (_error) {
    if (status) status.textContent = t("form.submitFailed");
  } finally {
    form.dataset.submitting = "false";
    if (button) { button.disabled = false; button.textContent = original || t("form.recordAnnotation"); }
  }
}

for (const button of document.querySelectorAll("[data-language]")) button.addEventListener("click", () => i18n.setLanguage(button.dataset.language));
for (const button of document.querySelectorAll("[data-lens]")) button.addEventListener("click", () => setSelection({ lens: button.dataset.lens }));
for (const button of document.querySelectorAll("[data-mode]")) button.addEventListener("click", () => { workspaceMode = button.dataset.mode === "operate" ? "operate" : "observe"; updateModeButtons(); if (currentProjection) renderThread(currentProjection); });
byId("home-button")?.addEventListener("click", () => { contextThreadOpen = false; setSelection({ goal_ref: null, focus_ref: null, branch_path: [], thread_ref: null }); });
byId("catalog-workspace-back")?.addEventListener("click", () => { contextThreadOpen = false; setSelection({ goal_ref: null, focus_ref: null, branch_path: [], thread_ref: null }); byId("home-heading")?.focus?.(); });
byId("thread-toggle")?.addEventListener("click", () => { contextThreadOpen = !contextThreadOpen; updateThreadVisibility(); });
byId("density-mode")?.addEventListener("change", (event) => {
  const value = event.currentTarget.value;
  if (PRESENTATION_DENSITIES.has(value)) window.AoaDashboardTheme?.setDensity?.(value);
});
i18n.subscribe(() => {
  applyStaticTranslations();
  if (currentProjection) renderProjection(currentProjection);
  publishNativePresentationPreference();
});
window.AoaDashboardTheme?.subscribe?.(() => {
  const density = byId("density-mode");
  if (density && window.AoaDashboardTheme?.getDensity) density.value = window.AoaDashboardTheme.getDensity();
  publishNativePresentationPreference();
});
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
  routeMatchesSelection,
  routeReadiness,
  formatHumanRecency,
  formatAbsoluteMinute,
  currentOwnerGoal,
  goalTitle,
  compactGoalTitle,
  compactDisplayText,
  goalRef,
  qualityForData,
  workspaceNeedsReview,
  lifecycleForData,
  nextFocus,
  attentionFocus,
  directionItems,
  trajectoryDirectionItems,
  primaryDirectionItems,
  topologyDirectionItems,
  participantItems,
  participantAssignmentItems,
  goalThreadItems,
  goalThreadRelationItems,
  sourceItems,
  contextForRef,
  knownFocusRefs,
  diagnosticEntries,
  catalogItemForRef,
  renderDiagnosticRoutes,
  renderTrajectoryLens,
  renderParticipantsLens,
  renderGoalThreadBoard,
  renderThread,
  renderHome,
  renderCatalogWorkspace,
  renderProjection,
  refresh,
  getSelection: () => ({ ...selection, branch_path: [...selection.branch_path], expanded_branch_refs: [...selection.expanded_branch_refs], page_by_list: { ...selection.page_by_list } }),
});

refresh();
setInterval(refresh, 5000);
