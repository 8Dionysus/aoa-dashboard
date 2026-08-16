# First vertical slice

The slice is complete when a local operator can open the dashboard and see:

- the current Goal Anchor id/title and digest;
- the historical bootstrap session binding alongside archive freshness, with
  its current-holder limit visible;
- `aoa-stats` source coverage with its `not_attested` freshness ceiling;
- an optional `aoa-agents` receipt feed without conflating another actor with
  this Goal;
- the current task-local Goal/thread correlation: Luna handoff refs and
  SHA-256 digests, v2 wake delivery, accepted turn, master-filter disposition,
  DAG state, and newly exposed obligations;
- a versioned Goal-local correlation read model with deterministic cursor,
  checkpoint/replay state, source watermarks, duplicate provenance, and
  unresolved conflicting observations;
- a structured P-infinity Pressure Inbox showing the natural owner, evidence,
  omission consequence, independence signals, trigger strength, stop-line,
  wake condition, outcome, and critical display-only next-route;
- DAG progress, lifecycle steps, owner surfaces, source refs, and claim limits;
- distinct lifecycle and data-quality vocabulary values;
- a dashboard-owned annotation or deferred action intent recorded locally.

The task-local adapter is bounded to the configured direct directory and
validates the exact `master_thread_id`, handoff digest, v2 wake schema,
canonical `handoff_ref`, and admitted delivery outcome. It does not expose raw
prompt bodies. `returned`, `wake requested`, and `reentered` remain separate
observations; `reentered` is only a filtered correlation, never semantic
continuation or acceptance.

The new cursor layer is adjacent to, and does not modify, the wake-receipt
compatibility adapter. Existing `bootstrap.json` and
`master-return-disposition.json` inputs remain accepted through an explicit
migration record. Legacy pressure strings are shown only as redacted,
digest-linked deferred candidates until all structured fields are present; raw
legacy text is never emitted.

The projection GET is read-only. When durable local retention is required, an
owner-controlled caller may use the bounded materialization function to append
validated observations to JSONL and atomically replace one checkpoint file; the
locked log/checkpoint pair is recoverable, not a two-file atomic transaction.
Malformed or drifted input is never persisted or reported as successful.

This is a read model, not a release gate. Independent evaluation, owner
acceptance, a goal-scoped return, and master re-entry remain explicitly
missing until their owners publish suitable evidence.
