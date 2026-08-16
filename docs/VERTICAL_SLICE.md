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
- one compact actor-by-actor activity inventory over admitted task-local
  envelopes, with responsibility identity, process/session/terminal posture,
  wake/return state, usage observations, provenance refs, and field-level
  missing or unknown values;
- DAG progress, lifecycle steps, owner surfaces, source refs, and claim limits;
- distinct lifecycle and data-quality vocabulary values;
- a dashboard-owned annotation or deferred action intent recorded locally.

The task-local adapter is bounded to the configured direct directory and
validates the exact `master_thread_id`, handoff digest, v2 wake schema,
canonical `handoff_ref`, and admitted delivery outcome. It does not expose raw
prompt bodies. `returned`, `wake requested`, and `reentered` remain separate
observations; `reentered` is only a filtered correlation, never semantic
continuation or acceptance.

The activity adapter reads only the refs already admitted by that adapter and
copies a fixed allowlist of scalar metadata. It does not add a cursor, pressure
inbox, wake compatibility path, or source binding. Process/session/terminal
values are not health checks, and usage absence is never rendered as zero.

This is a read model, not a release gate. Independent evaluation, owner
acceptance, a goal-scoped return, and master re-entry remain explicitly
missing until their owners publish suitable evidence.
