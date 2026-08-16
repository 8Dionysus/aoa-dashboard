# First vertical slice

The slice is complete when a local operator can open the dashboard and see:

- the current Goal Anchor id/title and digest;
- the historical bootstrap session binding alongside archive freshness, with
  its current-holder limit visible;
- `aoa-stats` source coverage with its `not_attested` freshness ceiling;
- an optional `aoa-agents` receipt feed without conflating another actor with
  this Goal;
- the current task-local Goal/thread correlation: Luna handoff refs and
  SHA-256 digests, versioned v2 task-local or v1 `aoa-sdk` wake candidates,
  accepted turn, master-filter disposition, DAG state, and newly exposed
  obligations;
- DAG progress, lifecycle steps, owner surfaces, source refs, and claim limits;
- distinct lifecycle and data-quality vocabulary values;
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

This is a read model, not a release gate. Independent evaluation, owner
acceptance, a goal-scoped return, and master re-entry remain explicitly
missing until their owners publish suitable evidence.
