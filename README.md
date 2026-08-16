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

The current correlation surface is task-local and read-only. Handoff delivery
is not proof or acceptance; `reentered` requires exact `accepted_turn_id` plus
the master filter and remains a bounded correlation claim. Annotations and
action intents keep their local dashboard-owned, non-executing boundary.
Critical Pressure Inbox next-routes are rendered as display-only `effect:none`
records. The dashboard never wakes a master, forms an actor, chooses a winner,
or executes an owner route.
