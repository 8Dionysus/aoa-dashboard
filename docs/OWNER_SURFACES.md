# Owner surface map used by the first slice

The adapters were chosen after reading the adjacent contracts and checking
their current host paths. No neighboring organ exposes a ready-made Goal
Space UI or dashboard projection that can be adopted directly, so this repo
owns only the thin translation and presentation layer.

- `aoa-agents`: role-first and responsibility semantics. The optional live
  responsibility receipt feed is read as an owner feed; runtime A2A/usage
  artifacts remain evidence refs, not stats input.
- `aoa-skills`: shared capability ABI and task-local DAG vocabulary. The
  dashboard does not persist or redefine the task DAG.
- `aoa-sdk`: exact incarnation binding and RunPlan boundaries. The dashboard
  surfaces a binding reference and does not select model, role, or tools.
- `abyss-stack`: runtime/deployed service owner. The source checkout and
  deployed root are separate bindings; a path check cannot establish runtime
  health.
- `.aoa/session-memory`: raw transcript/session manifest and freshness owner.
  The configured bootstrap session is explicitly historical; it is not the
  current holder. The live rollout source and archived raw source are both
  referenced; an advancing source marks the archive as deferred/stale.
- `aoa-session-memory` also publishes the bounded Goal catalog consumed by the
  home view. The dashboard admits its exact v1 schema, preserves its
  currentness, and projects only safe titles, lifecycle grouping, timestamps,
  and one stable ref per Goal.
- Current Goal/thread return correlation is dashboard-owned derived metadata
  over the bounded task-local handoff/wake directory and master filter. It
  supports the historical task-local v2 witness beside the versioned
  owner-shaped `aoa-sdk` v1 source, preserving exact refs/content digests,
  explicit digest normalization provenance, freshness, missingness, and
  failure. The v1 admitted binding set is currently empty; config strings are
  candidate input only and cannot establish owner authority. A future
  owner-qualified admission route must be supplied by the stronger owner
  surface before v1 can be canonical or reenter. It does not take ownership of
  role, runtime, proof, return acceptance, parent resume, or semantic
  continuation.
- The master filter's mutable currentness remains owner evidence: the
  `master-thread` publishes a content-addressed current-head attestation and
  append-only history, while `aoa-dashboard` only compares bytes, retains refs,
  and reports bounded current/stale/missing/conflict/rollback state. The former
  snapshot pin is historical bootstrap context and is never rewritten by the
  dashboard.
- The owner-side advancement procedure is content-derived and explicit. It
  receives the configured source binding, computes identifiers from the
  selected bytes, and appends a typed transition; version, PID, checkout path,
  and caller-supplied digest are not currentness policy. Invalid legacy
  history is preserved and can be replaced only by a separately bound valid
  lineage.
- The live actor-activity card is a second derived view over the same admitted
  envelopes. It may show allowlisted scalar process/session/terminal/usage
  observations and responsibility identifiers, but it cannot publish or
  reinterpret those owners' semantics. Missing and unknown remain explicit.
- `aoa-evals`: proof and independent evaluation owner. Candidate artifacts are
  not displayed as verdicts.
- `aoa-memo`: reviewed durable memory owner. Recall is context, not evidence
  of current state.
- `aoa-stats`: measurement/source-coverage owner. The first slice consumes the
  source coverage JSON and registry, preserving `not_attested` freshness.
- KAG: derived navigation/index owner. Its 2026-08-08 projection is retained
  as a stale snapshot reference and cannot make current owner claims.

The external bindings are in `config/bootstrap.json`. They are deliberately
host-local for this first dogfood slice and are not portable deployment
defaults.
