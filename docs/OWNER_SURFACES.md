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
- Current Goal/thread return correlation is dashboard-owned derived metadata
  over the bounded task-local handoff/wake directory and master filter. It
  supports the historical task-local v2 witness beside the exact owner
  `aoa-sdk` v1 runtime-neutral receipt, preserving source schema, exact raw
  refs/content digests, explicit digest normalization provenance, freshness,
  missingness, and failure. It does not take ownership of role, runtime,
  proof, return acceptance, parent resume, or semantic continuation.
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
