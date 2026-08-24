# Release posture

`aoa-dashboard` `v0.1.0` is an owner-local, source/test/bootstrap release.
The release establishes a public source identity and a reproducible package
route; it does not widen the organ's derived-read or deferred-intent boundary.

| Claim | Current evidence | Ceiling |
| --- | --- | --- |
| independent repository identity | public GitHub remote, exact `v0.1.0` tag and clean landed `main` | public source identity |
| organ contract | committed contract, docs, validator and tests | source contract |
| federation registration | center registry and SDK workspace registration | source/workspace discovery |
| release publication | canonical changelog, annotated tag and GitHub Release | source/test/bootstrap publication |
| public package assets | local wheel/sdist producer outputs only; the reconciled `v0.1.0` Release has zero assets | no public package artifact or consumer-admission claim |
| private organ access | no dashboard record; default-deny v2 route documented | not admitted |
| deployment | no dashboard deployment is claimed by this organ contract | unknown/not claimed |
| live health | no live service claim | unknown/not claimed |
| proof/eval verdict | no independent eval packet is attached here | absent |
| human acceptance | remains with the operator and natural owner | absent |

The native desktop shell adds a source-level launcher, desktop metadata, and
host-runtime documentation. Its graphical canary can establish bounded local
process, URL/health, render, and clean-close observations; it does not promote
the dashboard to a deployed service, proof/eval result, owner acceptance, or
Goal completion.

GitHub validation protects source landing. It does not promote a repository to
runtime or private admission. Any future release must preserve the owner map,
run the local contract gate, and carry exact source, registry, deployment,
proof, and acceptance evidence separately.

## Owner-local publication route

`aoa-dashboard` is an optional SDK workspace repository but is intentionally not
in the SDK `OWNER_RELEASE_REPOS` publication set. The source-only release route
therefore belongs here: run `scripts/release_check.py`, the organ validator,
the unit/JSON/compile/JavaScript/build gates, and the exact GitHub PR route;
then tag the exact landed `main` commit and create the Release body from
`CHANGELOG.md`. Do not use `aoa release --all-due` for this repository and do
not infer federation publication from workspace discovery.

Artifact hashes and any available trust/attestation evidence are recorded as
release evidence, not as proof of runtime admission, deployment, health, or
human acceptance. The two package attachments that predated this boundary
were retained in a digest-bound recovery packet and removed from the existing
`v0.1.0` Release during single-release reconciliation. A future public package
asset requires an owner-recognized artifact class, exact source provenance,
required sidecars, registry record, and a non-unknown consumer trust-gate
verdict; a local build alone is not sufficient.
