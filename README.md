# aoa-dashboard

> Current release: `v0.1.0`. See [CHANGELOG](CHANGELOG.md) for release notes.

The owner-bounded AoA Goal Space/operator surface.
With an explicit owner-qualified runtime binding it reads the selected Goal
Anchor, owner Goal/thread context, task-local Goal/thread handoff and wake
directory, Goal topology, an arbitrary owner-published Goal catalog plus an
exact selected-Goal public-safe projection, pressure context, the `aoa-stats`
source-coverage projection, the optional `aoa-agents` responsibility feed, and
bounded owner/KAG metadata. It produces a typed derived projection and a small
operator UI with source/ref/digest drill-down. Without that binding, the
projection remains fail-closed and does not invent a current Goal. The bundled
first-slice material is an explicit historical/demo opt-in only.

The dashboard is not an authority plane. It does not create roles, run actors,
execute runtime actions, issue eval verdicts, accept work, or rewrite owner
facts. Posted annotations and action intents are dashboard-owned records; an
action intent is explicitly deferred and is never executed by this service.

The constitutional boundary and owner routes are defined in
[`docs/ORGAN_CONTRACT.md`](docs/ORGAN_CONTRACT.md) and the machine-readable
[`contracts/organ_contract.json`](contracts/organ_contract.json). The repository
is a public source identity for a bootstrap derived layer; that identity does
not by itself admit a runtime or private organ access contour.

The derived correlation read model is rebuilt from canonical metadata-only
observations with `aoa_dashboard_correlation_cursor_v1` and
`aoa_dashboard_correlation_checkpoint_v1`. Exact replay is idempotent; source
watermark or payload drift fails closed. Duplicate observations retain their
provenance, while conflicting observations remain visible with
`winner: null` and `resolution: unresolved`.
The HTTP projection remains read-only; the explicit
`materialize_goal_local_projection` owner-controlled path appends validated
observations to a JSONL ledger and atomically replaces its checkpoint file. The
log/checkpoint pair is single-writer locked and recoverable, but is not a
two-file atomic transaction; an interrupted call may leave a log-ahead state
for the next locked rebuild. A local materialization is derived evidence, never
an owner-source overwrite.

The P-infinity Pressure Inbox is a structured, read-only route. Each admitted
record keeps `pressure_ref`, evidence, the affected Goal criterion, omission
consequence, natural owner, checked surfaces, independence signals, trigger
strength, stop-line, wake condition, next route, and outcome. Legacy
bootstrap/master-filter obligation strings remain visible as deferred
candidates until those fields are supplied; only a redacted digest-linked
candidate is emitted, and raw legacy text is never exposed or silently
upgraded.

## Run

```text
python3 scripts/run_dashboard.py --host 127.0.0.1 --port 8765 \
  --binding /path/to/owner-qualified-runtime-binding.json
```

`config/bootstrap.json` is a reusable selector, not a current instance. Omit
`--binding` to keep the read model fail-closed, or pass one explicit
owner-qualified `aoa_dashboard_runtime_binding_v1` JSON document. The
historical first-slice instance is available only through the explicit
`config/demo/first-slice.json` path. Runtime records go to
`AOA_DASHBOARD_STATE_ROOT` (default `/tmp/aoa-dashboard-state`).
The correlation ledger and checkpoint paths are configured under
`correlation_projection`; the HTTP read path does not create or mutate them.

Open `http://127.0.0.1:8765/`. The UI reads `/api/projection` and polls it
periodically; no instance data is loaded by default.

### Native desktop shell

The same UI can run in a small native GTK shell. From a checkout, use:

```text
python3 scripts/run_desktop.py
```

An installed package exposes the equivalent `aoa-dashboard-desktop` command.
The shell uses GTK4, Libadwaita 1, and WebKitGTK 6.0 from the host; those
libraries are intentionally not vendored. It starts the existing Python server
inside the application on `127.0.0.1` with an OS-assigned ephemeral port,
hands that URL to the embedded WebView, and stops the server when the
application exits. The stable application id is
`org.aoa.AoaDashboard`, so normal Gio single-instance behavior applies.

The graphical shell is a presentation/lifecycle wrapper only. The Python
projection and the existing HTML/CSS/JavaScript remain the source surface, and
the dashboard's provenance, missingness, and claim limits are unchanged.

## Validation

```text
python3 scripts/validate_organ_contract.py
python3 scripts/validate_default_binding.py
python3 scripts/release_check.py
python3 -m unittest discover -s tests -v
for contract in contracts/*.json; do python3 -m json.tool "$contract" >/dev/null; done
git diff --check
```

The same route is run by the `Repo Validation` GitHub workflow.

## Owner and admission routes

- [`docs/BOUNDARIES.md`](docs/BOUNDARIES.md) states what the dashboard owns and
  what remains with sibling repositories.
- [`docs/ADMISSION.md`](docs/ADMISSION.md) records the current no-access-plane
  state and the future private registry route without fabricating admission.
- [`docs/DIRECTION.md`](docs/DIRECTION.md) records the next bounded growth
  conditions.
- [`docs/RELEASE_POSTURE.md`](docs/RELEASE_POSTURE.md) separates source
  identity, GitHub landing, deployment, and live acceptance.

The projection is evidence of the dashboard's adapter and rendering contract,
not proof of live runtime health or owner acceptance. The UI keeps
`planned`, `bound`, `running`, `paused`, `returned`, `reviewed`, `accepted`,
`wake requested`, `reentered`, `missing`, `stale`, `deferred`, and `invalid`
as separate vocabulary values.

The current correlation surface is task-local and read-only. It accepts the
historical `task_local_actor_wake_receipt_v2` witness and recognizes the
versioned owner-shaped `aoa_codex_wake_receipt_v1` source without merging their
schemas. The v1 adapter preserves the raw receipt ref/content digest and raw
`sha256:<hex>` handoff field while comparing only an explicit normalized value.
The owner-shaped wake-receipt v1 admission set remains empty: a missing,
unlanded, forged, or merely shaped wake receipt remains candidate evidence with
null canonical owner refs, invalid state, and no re-entry. Separately, the
runtime process may consume one explicit `aoa_dashboard_runtime_binding_v1`
document only when its source descriptors are owner-qualified, current at read,
and internally matched. The reusable bootstrap does not contain that instance;
dashboard configuration cannot create the authority represented by the source
owners. The current v1 Goal Anchor is a structured owner-qualified source
whose Goal/thread identity and required exact-byte digest must match the
selected binding; a path, filename, or free-text match is not sufficient. The
owner ABI does not publish
`handoff_message_submitted`, so the dashboard keeps it unknown (`null`) for v1
instead of reconstructing it from the outcome. `goal_resume_requested` is
explicitly `null` for v1, unsupported, and missing receipts, and preserves the
task-local v2 boolean when present; it never admits v1 or proves semantic
resume. Handoff delivery is not proof, acceptance, semantic re-entry, runtime
health, or parent resume; `reentered` requires exact `accepted_turn_id` plus
the master filter and remains a bounded correlation claim. Annotations and
action intents keep their local dashboard-owned, non-executing boundary.
Critical Pressure Inbox next-routes are rendered as display-only `effect:none`
records. The dashboard never wakes a master, forms an actor, chooses a winner,
or executes an owner route.

The live activity surface is derived from those admitted task-local correlation
envelopes. It renders one card per observed return candidate and copies only
allowlisted scalar actor, responsibility, process, session, terminal, and usage
fields from the handoff or wake payload. Missing or unknown fields stay visible;
the surface never treats them as zero or as runtime health.

The home surface is catalog-first: it groups every admitted catalog item by
active, attention, paused, or completed/history state and keeps the runtime
selected Goal as a separate convenience card. Catalog publication is bound by
explicit runtime path or command capability; currentness, opaque pagination,
localized title availability, and negative states remain visible. Selecting a
catalog item reads only that item's exact owner-qualified public-safe projection.

The mutable master disposition is admitted through the owner-authored
`master_filter_currentness` binding: a content-addressed current-head attestation
and append-only history record the exact filter digest, sequence, transition,
and rollback history. The former `master_filter_expected_sha256` is retained
only as historical bootstrap context and is never used to decide currentness.
Missing, conflicting, ambiguous, stale, or unannounced rollback evidence stays
deferred or invalid with bounded refs and claim limits; the dashboard does not
rewrite the binding after a master transition.

The owner-controlled `scripts/advance_currentness.py` procedure is the
advancement path. Given the configured binding and an explicit owner-reviewed
transition, it derives the filter SHA-256 and next sequence from the selected
bytes, appends one history record, and atomically replaces the mutable head
pointer. It never accepts a caller-supplied digest, edits the filter, or edits
bootstrap configuration. If an old lineage contains invalid manual records,
bind a new lineage and retain the old files as historical evidence instead of
rewriting them.
