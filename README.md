# aoa-dashboard

The first working vertical slice of the AoA Goal Space/operator surface.
It reads a current Goal Anchor, the live `.aoa` session binding for this
creation session, the `aoa-stats` source-coverage projection, the optional
`aoa-agents` responsibility feed, and bounded owner/KAG metadata. It produces
a typed derived projection and a small operator UI with source drill-down.

The dashboard is not an authority plane. It does not create roles, run actors,
execute runtime actions, issue eval verdicts, accept work, or rewrite owner
facts. Posted annotations and action intents are dashboard-owned records; an
action intent is explicitly deferred and is never executed by this service.

## Run

```text
python3 scripts/run_dashboard.py --host 127.0.0.1 --port 8765
```

The default binding is `config/bootstrap.json`. Override it with
`AOA_DASHBOARD_CONFIG`. Runtime records go to
`AOA_DASHBOARD_STATE_ROOT` (default `/tmp/aoa-dashboard-state`).

Open `http://127.0.0.1:8765/`. The UI reads `/api/projection` and polls it
periodically; no fixture data is bundled or loaded.

## Validation

```text
python3 -m unittest discover -s tests -v
python3 -m json.tool contracts/goal_space_projection.schema.json >/dev/null
```

The projection is evidence of the dashboard's adapter and rendering contract,
not proof of live runtime health or owner acceptance. The UI keeps
`planned`, `bound`, `running`, `paused`, `returned`, `reviewed`, `accepted`,
`wake requested`, `reentered`, `missing`, `stale`, `deferred`, and `invalid`
as separate vocabulary values.
