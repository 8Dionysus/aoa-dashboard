# Ownership and claim boundaries

## What this organ owns

The dashboard owns seven local derived/operator surfaces:

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
5. a versioned Goal-local cursor/checkpoint and append-only metadata retention
   layer. It may preserve duplicate/conflicting observations and provenance,
   but it may not choose a source-owner winner. The HTTP read path does not
   write; explicit materialization appends validated observations and atomically
   replaces one checkpoint file under the same single-writer lock. The
   log/checkpoint pair is recoverable rather than two-file atomic.
6. the P-infinity Pressure Inbox and its operator presentation. It may expose
   a critical next-route with `effect: none`; it cannot wake, branch, approve,
   execute, or change an owner record.
7. a task-local actor-activity projection, which groups admitted envelopes by
   actor key and retains allowlisted process/session/terminal/usage observations
   with their source refs. It is an observation surface, not a lifecycle or
   runtime-health owner.

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
Wake delivery is transport evidence only. The dashboard keeps the
task-local v2 witness and owner-shaped SDK v1 source as distinct families; the
current independently admitted v1 binding set is empty, so v1 remains raw
candidate evidence with null canonical owner refs, invalid state, and no
re-entry. An unlanded, forged, or merely shaped config string cannot create
owner authority. A future owner-qualified route must come from the stronger
owner surface. The v1 `sha256:<hex>` is normalized only by the versioned v1
adapter while its raw field remains visible. The owner ABI does not publish
`handoff_message_submitted`; v1 keeps that observation unknown. The nullable
`goal_resume_requested` observation is null for v1, unsupported, and missing,
and is an exact v2 boolean when present; it never participates in v1 admission.
Master-filtered re-entry is emitted only from exact `accepted_turn_id` plus the
validated master filter and still does not prove semantic continuation, owner
acceptance, runtime health, return acceptance, or parent resume.

The mutable master filter is current only when the `master-thread` owner
supplies the content-addressed current-head attestation and bounded append-only
history declared by `master_filter_currentness`. The dashboard compares the
attested digest to the filter bytes and preserves sequence, transition,
rollback, provenance, and claim limits. Missing or conflicting owner evidence is
deferred or invalid; the historical snapshot digest is context only and is not
rewritten after a transition.

## Cursor and pressure stop-lines

The cursor is computed from sorted canonical observation identities, payload
digests, and source watermarks rather than poll order or read time. A replay
reuses the same cursor; a changed existing payload/source watermark, removed
record, malformed checkpoint, unknown access scope, or unknown authority is an
invalid rebuild. Only declared observation/source read timestamps are excluded
from digests; meaningful currentness, access, authority, and claim drift
remains invalid or unresolved. A new observation may extend the cursor, but it
cannot erase an earlier record.

Pressure records fail closed when evidence, natural owner, stop-line, wake
condition, or route authority is absent. The compatibility bridge accepts the
existing bootstrap and master-filter paths, but converts legacy obligation
strings into explicitly deferred, digest-linked candidates with missing fields;
raw legacy text remains source-owned and is never emitted by the API/UI. It
never turns a missing owner into a domain zero or an action permission.
identity. Wake delivery is transport evidence only. The dashboard keeps the
task-local v2 witness and owner-shaped SDK v1 source as distinct families; the
current independently admitted v1 binding set is empty, so v1 remains raw
candidate evidence with null canonical owner refs, invalid state, and no
re-entry. An unlanded, forged, or merely shaped config string cannot create
owner authority. A future owner-qualified route must come from the stronger
owner surface. The v1 `sha256:<hex>` is normalized only by the versioned v1
adapter while its raw field remains visible. The owner ABI does not publish
`handoff_message_submitted`; v1 keeps that observation unknown. The nullable
`goal_resume_requested` observation is null for v1, unsupported, and missing,
and is an exact v2 boolean when present; it never participates in v1 admission.
Master-filtered re-entry is emitted only from exact `accepted_turn_id` plus the
validated master filter and still does not prove semantic continuation, owner
acceptance, runtime health, return acceptance, or parent resume.
The actor-activity cards reuse that same correlation binding. Their identity,
responsibility, process, session, terminal, and usage groups are field-level
observations. A missing publisher, missing field, malformed payload, or absent
usage value remains missing, unknown, or invalid; no count, health, or success
claim is inferred from absence.
