# aoa-dashboard

The first working vertical slice of the AoA Goal Space/operator surface.
It reads a current Goal Anchor, a historical `.aoa` bootstrap binding, the
current task-local Goal/thread handoff and wake directory, the `aoa-stats`
source-coverage projection, the optional `aoa-agents` responsibility feed, and
bounded owner/KAG metadata. It produces a typed derived projection and a small
operator UI with source/ref/digest drill-down.

The dashboard is not an authority plane. It does not create roles, run actors,
execute runtime actions, issue eval verdicts, accept work, or rewrite owner
facts. Posted annotations and action intents are dashboard-owned records; an
action intent is explicitly deferred and is never executed by this service.

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
python3 scripts/run_dashboard.py --host 127.0.0.1 --port 8765
```

The default binding is `config/bootstrap.json`. Override it with
`AOA_DASHBOARD_CONFIG`. Runtime records go to
`AOA_DASHBOARD_STATE_ROOT` (default `/tmp/aoa-dashboard-state`).
The correlation ledger and checkpoint paths are configured under
`correlation_projection`; the HTTP read path does not create or mutate them.

Open `http://127.0.0.1:8765/`. The UI reads `/api/projection` and polls it
periodically; no fixture data is bundled or loaded.

## Validation

```text
python3 -m unittest discover -s tests -v
for contract in contracts/*.json; do python3 -m json.tool "$contract" >/dev/null; done
```

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
No owner-qualified v1 binding is currently admitted: the default bootstrap has
no candidate binding, and a missing, unlanded, forged, or merely shaped config
value remains raw candidate evidence with null canonical owner refs, invalid
state, and no re-entry. A future route must provide independently admitted
owner evidence from the stronger owner surface; dashboard config strings cannot
create that authority. The owner ABI does not publish
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
