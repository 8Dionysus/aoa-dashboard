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
    const wake = envelope.wake_observation || {};
    const wakeLabel = [wake.source_schema_version || "wake schema missing", wake.outcome || "outcome missing"].join(" · ");
    const stages = [
      ["Goal / thread", envelope.goal?.anchor_ref, envelope.goal?.master_thread_id],
      ["Luna return", envelope.return_observation?.ref, envelope.return_observation?.filter_disposition],
      ["Wake admission", wake.ref, wakeLabel],
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
    const wakeDetails = document.createElement("details");
    wakeDetails.append(text("summary", "wake source, provenance, freshness and failure"));
    wakeDetails.append(text("p", `${wake.source_family || "unknown source"} · freshness: ${wake.freshness || "unknown"} · missingness: ${wake.missingness || "unknown"}`, "claim"));
    const provenance = wake.provenance || {};
    wakeDetails.append(evidenceList([wake.ref, {
      label: "raw owner receipt",
      kind: wake.source_schema_version || "wake receipt",
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
    for (const obligation of obligations) list.append(text("li", obligation));
    obligationBlock.append(list);
  } else {
    obligationBlock.append(text("p", "No new obligation is present in the current filter."));
  }
  target.append(obligationBlock);
}

function activityValue(group, key) {
  const value = group?.[key];
  return value == null || value === "" ? "unknown" : value;
}

function activityGroup(label, group, fields) {
  const block = document.createElement("div");
  block.className = "activity-group";
  const heading = document.createElement("div");
  heading.className = "activity-group-head";
  heading.append(text("strong", label));
  heading.append(badge(group?.state || "unknown"));
  block.append(heading);
  for (const [name, key] of fields) {
    const row = document.createElement("div");
    row.className = "activity-field";
    row.append(text("span", name, "muted"));
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
  intro.append(text("strong", `${summary.actor_count == null ? "unknown" : summary.actor_count} actor(s) observed`));
  intro.append(badge(activity.state || "unknown"));
  intro.append(text("p", activity.observation || "Actor activity is not available; absence is not zero."));
  target.append(intro);

  const actors = activity.actors || [];
  if (!actors.length) {
    target.append(text("p", "No actor envelope is admitted by the current task-local correlation surface; actor count remains unknown.", "claim"));
    return;
  }
  for (const actor of actors) {
    const card = document.createElement("article");
    card.className = "actor-card";
    const head = document.createElement("div");
    head.className = "actor-head";
    const title = document.createElement("div");
    title.append(text("strong", actor.identity?.label || actor.actor_key || "actor identity unknown"));
    title.append(text("div", actor.actor_key || "actor key unknown", "mono muted"));
    head.append(title);
    head.append(badge(actor.state || "unknown"));
    card.append(head);

    const grid = document.createElement("div");
    grid.className = "activity-grid";
    grid.append(activityGroup("Identity", actor.identity, [["actor id", "actor_id"], ["incarnation", "incarnation_id"], ["role", "role_id"]]));
    grid.append(activityGroup("Responsibility", actor.responsibility, [["state", "responsibility_state"], ["holder", "holder"], ["mandate", "mandate_id"], ["obligation", "obligation_id"]]));
    grid.append(activityGroup("Process", actor.process, [["process id", "process_id"], ["posture", "posture"]]));
    grid.append(activityGroup("Session", actor.session, [["session id", "session_id"], ["posture", "posture"]]));
    grid.append(activityGroup("Terminal", actor.terminal, [["terminal id", "terminal_id"], ["posture", "posture"], ["exit code", "exit_code"]]));
    grid.append(activityGroup("Usage", actor.usage, [["evidence status", "observation_status"], ["input tokens", "input_tokens"], ["output tokens", "output_tokens"], ["total tokens", "total_tokens"], ["tool calls", "tool_calls"], ["duration seconds", "duration_seconds"]]));
    card.append(grid);

    const wakeReturn = document.createElement("div");
    wakeReturn.className = "activity-return";
    wakeReturn.append(text("strong", "Wake / return posture"));
    wakeReturn.append(badge(actor.wake_return?.return_state || "unknown"));
    wakeReturn.append(text("span", `wake: ${activityValue(actor.wake_return, "wake_state")} · re-entry: ${activityValue(actor.wake_return, "reentry_state")} · accepted turn: ${activityValue(actor.wake_return, "accepted_turn_id")}`, "mono"));
    card.append(wakeReturn);
    card.append(evidenceList(actor.evidence_refs));
    card.append(text("p", actor.claim_limit || "", "claim"));
    target.append(card);
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
    renderActorActivity(data);
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
