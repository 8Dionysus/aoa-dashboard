(function exposeDashboardUiState(root) {
  "use strict";

  const LENSES = ["trajectory", "attention", "participants", "evidence", "records"];
  const QUALITY = ["missing", "unknown", "stale", "deferred", "invalid"];
  const MAX_CONTEXT_ITEMS = 32;
  const MAX_CONTEXT_STRING = 512;
  const CATALOG_SCHEMA = "aoa_dashboard_goal_catalog_projection_v1";
  const CATALOG_GROUPS = ["active", "attention", "paused", "completed"];
  const CATALOG_CURRENTNESS = ["current", "stale", "deferred", "unknown", "invalid"];

  function textOrNull(value, limit = MAX_CONTEXT_STRING) {
    if (value === null || value === undefined || value === "") return null;
    const text = String(value);
    return text ? text.slice(0, limit) : null;
  }

  function boundedStrings(value) {
    if (!Array.isArray(value)) return [];
    return value
      .map((item) => textOrNull(item))
      .filter(Boolean)
      .slice(0, MAX_CONTEXT_ITEMS);
  }

  function boundedPages(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return {};
    const result = {};
    for (const [key, page] of Object.entries(value).slice(0, MAX_CONTEXT_ITEMS)) {
      if (!/^[a-z][a-z0-9_-]{0,40}$/.test(key)) continue;
      const number = Number(page);
      if (Number.isInteger(number) && number >= 0 && number <= 100000) result[key] = number;
    }
    return result;
  }

  function emptySelection() {
    return {
      goal_ref: null,
      lens: "trajectory",
      focus_ref: null,
      branch_path: [],
      thread_ref: null,
      expanded_branch_refs: [],
      page_by_list: {},
      observation_cursor_or_generation: null,
    };
  }

  function normalizeSelection(value = {}) {
    const source = value && typeof value === "object" ? value : {};
    const selection = emptySelection();
    selection.goal_ref = textOrNull(source.goal_ref);
    selection.lens = LENSES.includes(source.lens) ? source.lens : "trajectory";
    selection.focus_ref = textOrNull(source.focus_ref);
    selection.branch_path = boundedStrings(source.branch_path);
    selection.thread_ref = textOrNull(source.thread_ref);
    selection.expanded_branch_refs = boundedStrings(source.expanded_branch_refs);
    selection.page_by_list = boundedPages(source.page_by_list);
    selection.observation_cursor_or_generation = textOrNull(source.observation_cursor_or_generation);
    if (selection.goal_ref && !selection.thread_ref) selection.thread_ref = selection.goal_ref;
    if (selection.focus_ref && !selection.branch_path.length) selection.branch_path = [selection.focus_ref];
    return selection;
  }

  function routePayload(selection) {
    const normalized = normalizeSelection(selection);
    return {
      goal_ref: normalized.goal_ref,
      lens: normalized.lens,
      focus_ref: normalized.focus_ref,
      branch_path: normalized.branch_path,
      thread_ref: normalized.thread_ref,
      expanded_branch_refs: normalized.expanded_branch_refs,
      page_by_list: normalized.page_by_list,
      observation_cursor_or_generation: normalized.observation_cursor_or_generation,
    };
  }

  function encodeRoute(selection) {
    const normalized = normalizeSelection(selection);
    if (!normalized.goal_ref) return "#";
    const payload = encodeURIComponent(JSON.stringify(routePayload(normalized)));
    return `#goal/${encodeURIComponent(normalized.goal_ref)}/${normalized.lens}?context=${payload}`;
  }

  function failRoute(error) {
    return { status: "invalid", error: String(error || "malformed route"), selection: emptySelection() };
  }

  function decodeRoute(raw) {
    if (!raw || raw === "#") return { status: "home", error: null, selection: emptySelection() };
    if (typeof raw !== "string") return failRoute("route is not text");
    const match = raw.match(/^#goal\/([^/?]+)\/([^?]+)(?:\?(.+))?$/);
    if (!match) return failRoute("route shape is invalid");
    try {
      const goalRef = decodeURIComponent(match[1]);
      const lens = decodeURIComponent(match[2]);
      if (!goalRef || !LENSES.includes(lens)) return failRoute("route context is not admitted");
      const params = new URLSearchParams(match[3] || "");
      let payload = {};
      const encodedContext = params.get("context");
      if (encodedContext) {
        payload = JSON.parse(encodedContext);
        if (!payload || typeof payload !== "object" || Array.isArray(payload)) return failRoute("route context is not an object");
        if (payload.goal_ref && String(payload.goal_ref) !== goalRef) return failRoute("route Goal refs disagree");
      } else {
        // Read the pre-repair route shape so old bookmarks fail closed only when malformed.
        payload = {
          goal_ref: goalRef,
          lens,
          focus_ref: params.get("focus"),
          thread_ref: params.get("thread"),
          branch_path: params.get("branch") ? params.get("branch").split(",") : [],
          expanded_branch_refs: params.get("expanded") ? params.get("expanded").split(",") : [],
          page_by_list: params.get("pages") ? JSON.parse(params.get("pages")) : {},
          observation_cursor_or_generation: params.get("generation"),
        };
      }
      const selection = normalizeSelection({ ...payload, goal_ref: goalRef, lens });
      return { status: "valid", error: null, selection };
    } catch (error) {
      return failRoute(error && error.message ? error.message : "route decoding failed");
    }
  }

  function pageWindow(values, page, pageSize, selectedRef = null) {
    const items = Array.isArray(values) ? values : [];
    const size = Number.isInteger(pageSize) && pageSize > 0 ? pageSize : 1;
    const pageCount = Math.max(1, Math.ceil(items.length / size));
    let current = Number.isInteger(page) && page >= 0 ? page : 0;
    if (selectedRef) {
      const selectedIndex = items.findIndex((item) => item && item.ref === selectedRef);
      if (selectedIndex >= 0) current = Math.floor(selectedIndex / size);
    }
    current = Math.min(current, pageCount - 1);
    return {
      items: items.slice(current * size, (current + 1) * size),
      page: current,
      pageCount,
      total: items.length,
      omitted: Math.max(0, items.length - size),
      hasPrevious: current > 0,
      hasNext: current + 1 < pageCount,
    };
  }

  function qualifiedCatalog(candidate) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) {
      return { state: "missing", items: [], source: null, currentness: "missing", claim_limit: null, reason: "publisher_missing" };
    }
    const emptyState = ["missing", "invalid"].includes(candidate.state)
      && candidate.currentness === candidate.state
      && candidate.schema_version === CATALOG_SCHEMA
      && candidate.source === null
      && Array.isArray(candidate.items)
      && candidate.items.length === 0
      && typeof candidate.claim_limit === "string"
      && candidate.claim_limit.length > 0;
    if (emptyState) {
      return {
        state: candidate.state,
        items: [],
        source: null,
        currentness: candidate.state,
        claim_limit: candidate.claim_limit,
        reason: candidate.state === "missing" ? "publisher_missing" : "publisher_invalid",
      };
    }
    const source = candidate.source;
    const qualified = candidate.schema_version === CATALOG_SCHEMA
      && CATALOG_CURRENTNESS.includes(candidate.currentness)
      && candidate.state === candidate.currentness
      && source && typeof source === "object" && !Array.isArray(source)
      && source.owner === "aoa-session-memory"
      && source.ref === "aoa-session-memory:goal-lifecycles"
      && source.owner_schema_version === "aoa_session_memory_goal_catalog_v1"
      && source.currentness === candidate.currentness
      && Array.isArray(candidate.items)
      && candidate.items.length <= 500
      && typeof candidate.claim_limit === "string" && candidate.claim_limit.length > 0;
    if (!qualified) {
      return { state: "invalid", items: [], source: null, currentness: "invalid", claim_limit: null, reason: "publisher_unqualified" };
    }
    const refs = new Set();
    const items = [];
    for (const value of candidate.items) {
      if (!value || typeof value !== "object" || Array.isArray(value)) return { state: "invalid", items: [], source, currentness: "invalid", claim_limit: candidate.claim_limit, reason: "item_invalid" };
      const ref = textOrNull(value.ref, 160);
      const titleState = value.title_state;
      const title = value.title === null ? null : textOrNull(value.title, 96);
      if (!ref || refs.has(ref) || !CATALOG_GROUPS.includes(value.group) || !["available", "missing", "withheld"].includes(titleState)) {
        return { state: "invalid", items: [], source, currentness: "invalid", claim_limit: candidate.claim_limit, reason: "item_invalid" };
      }
      if ((titleState === "available" && !title) || (titleState !== "available" && title !== null)) {
        return { state: "invalid", items: [], source, currentness: "invalid", claim_limit: candidate.claim_limit, reason: "item_invalid" };
      }
      refs.add(ref);
      items.push({
        ref,
        title,
        title_state: titleState,
        lifecycle_state: textOrNull(value.lifecycle_state, 40) || "unknown",
        group: value.group,
        first_observed_at: textOrNull(value.first_observed_at, 40),
        last_observed_at: textOrNull(value.last_observed_at, 40),
        ambiguity: Boolean(value.ambiguity),
      });
    }
    return {
      state: candidate.state,
      items,
      source,
      currentness: candidate.currentness,
      claim_limit: candidate.claim_limit,
      counts_by_group: candidate.counts_by_group && typeof candidate.counts_by_group === "object" ? candidate.counts_by_group : {},
      reason: null,
    };
  }

  function optionalRecord(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return { state: "missing", count: null, latest: [], evidence_refs: [], claim_limit: null };
    }
    const hasCount = Number.isInteger(value.count) && value.count >= 0;
    const state = hasCount ? (value.state || "bound") : (QUALITY.includes(value.state) ? value.state : "unknown");
    const result = {
      state,
      count: hasCount ? value.count : null,
      latest: Array.isArray(value.latest) ? value.latest : [],
      evidence_refs: Array.isArray(value.evidence_refs) ? value.evidence_refs : [],
      claim_limit: typeof value.claim_limit === "string" ? value.claim_limit : null,
    };
    if (["missing", "unavailable", "present"].includes(value.availability)) result.availability = value.availability;
    return result;
  }

  root.AoaDashboardUiState = Object.freeze({
    LENSES: LENSES.slice(),
    QUALITY: QUALITY.slice(),
    SelectionContext: Object.freeze({
      fields: Object.freeze(["goal_ref", "lens", "focus_ref", "branch_path", "thread_ref", "expanded_branch_refs", "page_by_list", "observation_cursor_or_generation"]),
      empty: emptySelection,
      normalize: normalizeSelection,
    }),
    encodeRoute,
    decodeRoute,
    pageWindow,
    qualifiedCatalog,
    optionalRecord,
  });
}(typeof window === "undefined" ? globalThis : window));
