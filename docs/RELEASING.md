# Releasing aoa-dashboard

This repository uses an owner-local source-only release route. The first
public release is `v0.1.0`; there is no prior published SemVer baseline.
`aoa-dashboard` is not an `aoa-sdk` `OWNER_RELEASE_REPOS` target, so workspace
discovery does not authorize `aoa release --all-due` or the SDK publisher.

## Source and changelog requirements

Release preparation starts from the exact current `origin/main` in a clean,
isolated worktree. The release-prep change must update the canonical
`CHANGELOG.md`, preserve the `[Unreleased]` heading, add a dated release
section, and link the complete [reconciliation ledger](RELEASE_RECONCILIATION.md).
The release section must keep the source/test/bootstrap claim ceiling and must
not claim private admission, deployment, live health, proof/eval, semantic
re-entry, or human acceptance.

The package marker in `pyproject.toml`, the README current-release banner, the
release posture, the organ-contract required-surface manifest, and this route
must agree on the release identity. No schema or generated surface may be
silently changed merely to make a release pass.

## Required local gate

Run from the clean release-prep or exact landed-main worktree:

```text
python3 scripts/release_check.py
python3 scripts/validate_organ_contract.py
python3 scripts/validate_default_binding.py
python3 -m unittest discover -s tests -v
for contract in contracts/*.json; do python3 -m json.tool "$contract" >/dev/null; done
python3 -m compileall -q src scripts tests
node --check web/app.js
node --check web/i18n.js
node --check web/theme.js
git diff --check
python3 -m build --sdist --wheel
```

The wheel and sdist are local producer artifacts. Record their SHA-256
digests, archive them as task evidence, and distinguish them from registry
admission, signature, SBOM, provenance, runtime, and proof evidence. If the
host has the GTK4/Libadwaita/WebKitGTK stack, a bounded native canary may be
run and recorded separately; it does not become a deployment or health claim.

## Landing and publication

1. Commit the release-prep surface on a branch based on current `origin/main`.
2. Push the branch and open a PR with the changed surfaces, gates, skipped
   checks, and claim limits.
3. Wait for required `Repo Validation`; repair failures and wait for the
   replacement result. Merge through GitHub, then fast-forward local `main`.
4. Repeat every local gate on the exact landed `main` commit and confirm the
   worktree is clean.
5. Run the strict federation preflight as an observation. For this repository,
   an SDK publisher selection failure is expected because the repo is outside
   `OWNER_RELEASE_REPOS`; preserve that result and use this owner-local route.
6. Run the owner-local dry-run equivalent: verify the release section, exact
   current main, absent-or-matching `v0.1.0` tag, and canonical release body
   generated from `CHANGELOG.md` without mutating GitHub.
7. Create an annotated `v0.1.0` tag only at the exact landed `main` commit,
   push that tag, and create the GitHub Release with the body derived from the
   canonical changelog.
8. Recheck tag/object identity, the latest-release marker, Release body
   parity, assets/attestations, postpublish audit, local `main` synchronization,
   and clean status. A missing asset, attestation, runtime receipt, proof
   verdict, or acceptance remains missing; it is not replaced by CI green.

Never mutate `aoa-session-memory`, `aoa-routing`, or `abyss-stack_old` as part
of this route. Never publish a tag from an unlanded worktree or include active
Goal Space lines in this release.
