# First vertical slice

The slice is complete when a local operator can open the dashboard and see:

- the current Goal Anchor id/title and digest;
- the historical bootstrap session binding alongside archive freshness, with
  its current-holder limit visible;
- `aoa-stats` source coverage with its `not_attested` freshness ceiling;
- an optional `aoa-agents` receipt feed without conflating another actor with
  this Goal;
- the current task-local Goal/thread correlation: Luna handoff refs and
  SHA-256 digests, versioned v2 task-local or v1 `aoa-sdk` wake delivery,
  accepted turn, master-filter disposition, DAG state, and newly exposed
  obligations;
- DAG progress, lifecycle steps, owner surfaces, source refs, and claim limits;
- distinct lifecycle and data-quality vocabulary values;
- a dashboard-owned annotation or deferred action intent recorded locally.

The adapter is bounded to the configured direct directory and validates the
exact `master_thread_id`, handoff digest, canonical `handoff_ref`, and
version-specific receipt contract. The v1 owner adapter accepts only the exact
`aoa_codex_wake_receipt_v1` shape, compares its `sha256:<hex>` handoff digest
through an explicit versioned normalization, and retains the raw owner ref,
raw content digest, source contract ref, freshness, missingness, and failure.
It does not expose raw prompt bodies. `returned`, `wake requested`, and
`reentered` remain separate observations; `reentered` is only a filtered
correlation, never semantic continuation, runtime health, return acceptance,
or parent resume. A v1/v2 collision is invalid and both candidate schemas
remain visible in evidence drill-down.

This is a read model, not a release gate. Independent evaluation, owner
acceptance, a goal-scoped return, and master re-entry remain explicitly
missing until their owners publish suitable evidence.
