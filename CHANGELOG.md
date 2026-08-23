# Changelog

## [Unreleased]

### Changed

- The shipped bootstrap is now reusable: an explicit owner-qualified runtime
  binding selects the Goal, thread, topology, catalog, correlation, and
  pressure sources; no binding remains fail-closed.

### Validation

- Added two-binding, fail-closed, mismatch, demo-isolation, default-scan, and
  packaging coverage for the reusable bootstrap route.

### Notes

- The historical first-slice instance remains an explicit demo input and is
  not the default current product binding.

## [0.1.0] - 2026-08-22

### Summary

- First public bootstrap release of `aoa-dashboard`, an owner-bounded AoA Goal Space/operator projection with a provenance-preserving derived read surface and an optional native desktop wrapper.

### Added

- Goal projection and operator UI with explicit source/ref/digest evidence and non-collapsing missingness, freshness, lifecycle, and acceptance vocabulary.
- Dashboard-owned correlation envelopes, replayable cursors/checkpoints, source watermarks, duplicate/conflict retention, and task-local return/wake projections.
- Bounded wake-receipt compatibility for task-local v2 and owner-shaped v1 candidates, with strict binding, provenance, digest normalization, malformed-input retention, and safe unknown-field handling.
- Structured P-infinity Pressure Inbox with redacted digest-linked legacy candidates and deferred, non-executing routes.
- Bounded actor-activity projection over admitted metadata-only envelopes, preserving separate actor, responsibility, process, session, terminal, wake/return, and usage observations.
- Content-addressed master-filter currentness contract, append-only history, explicit initial/advance/rollback and migration handling, and the owner-controlled `scripts/advance_currentness.py` route.
- Public organ contract, owner-surface map, deny-by-default admission documentation, source validation script, and the `Repo Validation` workflow.
- GTK4/Libadwaita/WebKitGTK 6.0 native shell, `org.aoa.AoaDashboard` desktop metadata/icon, host-local loopback backend, and `aoa-dashboard-desktop` package entry point.
- Bilingual web UI, light/dark/system theme support, persisted presentation preferences, and a strict native presentation bridge.
- Owner-local release validator and publication route with a complete release reconciliation ledger.

### Changed

- The projection reads named owner surfaces and preserves source refs, digests, freshness, missingness, authority, and claim limits rather than treating derived data as authority.
- Currentness moved from a historical expected-digest snapshot to owner-authored current-head/history evidence; invalid legacy records remain historical evidence and are not rewritten.
- The HTTP path remains read-only; local materialization is explicit, append-only, locked, and recoverable, with no two-file atomicity claim.
- The native shell wraps the existing web surface instead of introducing a second frontend or native authority plane.
- Release identity is explicit in the package marker, README banner, dated changelog, release posture, contract manifest, and owner-local release route.

### Fixed

- Adapter alignment with live owner payloads and exact master/holder binding.
- Filtering and preservation of returned candidates beside deferred pressure.
- Stable replay digests, cursor provenance/collision checks, safe cursor writes, and capability-opaque diagnostics.
- Wake receipt provenance, owner admission/parity, attempts normalization, malformed/non-object envelope handling, and explicit unknown/null values.
- Projection reconciliation hermeticity and duplicate fixture handling.
- Native startup locale/theme mapping, malformed or over-broad bridge payload rejection, state preservation, and clean backend shutdown.

### Deprecated

- The former `master_filter_expected_sha256` snapshot is historical bootstrap/migration context only; it is not a currentness decision.
- Legacy obligation strings remain redacted digest-linked deferred candidates until structured owner fields exist.
- The owner-shaped v1 wake candidate is not an admitted binding merely because its JSON shape is valid; the current admitted v1 set is empty.

### Removed

- No public capability or owner authority is intentionally removed in this initial release.
- Duplicate documentation summaries and unsafe implicit interpretations were removed during history hardening; their semantic coverage remains in explicit contracts.

### Security

- Metadata admission rejects forbidden prompt/raw/private/secret-like fields except in narrowly declared provenance contexts; raw prompt bodies and raw legacy obligation text are not exposed by the dashboard projection.
- Digest/ref provenance, owner boundaries, default-deny admission, and rollback evidence are explicit.
- No secret material was observed in the inspected landed source. No independent secret scan, SBOM, signature, provenance, or security assessment is implied by this release; host-local absolute paths in `config/bootstrap.json` are portability/privacy exposure and are not credentials.

### Validation

- The release-prep and exact landed-main gates run `scripts/release_check.py`, `scripts/validate_organ_contract.py`, the full unit suite, JSON parsing for every `contracts/*.json`, Python compileall, JavaScript syntax checks, `git diff --check`, and a PEP 517 wheel/sdist build.
- GitHub `Repo Validation` is required on the release-prep PR and the resulting landed commit. Its green result proves only the declared organ validator, tests, and JSON contract parsing; it is not an artifact, runtime, proof, or acceptance attestation.
- Artifact filenames and SHA-256 digests are recorded in the release execution evidence. Registry admission, signing, SBOM, provenance, and attestations are reported separately when absent or present.

### Notes

- This is a source/test/bootstrap release. It does not claim private organ admission, registry presence, deployment, persistent service status, live health, proof/eval verdict, semantic re-entry, master acceptance, human acceptance, or Goal completion.
- The default configuration contains host-local paths under `/srv/AbyssOS`, `/home/dionysus`, `/srv/abyss-machine`, and `/tmp`; it is a first-slice dogfood binding, not a portable deployment configuration.
- Python >=3.11 and setuptools build tooling are required. The native shell additionally requires host GTK4, Libadwaita 1, and PyGObject/WebKitGTK 6.0; those libraries are not vendored.
- No migration is required for a first public source package, but consumers of the old expected-digest snapshot must move to the current-head/history contract. v1/v2 wake schemas remain distinct, and an action intent remains deferred/non-executing.
- No intentional stable API breaking change is asserted. Because maturity is bootstrap and version is 0.x, schema consumers must treat versioned contract changes conservatively and verify exact refs.
- The complete first-parent and reachable-commit reconciliation is preserved in [`docs/RELEASE_RECONCILIATION.md`](docs/RELEASE_RECONCILIATION.md); it classifies merged, duplicate, internal/noise, generated-churn, and intentionally excluded material without turning the human notes into a commit dump.
