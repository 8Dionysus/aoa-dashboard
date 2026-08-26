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
- `aoa-session-memory` publishes the bounded historical Goal catalog consumed by
  the home view. The dashboard admits its exact v1 schema, preserves its
  currentness, and projects only safe titles, lifecycle grouping, timestamps,
  and one stable ref per Goal. A separately bound Codex app-server adapter can
  add live Goals before historical publication catches up; it uses only exact
  `thread/list` ids followed by exact `thread/goal/get` ids and never treats
  the current or selected Goal as a catalog query. Federation retains both
  owner records and their independent pagination/currentness/failure states.
- Current Goal/thread return correlation is dashboard-owned derived metadata
  over the bounded task-local handoff/wake directory and master filter. It
  supports the historical task-local v2 witness beside the versioned
  owner-shaped `aoa-sdk` v1 source, preserving exact refs/content digests,
  explicit digest normalization provenance, freshness, missingness, and
  failure. The owner-shaped wake-receipt v1 admitted binding set is currently
  empty; config strings are candidate input only and cannot establish owner
  authority. The separate runtime Goal binding is admitted only from an
  explicit owner-qualified process input and does not make a wake receipt
  canonical or reenter. It does not take ownership of
  role, runtime, proof, return acceptance, parent resume, or semantic
  continuation.
- Codex app-server is the semantic owner for the exact Goal and Thread. The
  dashboard reads `thread/goal/get`, `thread/read`, and the experimental,
  read-only `thread/list` relation filters for one exact current thread. The
  separate live Goal catalog reads paginated `thread/list` with an explicit
  archived/query budget and then asks `thread/goal/get` for each returned id;
  `goal: null` is a valid no-Goal thread, not a dashboard Goal. A relation
  page is retained as bounded direct-child or descendant context; it is not a
  complete branch lifecycle or participant graph.
- The participant envelope projects task-local actor observations into
  independently degraded identity, task, model-realization, and runtime
  dimensions. Candidate labels and model slugs remain diagnostics-only unless
  the required owner shape is present; missing, stale, and mismatched Goal
  thread joins are not repaired by the dashboard.
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

`config/bootstrap.json` contains only the reusable selection contract. The
selected Goal, thread, topology, catalog, correlation, and pressure paths are
supplied at process start through an explicit owner-qualified runtime binding;
they are not copied into the shipped default. The first-slice instance remains
under `config/demo/first-slice.json` as explicit historical/demo data and is
never the current holder or default product binding.
