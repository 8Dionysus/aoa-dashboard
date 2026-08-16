# Contracts

The JSON contracts in this directory define the dashboard-owned boundary.
They do not replace source-owner schemas. External source payloads are read
through adapters and retained only as bounded metadata plus provenance refs.

- `status-vocabulary.json` is the non-collapsing state vocabulary.
- `goal_anchor.schema.json` describes the private binding to an anchor path and
  the public metadata emitted from it.
- `correlation_envelope.schema.json` is the strict dashboard-owned envelope
  for Goal/thread, handoff, v2 wake receipt, accepted turn, master filter, and
  task-local DAG disposition. It retains exact refs/digests, observed time,
  freshness, degradation, authority, and claim limits.
- `correlation_observation.schema.json`, `correlation_cursor.schema.json`,
  `correlation_checkpoint.schema.json`, and
  `goal_local_correlation_projection.schema.json` define the versioned,
  replayable Goal-local observation ledger. They retain provenance and expose
  conflicts without selecting a winner.
- `pressure_inbox.schema.json` defines the structured P-infinity pressure
  record/read-model boundary. Its critical routes are display-only and carry
  `effect: none`.
- `goal_space_projection.schema.json` describes the read model served to the
  operator UI.
- `dashboard_annotation.schema.json` and `action_intent.schema.json` are
  append-only dashboard-owned records.
