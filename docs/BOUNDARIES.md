# Ownership and claim boundaries

## What this organ owns

The dashboard owns three local surfaces:

1. `aoa_dashboard_projection_v1`, a derived read model assembled from named
   owner sources;
2. operator annotations, which are notes about a dashboard target and do not
   amend the target owner's record;
3. action intents, which describe a requested future owner route. The first
   slice records them with `deferred` state and has no execution path.
4. a task-local correlation projection, which retains exact Goal/thread,
   handoff, versioned wake, accepted-turn, master-filter, and DAG disposition
   refs. It is derived read-model evidence, not a new actor, runtime, proof,
   return-acceptance, semantic-re-entry, or parent-resume owner.

## What remains outside the organ

| Surface | Owner | Dashboard treatment |
| --- | --- | --- |
| role, mandate, responsibility, return, wake | `aoa-agents` | observe receipts and refs only |
| capability ABI and task-local DAG | `aoa-skills` | show bounded owner metadata only |
| RunPlan and incarnation binding | `aoa-sdk` | show binding refs, never choose them |
| deployed runtime lifecycle | `abyss-stack` | source/deploy/live is separate and may be deferred |
| raw session transcript and freshness | `.aoa/session-memory` | use refs and metadata, never promote a projection to proof; configured bootstrap bindings are historical |
| proof, review, eval verdict | `aoa-evals` | missing until an independent packet is connected |
| reviewed durable memory | `aoa-memo` | optional context, never current truth |
| measurement compatibility and source coverage | `aoa-stats` | consume its derived surface with its authority ceiling |
| derived navigation and evidence-bearing relations | KAG | navigation/provenance only; stale snapshots remain stale |

The projection uses a pair of dimensions rather than a single green/red flag:
the lifecycle step (`planned`, `bound`, `running`, `paused`, `returned`,
`reviewed`, `accepted`, `wake requested`, `reentered`) and the observation
quality (`missing`, `unknown`, `stale`, `deferred`, `invalid`). A step can be
known to be a step while its expected evidence is missing or deferred.

The current holder is bound through the Goal/thread and task-local receipt
directory in `current_correlation`. The old session/edeac bootstrap remains a
separate `historical_bootstrap` binding and is never used as current-holder
identity. Wake delivery is transport evidence only. The dashboard keeps the
task-local v2 witness and owner-qualified SDK v1 receipt as distinct source
families; v1's `sha256:<hex>` is normalized only by the versioned v1 adapter
while its raw field remains visible. Master-filtered re-entry is emitted only
from exact `accepted_turn_id` plus the validated master filter and still does
not prove semantic continuation, owner acceptance, runtime health,
return acceptance, or parent resume.
