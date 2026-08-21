const { createI18n } = window.AoaDashboardI18n;
const i18n = createI18n();

const LIFECYCLE = [
  "planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "wake requested", "reentered",
];
const QUALITY = ["missing", "unknown", "stale", "deferred", "invalid"];
const PRESENTATION_HANDLER_NAME = "aoaDashboardPresentation";
const PRESENTATION_LANGUAGES = new Set(["en", "ru"]);
const PRESENTATION_THEMES = new Set(["system", "light", "dark"]);

let currentProjection = null;

const byId = (id) => document.getElementById(id);
const clear = (element) => { while (element.firstChild) element.removeChild(element.firstChild); };
const t = (key, variables = {}) => i18n.t(key, variables);
const statusLabel = (value) => i18n.status(value);

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

function applyStaticTranslations() {
  document.documentElement.lang = i18n.language;
  if (window.AoaDashboardTheme?.setLabels) {
    window.AoaDashboardTheme.setLabels({
      label: t("theme.label"),
      ariaLabel: t("theme.ariaLabel"),
      system: t("theme.system"),
      light: t("theme.light"),
      dark: t("theme.dark"),
    });
  }
  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  for (const node of document.querySelectorAll("[data-i18n-placeholder]")) {
    node.setAttribute("placeholder", t(node.dataset.i18nPlaceholder));
  }
  for (const node of document.querySelectorAll("[data-i18n-aria-label]")) {
    node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
  }
  for (const button of document.querySelectorAll("[data-language]")) {
    button.setAttribute("aria-pressed", String(button.dataset.language === i18n.language));
  }
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

function evidenceList(refs) {
  const list = document.createElement("div");
  list.className = "ref-list";
  for (const ref of refs || []) {
    if (!ref) continue;
    const digest = ref.sha256 ? ` · ${t("evidence.sha256", { value: ref.sha256 })}` : "";
    const observed = ref.observed_at ? ` · ${t("evidence.observed", { value: ref.observed_at })}` : "";
    const label = ref.label || ref.kind || t("evidence.ref");
    const location = ref.ref || ref.path || t("evidence.unresolved");
    const code = text("code", `${label}: ${location}${digest}${observed}`);
    list.append(code);
  }
  return list;
}

function renderHeader(data) {
  const goal = data.goal || {};
  byId("goal-title").textContent = goal.title || t("goal.unnamed");
  byId("goal-id").textContent = goal.goal_id || t("goal.idMissing");
  byId("goal-digest").textContent = goal.anchor_digest || t("goal.digestUnavailable");
  byId("goal-limit").textContent = goal.claim_limit || "";
  byId("generated").textContent = t("label.generated", { value: data.generated_at || t("fallback.unknown") });
  const connection = byId("connection");
  connection.textContent = t("connection.hostLocalRead");
  connection.className = "badge state-bound";
}

function renderInventory(data) {
  const target = byId("inventory");
  clear(target);
  for (const item of data.state_inventory || []) {
    const card = document.createElement("div");
    card.className = `inventory-item ${item.category === "lifecycle" ? "lifecycle" : "quality"}`;
    card.append(text("span", statusLabel(item.state), "label"));
    card.append(text("span", item.observed_count, "count"));
    card.append(text("span", item.observation, "note"));
    target.append(card);
  }
}

function renderLifecycle(data) {
  const target = byId("lifecycle");
  clear(target);
  for (const item of data.lifecycle || []) {
    const row = document.createElement("div");
    row.className = "timeline-row";
    row.append(text("div", item.step, "timeline-step"));
    const body = document.createElement("div");
    body.className = "timeline-body";
    body.append(badge(item.state));
    body.append(text("p", item.observation));
    body.append(evidenceList(item.evidence_refs));
    row.append(body);
    target.append(row);
  }
}

function renderDag(data) {
  const target = byId("dag");
  clear(target);
  for (const item of data.dag || []) {
    const row = document.createElement("div");
    row.className = "dag-row";
    row.append(text("div", item.id, "dag-id"));
    const body = document.createElement("div");
    body.className = "dag-body";
    const head = document.createElement("div");
    head.className = "dag-head";
    head.append(text("strong", item.title));
    head.append(badge(item.state));
    body.append(head);
    body.append(text("p", `${item.observation} ${t("label.pressure", { value: item.pressure })}`));
    row.append(body);
    target.append(row);
  }
}

function renderCorrelation(data) {
  const target = byId("correlation");
  clear(target);
  const correlation = data.correlation || {};
  const identity = document.createElement("div");
  identity.className = "correlation-identity";
  identity.append(text("div", t("label.masterThread", { value: correlation.master_thread_id || t("fallback.missing") }), "mono"));
  identity.append(text("div", t("label.surfaceFreshness", {
    surface: statusLabel(correlation.state || "missing"),
    freshness: statusLabel(correlation.freshness || "unknown"),
  }), "mono"));
  identity.append(text("p", correlation.claim_limit || ""));
  const currentness = correlation.master_filter?.currentness || {};
  const currentnessDetails = document.createElement("details");
  currentnessDetails.open = true;
  // The source label "master-filter current-head evidence" is rendered through the i18n dictionary.
  currentnessDetails.append(text("summary", t("label.masterFilterCurrentHead")));
  const head = currentness.head || {};
  currentnessDetails.append(text(
    "p",
    t("label.currentness", {
      state: statusLabel(currentness.state || "unknown"),
      sequence: head.sequence ?? t("fallback.unknown"),
      head: head.sha256 || t("fallback.missing"),
    }),
    "claim",
  ));
  currentnessDetails.append(evidenceList(currentness.evidence_refs));
  if (currentness.degradation?.length) {
    currentnessDetails.append(text("p", t("label.diagnostics", { value: currentness.degradation.join(", ") }), "claim"));
  }
  currentnessDetails.append(text("p", currentness.claim_limit || t("fallback.currentnessClaimLimit"), "claim"));
  identity.append(currentnessDetails);
  target.append(identity);

  const readModel = data.correlation_read_model || {};
  const cursor = readModel.cursor || {};
  const retention = document.createElement("div");
  retention.className = "correlation-identity";
  retention.append(text("div", t("label.goalLocalCursor", { status: statusLabel(readModel.status || "missing") }), "mono"));
  retention.append(text("div", t("label.schemaPositionRebuild", {
    schema: readModel.schema_version || t("fallback.missing"),
    position: cursor.position ?? t("fallback.unknown"),
    rebuild: readModel.rebuild?.mode || t("fallback.unknown"),
  }), "mono"));
  retention.append(text("p", t("label.retainedObservations", {
    observations: readModel.observations?.length || 0,
    conflicts: readModel.conflicts?.length || 0,
    winner: readModel.retention?.winner_selection || t("fallback.unknown"),
  })));
  if (readModel.conflicts?.length) {
    const conflictList = document.createElement("ul");
    for (const conflict of readModel.conflicts) {
      conflictList.append(text("li", t("label.conflict", {
        key: conflict.conflict_key || t("fallback.unknown"),
        records: conflict.record_ids?.length || 0,
        resolution: conflict.resolution || t("fallback.unknown"),
        winner: conflict.winner || t("fallback.none"),
      })));
    }
    retention.append(conflictList);
  }
  target.append(retention);

  for (const envelope of correlation.envelopes || []) {
    const card = document.createElement("article");
    card.className = "correlation-card";
    const headBlock = document.createElement("div");
    headBlock.className = "correlation-head";
    const returnId = envelope.return_observation?.return_id || envelope.correlation_id || t("fallback.return");
    headBlock.append(text("strong", t("label.lunaReturn", { value: returnId })));
    headBlock.append(badge(envelope.state || "invalid"));
    card.append(headBlock);

    const chain = document.createElement("div");
    chain.className = "correlation-chain";
    const wake = envelope.wake_observation || {};
    const wakeLabel = [wake.source_schema_version || t("fallback.wakeSchemaMissing"), wake.outcome ? statusLabel(wake.outcome) : t("fallback.outcomeMissing")].join(" · ");
    const stages = [
      ["label.goalThread", envelope.goal?.anchor_ref, envelope.goal?.master_thread_id],
      ["label.lunaReturnStage", envelope.return_observation?.ref, envelope.return_observation?.filter_disposition ? statusLabel(envelope.return_observation.filter_disposition) : t("fallback.missing")],
      ["label.wakeAdmission", wake.ref, wakeLabel],
      ["label.acceptedTurn", envelope.accepted_turn?.basis_ref, envelope.accepted_turn?.accepted_turn_id || t("fallback.missing")],
      ["label.masterFilter", envelope.master_filter?.ref, envelope.master_filter?.disposition ? statusLabel(envelope.master_filter.disposition) : t("fallback.missing")],
      ["label.reentry", null, envelope.lifecycle?.reentered?.state ? statusLabel(envelope.lifecycle.reentered.state) : t("fallback.missing")],
    ];
    for (const [labelKey, ref, value] of stages) {
      const stage = document.createElement("div");
      stage.className = "correlation-stage";
      stage.append(text("span", t(labelKey), "correlation-stage-label"));
      stage.append(text("strong", value || t("fallback.missing"), "mono"));
      if (ref) stage.append(evidenceList([ref]));
      chain.append(stage);
    }
    card.append(chain);
    const wakeDetails = document.createElement("details");
    wakeDetails.append(text("summary", t("label.wakeDetails")));
    wakeDetails.append(text("p", t("label.wakeFreshness", {
      source: wake.source_family || t("fallback.unknownSource"),
      freshness: statusLabel(wake.freshness || "unknown"),
      missingness: statusLabel(wake.missingness || "unknown"),
    }), "claim"));
    const provenance = wake.provenance || {};
    wakeDetails.append(evidenceList([wake.ref, {
      label: t("label.rawOwnerReceipt"),
      kind: wake.source_schema_version || t("fallback.wakeReceipt"),
      ref: provenance.raw_owner_ref || wake.ref?.ref,
      sha256: provenance.raw_owner_content_sha256 || wake.ref?.sha256,
      observed_at: wake.observed_at,
    }]));
    if (wake.failure) wakeDetails.append(text("pre", JSON.stringify({ failure: wake.failure }, null, 2)));
    if ((wake.candidate_receipts || []).length > 1) wakeDetails.append(text("pre", JSON.stringify({ candidate_receipts: wake.candidate_receipts }, null, 2)));
    const sourceSummary = {
      schema_version: wake.source_schema_version,
      owner_repo: provenance.owner_repo,
      owner_ref: provenance.owner_ref,
      contract_ref: provenance.contract_ref,
      adapter_version: wake.adapter_version,
      raw_handoff_sha256: wake.raw_handoff_sha256,
      normalized_handoff_sha256: wake.normalized_handoff_sha256,
      authority: wake.authority,
    };
    wakeDetails.append(text("pre", JSON.stringify(sourceSummary, null, 2)));
    card.append(wakeDetails);
    const limits = envelope.claim_limits || [];
    if (limits.length) {
      const details = document.createElement("details");
      details.append(text("summary", t("label.claimLimitsDag")));
      details.append(evidenceList([envelope.dag_disposition?.ref]));
      const dag = envelope.dag_disposition?.nodes || [];
      if (dag.length) {
        const dagList = document.createElement("ul");
        for (const node of dag) dagList.append(text("li", `${node.id}: ${node.state} → ${node.next}`));
        details.append(dagList);
      }
      const list = document.createElement("ul");
      for (const limit of limits) list.append(text("li", limit));
      details.append(list);
      card.append(details);
    }
    target.append(card);
  }

  const obligations = correlation.new_obligations || [];
  const obligationBlock = document.createElement("div");
  obligationBlock.className = "correlation-obligations";
  obligationBlock.append(text("strong", t("label.newObligations")));
  if (obligations.length) {
    const list = document.createElement("ul");
    for (const obligation of obligations) {
      const digest = obligation && typeof obligation === "object" ? obligation.sha256 || t("fallback.unavailable") : t("fallback.unavailable");
      const redacted = obligation && typeof obligation === "object" ? obligation.redacted : null;
      list.append(text("li", `${redacted || t("fallback.redactedLegacyObligation")} · sha256:${digest}`));
    }
    obligationBlock.append(list);
  } else {
    obligationBlock.append(text("p", t("label.noNewObligation")));
  }
  target.append(obligationBlock);
}

function renderPressureInbox(data) {
  const inbox = data.pressure_inbox || {};
  const summary = byId("pressure-summary");
  const target = byId("pressure-inbox");
  clear(summary);
  clear(target);
  const items = inbox.items || [];
  const critical = inbox.critical_next_routes || [];
  summary.append(badge(inbox.status || "missing"));
  summary.append(text("span", t("pressure.summary", {
    admitted: items.length,
    critical: critical.length,
    legacy: (inbox.legacy_candidates || []).length,
  }), "mono"));

  for (const item of items) {
    const card = document.createElement("article");
    card.className = `pressure-card${item.next_route?.critical ? " critical" : ""}`;
    const head = document.createElement("div");
    head.className = "pressure-head";
    const title = document.createElement("div");
    title.append(text("strong", item.pressure_ref?.id || t("fallback.pressure")));
    title.append(text("div", item.pressure_ref?.ref || t("fallback.pressureRefMissing"), "mono muted"));
    head.append(title);
    head.append(badge(item.outcome?.state || "invalid"));
    card.append(head);
    card.append(text("p", item.affected_goal_criterion || t("fallback.goalCriterionMissing"), "pressure-criterion"));
    card.append(text("p", t("pressure.ifOmitted", { value: item.consequence_of_omission || t("fallback.consequenceMissing") }), "claim"));

    const route = document.createElement("div");
    route.className = "pressure-route";
    route.append(text("span", item.next_route?.critical ? t("pressure.criticalNextRoute") : t("pressure.nextRoute"), "pressure-route-label"));
    route.append(text("strong", item.next_route?.route || t("fallback.routeMissing")));
    route.append(text("span", t("pressure.routeMeta", {
      owner: item.next_route?.owner || t("fallback.ownerMissing"),
      effect: item.next_route?.effect || t("fallback.unknown"),
      authority: item.next_route?.authority || t("fallback.unknown"),
    }), "mono"));
    card.append(route);

    const details = document.createElement("details");
    details.append(text("summary", t("pressure.details")));
    details.append(text("p", t("pressure.naturalOwner", {
      owner: item.natural_owner?.owner || t("fallback.missing"),
      ref: item.natural_owner?.owner_ref || t("fallback.ownerRefMissing"),
    }), "claim"));
    details.append(text("p", t("pressure.trigger", { value: item.recommended_trigger_strength || t("fallback.missing") }), "claim"));
    details.append(text("p", t("pressure.stopLine", { value: item.stop_line || t("fallback.missing") }), "claim"));
    details.append(text("p", t("pressure.wakeCondition", { value: item.wake_condition || t("fallback.missing") }), "claim"));
    details.append(evidenceList(item.evidence));
    details.append(text("pre", JSON.stringify({ checked_existing_surfaces: item.checked_existing_surfaces, independence_signals: item.independence_signals, outcome: item.outcome }, null, 2)));
    details.append(text("p", t("pressure.claimLimit", { value: item.claim_limit || "" }), "claim"));
    card.append(details);
    target.append(card);
  }

  for (const candidate of inbox.legacy_candidates || []) {
    const card = document.createElement("article");
    card.className = "pressure-card legacy";
    card.append(text("strong", candidate.pressure_ref?.id || t("pressure.legacyCandidate")));
    card.append(badge("deferred"));
    card.append(text("p", candidate.legacy_obligation_redacted || t("fallback.legacyObligationRedacted"), "claim"));
    card.append(text("p", t("pressure.sourceDigest", { value: candidate.legacy_obligation_digest || t("fallback.unavailable") }), "mono muted"));
    card.append(text("p", t("pressure.missingFields", { value: (candidate.missing_fields || []).join(", ") || t("fallback.unknown") }), "claim"));
    target.append(card);
  }

  if (!items.length && !(inbox.legacy_candidates || []).length) {
    target.append(text("p", t("pressure.noAdmitted"), "claim"));
  }
}

function activityGroup(labelKey, group, fields) {
  const block = document.createElement("div");
  block.className = "activity-group";
  const heading = document.createElement("div");
  heading.className = "activity-group-head";
  heading.append(text("strong", t(labelKey)));
  heading.append(badge(group?.state || "unknown"));
  block.append(heading);
  for (const [labelKeyForField, key] of fields) {
    const row = document.createElement("div");
    row.className = "activity-field";
    row.append(text("span", t(labelKeyForField), "muted"));
    row.append(text("span", activityValue(group, key), "mono"));
    block.append(row);
  }
  return block;
}

function renderActorActivity(data) {
  const target = byId("actor-activity");
  clear(target);
  const activity = data.actor_activity || {};
  const summary = activity.summary || {};
  const intro = document.createElement("div");
  intro.className = "activity-summary";
  intro.append(text("strong", t("activity.observed", { count: summary.actor_count == null ? statusLabel("unknown") : summary.actor_count })));
  intro.append(badge(activity.state || "unknown"));
  intro.append(text("p", activity.observation || t("fallback.actorActivityUnavailable")));
  target.append(intro);

  const actors = activity.actors || [];
  if (!actors.length) {
    target.append(text("p", t("fallback.noActorEnvelope"), "claim"));
    return;
  }
  for (const actor of actors) {
    const card = document.createElement("article");
    card.className = "actor-card";
    const head = document.createElement("div");
    head.className = "actor-head";
    const title = document.createElement("div");
    title.append(text("strong", actor.identity?.label || actor.actor_key || t("fallback.actorIdentityUnknown")));
    title.append(text("div", actor.actor_key || t("fallback.actorKeyUnknown"), "mono muted"));
    head.append(title);
    head.append(badge(actor.state || "unknown"));
    card.append(head);

    const grid = document.createElement("div");
    grid.className = "activity-grid";
    grid.append(activityGroup("activity.identity", actor.identity, [["activity.actorId", "actor_id"], ["activity.incarnation", "incarnation_id"], ["activity.role", "role_id"]]));
    grid.append(activityGroup("activity.responsibility", actor.responsibility, [["activity.state", "responsibility_state"], ["activity.holder", "holder"], ["activity.mandate", "mandate_id"], ["activity.obligation", "obligation_id"]]));
    grid.append(activityGroup("activity.process", actor.process, [["activity.processId", "process_id"], ["activity.posture", "posture"]]));
    grid.append(activityGroup("activity.session", actor.session, [["activity.sessionId", "session_id"], ["activity.posture", "posture"]]));
    grid.append(activityGroup("activity.terminal", actor.terminal, [["activity.terminalId", "terminal_id"], ["activity.posture", "posture"], ["activity.exitCode", "exit_code"]]));
    grid.append(activityGroup("activity.usage", actor.usage, [["activity.evidenceStatus", "observation_status"], ["activity.inputTokens", "input_tokens"], ["activity.outputTokens", "output_tokens"], ["activity.totalTokens", "total_tokens"], ["activity.toolCalls", "tool_calls"], ["activity.durationSeconds", "duration_seconds"]]));
    card.append(grid);

    const wakeReturn = document.createElement("div");
    wakeReturn.className = "activity-return";
    wakeReturn.append(text("strong", t("activity.wakeReturn")));
    wakeReturn.append(badge(actor.wake_return?.return_state || "unknown"));
    wakeReturn.append(text("span", t("activity.wakeReentryAccepted", {
      wake: activityValue(actor.wake_return, "wake_state"),
      reentry: activityValue(actor.wake_return, "reentry_state"),
      turn: activityValue(actor.wake_return, "accepted_turn_id"),
    }), "mono"));
    card.append(wakeReturn);
    card.append(evidenceList(actor.evidence_refs));
    card.append(text("p", actor.claim_limit || "", "claim"));
    target.append(card);
  }
}

function renderSources(data) {
  const target = byId("sources");
  clear(target);
  for (const item of data.sources || []) {
    const card = document.createElement("article");
    card.className = "source-card";
    const head = document.createElement("div");
    head.className = "source-head";
    const title = document.createElement("div");
    title.append(text("strong", item.id));
    title.append(text("div", item.owner, "source-owner"));
    head.append(title);
    head.append(badge(item.state));
    card.append(head);
    card.append(text("p", item.observation));
    const freshness = document.createElement("div");
    freshness.append(text("span", t("sources.freshness"), "muted"));
    freshness.append(badge(item.freshness));
    card.append(freshness);
    const details = document.createElement("details");
    details.append(text("summary", t("sources.metadataEvidence")));
    details.append(evidenceList(item.evidence_refs));
    const pre = text("pre", JSON.stringify(item.metadata || {}, null, 2));
    details.append(pre);
    details.append(text("p", t("sources.claimLimit", { value: item.claim_limit || "" }), "claim"));
    card.append(details);
    target.append(card);
  }
}

function renderOwners(data) {
  const target = byId("owners");
  clear(target);
  for (const item of data.owner_surfaces || []) {
    const row = document.createElement("tr");
    row.append(text("td", item.owner));
    row.append(text("td", item.authority));
    row.append(text("td", item.source_path, "mono"));
    const snapshot = item.source_snapshot || {};
    const observed = document.createElement("td");
    observed.append(badge(snapshot.state || "unknown"));
    if (snapshot.head) {
      observed.append(text("div", t("owners.snapshot", {
        branch: snapshot.branch || t("fallback.detached"),
        head: snapshot.head.slice(0, 12),
        dirty: ` · ${snapshot.dirty ? statusLabel("dirty") : statusLabel("clean")}`,
      }), "mono"));
    }
    if (item.runtime_snapshot) observed.append(text("div", t("owners.runtime", { value: statusLabel(item.runtime_snapshot.state || "unknown") }), "mono"));
    row.append(observed);
    row.append(badge(item.kag_snapshot_state || "unknown"));
    target.append(row);
  }
}

function renderRecords(data) {
  const render = (id, summary, countKey) => {
    const target = byId(id);
    clear(target);
    target.append(text("strong", t(countKey, { count: summary.count })));
    if (summary.latest && summary.latest.length) {
      const last = summary.latest[summary.latest.length - 1];
      target.append(text("div", t("records.latest", {
        created: last.created_at || t("fallback.record"),
        target: last.target_ref || t("fallback.target"),
      })));
    } else {
      target.append(text("div", t("records.empty")));
    }
  };
  render("annotation-summary", data.annotations || { count: 0 }, "records.annotationCount");
  render("intent-summary", data.action_intents || { count: 0 }, "records.intentCount");
}

function renderLimits(data) {
  const target = byId("limits");
  clear(target);
  for (const item of data.claim_limits || []) target.append(text("li", item));
}

function renderProjection(data) {
  renderHeader(data);
  renderInventory(data);
  renderLifecycle(data);
  renderDag(data);
  renderCorrelation(data);
  renderPressureInbox(data);
  renderActorActivity(data);
  renderSources(data);
  renderOwners(data);
  renderRecords(data);
  renderLimits(data);
}

async function refresh() {
  try {
    const response = await fetch("/api/projection", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || t("error.projectionRequestFailed"));
    currentProjection = data;
    byId("alert").classList.add("hidden");
    renderProjection(data);
  } catch (error) {
    const alert = byId("alert");
    alert.textContent = t("error.projectionUnavailable", { error: error.message });
    alert.classList.remove("hidden");
    byId("connection").textContent = t("connection.projectionUnavailable");
    byId("connection").className = "badge state-invalid";
  }
}

async function submitForm(event, route, form) {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(form).entries());
  const response = await fetch(route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || t("error.writeFailed"));
  form.reset();
  await refresh();
}

for (const button of document.querySelectorAll("[data-language]")) {
  button.addEventListener("click", () => i18n.setLanguage(button.dataset.language));
}
i18n.subscribe(() => {
  applyStaticTranslations();
  if (currentProjection) renderProjection(currentProjection);
  publishNativePresentationPreference();
});
window.AoaDashboardTheme?.subscribe?.(publishNativePresentationPreference);
applyStaticTranslations();
publishNativePresentationPreference();

byId("annotation-form").addEventListener("submit", (event) => submitForm(event, "/api/annotations", event.currentTarget).catch((error) => { byId("alert").textContent = error.message; byId("alert").classList.remove("hidden"); }));
byId("intent-form").addEventListener("submit", (event) => submitForm(event, "/api/action-intents", event.currentTarget).catch((error) => { byId("alert").textContent = error.message; byId("alert").classList.remove("hidden"); }));

refresh();
setInterval(refresh, 5000);
