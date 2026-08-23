# Contracts

The JSON contracts in this directory define the dashboard-owned boundary.
They do not replace source-owner schemas. External source payloads are read
through adapters and retained only as bounded metadata plus provenance refs.

- `status-vocabulary.json` is the non-collapsing state vocabulary.
- `goal_anchor.schema.json` describes the private binding to an anchor path and
  the public metadata emitted from it.
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
- `goal_catalog_projection.schema.json` describes the dashboard-normalized
  view of the versioned `aoa-session-memory` Goal catalog. The adapter admits
  only the exact owner/schema pair, keeps source degradation, and omits raw
  objectives, session bodies, usage, work chains, and host paths.
- `master_filter_currentness.schema.json` defines the migration boundary for
  the mutable master return filter. The dashboard consumes an owner-authored
  current-head attestation plus append-only head history, compares the
  attested SHA-256 with one read of the filter bytes, and fails closed on
  missing, stale, ambiguous, conflicting, or unannounced rollback evidence.
- `dashboard_annotation.schema.json` and `action_intent.schema.json` are
  append-only dashboard-owned records.
