const LIFECYCLE = [
  "planned", "bound", "running", "paused", "returned", "reviewed", "accepted", "wake requested", "reentered",
];
const QUALITY = ["missing", "unknown", "stale", "deferred", "invalid"];

const byId = (id) => document.getElementById(id);
const clear = (element) => { while (element.firstChild) element.removeChild(element.firstChild); };

function text(tag, value, className = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value == null ? "" : String(value);
  return node;
}

function badge(value) {
  return text("span", value, `badge state-${String(value).replaceAll(" ", "-")}`);
}

function renderHeader(data) {
  byId("goal-title").textContent = data.goal.title || "Unnamed Goal";
  byId("goal-id").textContent = data.goal.goal_id || "goal id missing";
  byId("goal-digest").textContent = data.goal.anchor_digest || "digest unavailable";
  byId("goal-limit").textContent = data.goal.claim_limit || "";
  byId("generated").textContent = `generated ${data.generated_at}`;
  const connection = byId("connection");
  connection.textContent = "host-local read";
  connection.className = "badge state-bound";
}

function renderInventory(data) {
  const target = byId("inventory");
  clear(target);
  for (const item of data.state_inventory) {
    const card = document.createElement("div");
    card.className = `inventory-item ${item.category === "lifecycle" ? "lifecycle" : "quality"}`;
    card.append(text("span", item.state, "label"));
    card.append(text("span", item.observed_count, "count"));
    card.append(text("span", item.observation, "note"));
    target.append(card);
  }
}

function evidenceList(refs) {
  const list = document.createElement("div");
  list.className = "ref-list";
  for (const ref of refs || []) {
    if (!ref) continue;
    const digest = ref.sha256 ? ` · sha256:${ref.sha256}` : "";
    const observed = ref.observed_at ? ` · observed:${ref.observed_at}` : "";
    const code = text("code", `${ref.label || ref.kind || "ref"}: ${ref.ref || ref.path || "unresolved"}${digest}${observed}`);
    list.append(code);
  }
  return list;
}

function renderLifecycle(data) {
  const target = byId("lifecycle");
  clear(target);
  for (const item of data.lifecycle) {
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
  for (const item of data.dag) {
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
    body.append(text("p", `${item.observation} Pressure: ${item.pressure}`));
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
  identity.append(text("div", `master thread: ${correlation.master_thread_id || "missing"}`, "mono"));
  identity.append(text("div", `surface: ${correlation.state || "missing"} · freshness: ${correlation.freshness || "unknown"}`, "mono"));
  identity.append(text("p", correlation.claim_limit || ""));
  target.append(identity);

  const readModel = data.correlation_read_model || {};
  const cursor = readModel.cursor || {};
  const retention = document.createElement("div");
  retention.className = "correlation-identity";
  retention.append(text("div", `Goal-local cursor · ${readModel.status || "missing"}`, "mono"));
  retention.append(text("div", `schema: ${readModel.schema_version || "missing"} · position: ${cursor.position ?? "unknown"} · rebuild: ${readModel.rebuild?.mode || "unknown"}`, "mono"));
  retention.append(text("p", `retained ${readModel.observations?.length || 0} observation(s) · ${readModel.conflicts?.length || 0} unresolved conflict(s) · winner selection: ${readModel.retention?.winner_selection || "unknown"}`));
  if (readModel.conflicts?.length) {
    const conflictList = document.createElement("ul");
    for (const conflict of readModel.conflicts) {
      conflictList.append(text("li", `${conflict.conflict_key || "conflict"}: ${conflict.record_ids?.length || 0} retained record(s); resolution ${conflict.resolution || "unknown"}; winner ${conflict.winner || "none"}`));
    }
    retention.append(conflictList);
  }
  target.append(retention);

  for (const envelope of correlation.envelopes || []) {
    const card = document.createElement("article");
    card.className = "correlation-card";
    const head = document.createElement("div");
    head.className = "correlation-head";
    const returnId = envelope.return_observation?.return_id || envelope.correlation_id || "return";
    head.append(text("strong", `Luna return · ${returnId}`));
    head.append(badge(envelope.state || "invalid"));
    card.append(head);

    const chain = document.createElement("div");
    chain.className = "correlation-chain";
    const stages = [
      ["Goal / thread", envelope.goal?.anchor_ref, envelope.goal?.master_thread_id],
      ["Luna return", envelope.return_observation?.ref, envelope.return_observation?.filter_disposition],
      ["Wake admission", envelope.wake_observation?.ref, envelope.wake_observation?.outcome],
      ["Accepted turn", envelope.accepted_turn?.basis_ref, envelope.accepted_turn?.accepted_turn_id || "missing"],
      ["Master filter", envelope.master_filter?.ref, envelope.master_filter?.disposition],
      ["Re-entry", null, envelope.lifecycle?.reentered?.state || "missing"],
    ];
    for (const [label, ref, value] of stages) {
      const stage = document.createElement("div");
      stage.className = "correlation-stage";
      stage.append(text("span", label, "correlation-stage-label"));
      stage.append(text("strong", value || "missing", "mono"));
      if (ref) stage.append(evidenceList([ref]));
      chain.append(stage);
    }
    card.append(chain);
    const limits = envelope.claim_limits || [];
    if (limits.length) {
      const details = document.createElement("details");
      details.append(text("summary", "claim limits and DAG disposition"));
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
  obligationBlock.append(text("strong", "New obligations from master filter"));
  if (obligations.length) {
    const list = document.createElement("ul");
    for (const obligation of obligations) {
      const digest = obligation && typeof obligation === "object" ? obligation.sha256 || "unavailable" : "unavailable";
      const redacted = obligation && typeof obligation === "object" ? obligation.redacted : null;
      list.append(text("li", `${redacted || "[redacted legacy obligation]"} · sha256:${digest}`));
    }
    obligationBlock.append(list);
  } else {
    obligationBlock.append(text("p", "No new obligation is present in the current filter."));
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
  summary.append(text("span", `${items.length} admitted · ${critical.length} critical next-route(s) · ${(inbox.legacy_candidates || []).length} legacy candidate(s)`, "mono"));

  for (const item of items) {
    const card = document.createElement("article");
    card.className = `pressure-card${item.next_route?.critical ? " critical" : ""}`;
    const head = document.createElement("div");
    head.className = "pressure-head";
    const title = document.createElement("div");
    title.append(text("strong", item.pressure_ref?.id || "pressure"));
    title.append(text("div", item.pressure_ref?.ref || "pressure ref missing", "mono muted"));
    head.append(title);
    head.append(badge(item.outcome?.state || "invalid"));
    card.append(head);
    card.append(text("p", item.affected_goal_criterion || "Goal criterion missing", "pressure-criterion"));
    card.append(text("p", `If omitted: ${item.consequence_of_omission || "consequence missing"}`, "claim"));

    const route = document.createElement("div");
    route.className = "pressure-route";
    route.append(text("span", item.next_route?.critical ? "CRITICAL NEXT-ROUTE" : "NEXT-ROUTE", "pressure-route-label"));
    route.append(text("strong", item.next_route?.route || "route missing"));
    route.append(text("span", `${item.next_route?.owner || "owner missing"} · effect:${item.next_route?.effect || "unknown"} · authority:${item.next_route?.authority || "unknown"}`, "mono"));
    card.append(route);

    const details = document.createElement("details");
    details.append(text("summary", "owner, evidence, independence and stop-line"));
    details.append(text("p", `Natural owner: ${item.natural_owner?.owner || "missing"} (${item.natural_owner?.owner_ref || "owner ref missing"})`, "claim"));
    details.append(text("p", `Trigger: ${item.recommended_trigger_strength || "missing"}`, "claim"));
    details.append(text("p", `Stop-line: ${item.stop_line || "missing"}`, "claim"));
    details.append(text("p", `Wake condition: ${item.wake_condition || "missing"}`, "claim"));
    details.append(evidenceList(item.evidence));
    details.append(text("pre", JSON.stringify({ checked_existing_surfaces: item.checked_existing_surfaces, independence_signals: item.independence_signals, outcome: item.outcome }, null, 2)));
    details.append(text("p", `Claim limit: ${item.claim_limit || ""}`, "claim"));
    card.append(details);
    target.append(card);
  }

  for (const candidate of inbox.legacy_candidates || []) {
    const card = document.createElement("article");
    card.className = "pressure-card legacy";
    card.append(text("strong", candidate.pressure_ref?.id || "legacy pressure candidate"));
    card.append(badge("deferred"));
    card.append(text("p", candidate.legacy_obligation_redacted || "Legacy obligation text is redacted", "claim"));
    card.append(text("p", `Source digest: ${candidate.legacy_obligation_digest || "unavailable"}`, "mono muted"));
    card.append(text("p", `Missing structured fields: ${(candidate.missing_fields || []).join(", ") || "unknown"}`, "claim"));
    target.append(card);
  }

  if (!items.length && !(inbox.legacy_candidates || []).length) {
    target.append(text("p", "No pressure is admitted. Absence is not proof that no pressure exists.", "claim"));
  }
}

function renderSources(data) {
  const target = byId("sources");
  clear(target);
  for (const item of data.sources) {
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
    freshness.append(text("span", "freshness: ", "muted"));
    freshness.append(badge(item.freshness));
    card.append(freshness);
    const details = document.createElement("details");
    details.append(text("summary", "metadata and evidence refs"));
    details.append(evidenceList(item.evidence_refs));
    const pre = text("pre", JSON.stringify(item.metadata || {}, null, 2));
    details.append(pre);
    details.append(text("p", `Claim limit: ${item.claim_limit}`, "claim"));
    card.append(details);
    target.append(card);
  }
}

function renderOwners(data) {
  const target = byId("owners");
  clear(target);
  for (const item of data.owner_surfaces) {
    const row = document.createElement("tr");
    row.append(text("td", item.owner));
    row.append(text("td", item.authority));
    row.append(text("td", item.source_path, "mono"));
    const snapshot = item.source_snapshot || {};
    const observed = document.createElement("td");
    observed.append(badge(snapshot.state || "unknown"));
    if (snapshot.head) observed.append(text("div", `${snapshot.branch || "detached"} · ${snapshot.head.slice(0, 12)}${snapshot.dirty ? " · dirty" : " · clean"}`, "mono"));
    if (item.runtime_snapshot) observed.append(text("div", `runtime: ${item.runtime_snapshot.state || "unknown"}`, "mono"));
    row.append(observed);
    row.append(badge(item.kag_snapshot_state || "unknown"));
    target.append(row);
  }
}

function renderRecords(data) {
  const render = (id, summary, type) => {
    const target = byId(id);
    clear(target);
    target.append(text("strong", `${summary.count} ${type}`));
    if (summary.latest && summary.latest.length) {
      const last = summary.latest[summary.latest.length - 1];
      target.append(text("div", `${last.created_at || "record"} · ${last.target_ref || "target"}`));
    } else {
      target.append(text("div", "No dashboard-owned records yet."));
    }
  };
  render("annotation-summary", data.annotations, "annotation(s)");
  render("intent-summary", data.action_intents, "deferred intent(s)");
}

function renderLimits(data) {
  const target = byId("limits");
  clear(target);
  for (const item of data.claim_limits || []) target.append(text("li", item));
}

async function refresh() {
  try {
    const response = await fetch("/api/projection", { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.error || "projection request failed");
    byId("alert").classList.add("hidden");
    renderHeader(data);
    renderInventory(data);
    renderLifecycle(data);
    renderDag(data);
    renderCorrelation(data);
    renderPressureInbox(data);
    renderSources(data);
    renderOwners(data);
    renderRecords(data);
    renderLimits(data);
  } catch (error) {
    const alert = byId("alert");
    alert.textContent = `Projection unavailable: ${error.message}. The UI will retry.`;
    alert.classList.remove("hidden");
    byId("connection").textContent = "projection unavailable";
    byId("connection").className = "badge state-invalid";
  }
}

async function submitForm(event, route, form) {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(form).entries());
  const response = await fetch(route, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.error || "write failed");
  form.reset();
  await refresh();
}

byId("annotation-form").addEventListener("submit", (event) => submitForm(event, "/api/annotations", event.currentTarget).catch((error) => { byId("alert").textContent = error.message; byId("alert").classList.remove("hidden"); }));
byId("intent-form").addEventListener("submit", (event) => submitForm(event, "/api/action-intents", event.currentTarget).catch((error) => { byId("alert").textContent = error.message; byId("alert").classList.remove("hidden"); }));

refresh();
setInterval(refresh, 5000);
