# Contracts

The JSON contracts in this directory define the dashboard-owned boundary.
They do not replace source-owner schemas. External source payloads are read
through adapters and retained only as bounded metadata plus provenance refs.

- `status-vocabulary.json` is the non-collapsing state vocabulary.
- `goal_anchor.schema.json` describes the strict owner-qualified JSON source
  read from a current Goal Anchor. Its `goal_id` and `master_thread_id` must
  match the selected binding; the binding carries the required SHA-256 for the
  exact source bytes. The prose/text first-slice anchor remains historical/demo
  input only and is never admitted by the current v1 route.
- `correlation_envelope.schema.json` is the strict dashboard-owned envelope
  for Goal/thread, handoff, versioned wake receipts, accepted turn, master
  filter, and task-local DAG disposition. It keeps
  `task_local_actor_wake_receipt_v2` distinct from the owner-shaped
  `aoa_codex_wake_receipt_v1` source family and retains exact refs/content
  digests, provenance, observed time, freshness, missingness, failure,
  authority, and claim limits. The current independently admitted v1 binding
  set is empty: missing, unlanded, forged, or merely shaped config bindings
  remain candidate-only and invalid with null canonical owner refs. A future
  owner-qualified route must publish independently admitted owner evidence;
  dashboard config is not an admission surface. The owner ABI does not contain
  `handoff_message_submitted`, so that derived field remains `null` for v1.
  `goal_resume_requested` is retained as explicit nullable observation data,
  but never participates in v1 admission or proves semantic resume.
  It also serves as the source envelope for the versioned, replayable
  Goal-local observation ledger. The ledger retains provenance and exposes
  conflicts without selecting a winner.
- `correlation_observation.schema.json`, `correlation_cursor.schema.json`,
  `correlation_checkpoint.schema.json`, and
  `goal_local_correlation_projection.schema.json` define the versioned,
  replayable Goal-local observation ledger. They retain provenance and expose
  conflicts without selecting a winner.
- `pressure_inbox.schema.json` defines the structured P-infinity pressure
  record/read-model boundary. Its critical routes are display-only and carry
  `effect: none`.
  `goal_space_projection.schema.json` also carries the
  `aoa_dashboard_actor_activity_v1` derived view. Its actor cards retain only
  allowlisted scalar activity metadata and source refs; absent or malformed
  fields remain bounded observations.
- `goal_space_projection.schema.json` describes the read model served to the
  operator UI.
- `codex_goal_thread_projection.schema.json` describes the bounded read-only
  `thread/goal/get`, `thread/read`, and paginated `thread/list` observation for
  one exact Goal/thread. It preserves missing, unknown, deferred, and invalid
  relation pages without claiming a complete branch.
- `participant_context.schema.json` describes the dashboard adapter envelope
  whose identity, task, model, and runtime dimensions degrade independently.
  Explicit task-local names remain observations; the envelope does not promote
  them to canonical human identity, role mandate, model fit, or runtime health.
- `master_context_projection.schema.json` describes the read-only join of exact
  Goal/thread metadata, Master-filter evidence, catalog currentness, and
  planning topology without promoting any source to another owner's truth.
- `goal_topology_projection.schema.json` describes structural planning nodes and
  dependency closures. It does not create canonical branch or trajectory
  lifecycle authority.
- `goal-context-projection.schema.json` describes the dashboard-owned join of
  the exact public-safe session-memory Goal/thread board and aoa-agents
  participant relation dimensions. It preserves each source's currentness,
  privacy omissions, and claim limit; it does not create actor, branch,
  runtime, proof, acceptance, or action authority.
- `goal_catalog_projection.schema.json` describes the dashboard-normalized
  view of the versioned `aoa-session-memory` Goal catalog plus its optional
  explicit live Codex app-server federation. The adapters admit only the exact
  owner/schema or method bindings, keep per-source degradation and opaque
  pagination, preserve exact owner refs on overlap, and omit raw objectives,
  session bodies, usage, work chains, and host paths.
- `goal_projection.schema.json` describes the exact selected Goal projection
  admitted only after catalog membership. It carries only owner-published
  public-safe Goal/branch/thread items and explicit omissions; it is not a
  substitute for owner semantics, thread completeness, or acceptance.
- `master_filter_currentness.schema.json` defines the migration boundary for
  the mutable master return filter. The dashboard consumes an owner-authored
  current-head attestation plus append-only head history, compares the
  attested SHA-256 with one read of the filter bytes, and fails closed on
  missing, stale, ambiguous, conflicting, or unannounced rollback evidence.
- `runtime_binding.schema.json` defines the explicit
  `aoa_dashboard_runtime_binding_v1` process input. It rejects unknown fields,
  requires the complete source map (including Goal Anchor bytes and explicit
  correlation selectors), and binds the selected Goal and every current source
  through owner, authority, access, currentness, and claim-limit fields; it is
  consumed as read evidence and does not grant role, runtime, proof,
  acceptance, or action authority. Its optional `live_goal_catalog` source
  requires an explicit read-only socket, exact method pair, client capability
  label, archived filter, page size, page budget, and timeout.
- `dashboard_annotation.schema.json` and `action_intent.schema.json` are
  append-only dashboard-owned records.
