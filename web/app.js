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
    const code = text("code", `${ref.label || ref.kind || "ref"}: ${ref.ref || ref.path || "unresolved"}`);
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
