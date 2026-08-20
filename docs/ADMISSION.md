# Admission and access route

## Current state

`aoa-dashboard` is a public source repository and a bootstrap derived layer in
the federation map. It currently has `access_plane: none` and
`current_state: no_record_by_design`. The OS-private registry remains
`default_admission: deny`; no dashboard record is inserted merely because the
repository exists or the workspace can discover it.

The current private v2 source is owned by the workspace, not by this public
repository. Its host binding is selected through `AOA_SDK_ORGAN_REGISTRY` (or
the workspace manifest route), validated as
`aoa_organ_registry_source_v2`, and must remain outside Git. The exact observed
path, digest, expiry, and record count belong in owner evidence and handoff,
not in a committed public secret/config file.

## Future admission sequence

Admission is a sequence of independently owned claims:

1. `aoa-dashboard` defines a concrete read capability, source refs, effect
   ceiling, freshness and rollback behavior.
2. `aoa-sdk` validates and compiles the typed candidate; SDK presence is not
   admission.
3. The workspace owner validates the private, expiring v2 registry source and
   records a contour only after the source/access/control/runtime/proof axes
   are explicit.
4. `abyss-stack` contributes deployment/live evidence only if the contour has
   runtime effect. A source checkout or process path is not live health.
5. `aoa-evals` supplies independent proof for claims stronger than source
   shape or local validation.
6. The dashboard owner and human operator accept the bounded payload through
   their own routes.

Until all required axes are present, the state remains absent, shadow,
candidate, or denied as appropriate. A generated projection, local registry
reader, GitHub repository, or green unit test cannot promote it.

## Rollback

On drift or failed evidence, the workspace owner lowers admission to `deny` or
`shadow` first and revokes the consumer route. Preserve the source record,
digest, expiry, and receipts for review. Re-admission requires a new exact
validation cycle. Do not hand-edit a generated projection or delete the
private registry to simulate rollback.
