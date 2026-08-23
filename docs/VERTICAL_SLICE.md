# First vertical slice

The observations below are available for an explicitly selected
owner-qualified runtime binding. With no binding, current-Goal and
task-local-source observations remain missing rather than falling back to the
historical/demo instance.

The slice is complete when a local operator can open the dashboard and see:

- the current structured Goal Anchor id/title, owner-qualified Goal/thread
  identity, and exact source digest;
- the historical bootstrap session binding alongside archive freshness, with
  its current-holder limit visible;
- `aoa-stats` source coverage with its `not_attested` freshness ceiling;
- an optional `aoa-agents` receipt feed without conflating another actor with
  this Goal;
- the current task-local Goal/thread correlation: Luna handoff refs and
  SHA-256 digests, versioned v2 task-local or v1 `aoa-sdk` wake candidates,
  accepted turn, master-filter disposition, DAG state, and newly exposed
  obligations;
- a versioned Goal-local correlation read model with deterministic cursor,
  checkpoint/replay state, source watermarks, duplicate provenance, and
  unresolved conflicting observations;
- a structured P-infinity Pressure Inbox showing the natural owner, evidence,
  omission consequence, independence signals, trigger strength, stop-line,
  wake condition, outcome, and critical display-only next-route;
- one compact actor-by-actor activity inventory over admitted task-local
  envelopes, with responsibility identity, process/session/terminal posture,
  wake/return state, usage observations, provenance refs, and field-level
  missing or unknown values;
- DAG progress, lifecycle steps, owner surfaces, source refs, and claim limits;
- distinct lifecycle and data-quality vocabulary values;
- master-filter currentness from the owner-authored current-head digest and
  append-only transition history, including explicit stale, missing, conflict,
  and rollback evidence;
- a dashboard-owned annotation or deferred action intent recorded locally.

The adapter is bounded to the configured direct directory and validates the
exact `master_thread_id`, handoff digest, canonical `handoff_ref`, and
version-specific receipt contract. The v1 adapter validates the exact
`aoa_codex_wake_receipt_v1` shape, including owner-compatible integer
`attempts`, but the current owner-qualified admission set is empty. It
compares the v1 `sha256:<hex>` handoff digest through explicit versioned
normalization and retains the raw receipt ref/content digest, source contract
shape, freshness, missingness, and failure as candidate evidence. It does not
expose raw prompt bodies. `returned`, `wake requested`, and `reentered` remain
separate observations; `reentered` is only a filtered correlation, never
semantic continuation, runtime health, return acceptance, or parent resume. A
v1/v2 collision is invalid and both candidate schemas remain visible in
evidence drill-down. `goal_resume_requested` is an explicit nullable
observation: null for v1, unsupported, or missing, and the exact v2 boolean
when present; it is not an admission or semantic-resume signal.

The new cursor layer is adjacent to, and does not modify, the wake-receipt
compatibility adapter. The shipped `config/bootstrap.json` is reusable and
contains no current instance. A process may explicitly select an
owner-qualified `aoa_dashboard_runtime_binding_v1` document; missing,
ambiguous, stale, deferred, invalid, or mismatched binding/source inputs remain
fail-closed. A current Goal Anchor must be a strict owner-qualified JSON source
whose Goal/thread identity matches the selected binding and whose required
digest matches the bytes read. The old first-slice material is retained only at
`config/demo/first-slice.json` as historical/demo opt-in. Legacy pressure
strings are shown only as redacted, digest-linked deferred candidates until all
structured fields are present; raw legacy text is never emitted.

The mutable master filter is not pinned to a changing snapshot digest. The
configured `master_filter_currentness` binding names the master-thread-owned
current-head attestation and history within the task-local root. A valid head
must match the filter bytes, exact Goal/thread/ref contract, and the last
append-only sequence; missing or ambiguous evidence remains deferred/invalid.
The historical digest is retained as migration context only.

The projection GET is read-only. When durable local retention is required, an
owner-controlled caller may use the bounded materialization function to append
validated observations to JSONL and atomically replace one checkpoint file; the
locked log/checkpoint pair is recoverable, not a two-file atomic transaction.
Malformed or drifted input is never persisted or reported as successful.

The activity adapter reads only the refs already admitted by that adapter and
copies a fixed allowlist of scalar metadata. It does not add a cursor, pressure
inbox, wake compatibility path, or source binding. Process/session/terminal
values are not health checks, and usage absence is never rendered as zero.

This is a read model, not a release gate. Independent evaluation, owner
acceptance, a goal-scoped return, and master re-entry remain explicitly
missing until their owners publish suitable evidence.
