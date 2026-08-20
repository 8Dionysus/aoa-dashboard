# aoa-dashboard organ contract

## Identity

`aoa-dashboard` is the owner repository for a derived Goal Space/operator
projection. Its public source identity is
`https://github.com/8Dionysus/aoa-dashboard`; public GitHub presence is source
landing evidence only. The organ is `bootstrap` and
`declared_not_admitted` until a stronger access or runtime contour is separately
reviewed.

The machine-readable contract is
[`contracts/organ_contract.json`](../contracts/organ_contract.json). This
document explains its constitutional meaning; it is not a replacement for
the owner contracts of sibling repositories.

## What this organ owns

The organ owns the derived read and operator surfaces already present in this
repository:

1. `aoa_dashboard_projection_v1`;
2. dashboard annotations;
3. deferred, non-executing action intents;
4. task-local correlation projection and cursor/checkpoint;
5. the P-infinity Pressure Inbox projection;
6. task-local actor-activity projection.

It may read named owner surfaces, preserve source refs/digests, render
missingness and freshness, and persist its own annotations. It cannot amend a
sibling source record. An action intent describes a future owner route and has
no executor in this organ.

## Constitutional limits

The dashboard never creates or selects roles, mandates, incarnations, runtime
processes, proof verdicts, memory meaning, owner acceptance, master wake,
semantic re-entry, or action execution. It never converts an absent publisher
into a zero, a generated projection into admission, or transport delivery into
acceptance.

The dashboard uses `planned`, `bound`, `running`, `paused`, `returned`,
`reviewed`, `accepted`, `wake requested`, `reentered`, `missing`, `stale`,
`deferred`, and `invalid` as separate observations. A rendered state is not a
grant of authority.

## Exact sibling separation

| Surface | Natural owner | Dashboard boundary |
| --- | --- | --- |
| role, mandate, responsibility, return, wake | `aoa-agents` | observe receipts and refs |
| capability ABI and task-local DAG | `aoa-skills` | show bounded metadata |
| workspace, RunPlan, incarnation and compatibility | `aoa-sdk` | consume binding refs; never select |
| runtime and deployment lifecycle | `abyss-stack` | distinguish source/deploy/live evidence |
| raw session and freshness | `.aoa/session-memory` | preserve refs; never make proof |
| proof, review and eval verdict | `aoa-evals` | display independent evidence or missingness |
| reviewed durable memory | `aoa-memo` | optional context only |
| measurement and source coverage | `aoa-stats` | consume derived views; no invented zeros |
| derived navigation and relations | KAG | navigation/provenance only |

The dashboard is not `aoa-goals`, does not create an `aoa-goals` repository, and
does not absorb Goal Anchor or task-local DAG authority from their existing
owners.

## Receives and hands off

The organ receives named, bounded observations from the owner routes above and
the current Goal/thread correlation directory. It hands presentation and
dashboard-owned records to operators; it hands any requested effect back to
the named natural owner as a deferred intent. It returns this organ-establishment
work to `holder:aoa-dashboard-master-sol` for filtering and DAG progression.

## Deny-by-default states and rollback

The current organ has no direct access plane and no private registry record.
That absence is intentional. A future access contour must follow
[`ADMISSION.md`](ADMISSION.md), pass the SDK/workspace and proof gates, and be
accepted by the natural owner before it can move beyond default-deny.

If a future contour drifts, rollback lowers admission to `deny` or `shadow`
first, removes the consumer route, preserves source and receipt provenance,
and restores only after exact revalidation. Removing a projection package or
deleting evidence is not the rollback route.

## Completion check

The local completion gate is:

```text
python3 scripts/validate_organ_contract.py
python3 -m unittest discover -s tests -v
```

This proves the source contract and local tests. It does not prove deployment,
live runtime health, proof verdict, semantic continuation, or human acceptance.
