# Release reconciliation — `v0.1.0`

This owner-local ledger records the source range used for the first public
release. It is evidence for changelog coverage, not a replacement for the
human-first release notes.

## Release identity

| Field | Value |
|---|---|
| Published baseline | none; no SemVer tags or GitHub Releases existed |
| Historical root | `74670937a8f4c1efee61c7c7489ef563b60c5613` |
| Observed landed baseline | `c0fec92d36b0fd1f6c0c4a9802b37d22cea2c598` |
| Target | `0.1.0` / `v0.1.0` |
| Source range | all 50 commits reachable from the observed landed baseline |
| First-parent count | 20 |
| Reachable commit count | 50 |
| Active/unlanded work | excluded by ancestry; preserved in separate worktrees |

The source range was recomputed from the live `main` ref before release
preparation. The final tag must point to the later exact landed release-prep
commit, not to any local or active unlanded line.

## First-parent reconciliation

The repository has no named prior `First-Parent Reconciliation` convention, so
this release preserves the complete first-parent spine explicitly. Each entry
is either a human-facing release item, merged into another item, a duplicate
integration commit, or internal/noise with a reason.

| # | First-parent commit | Subject | Classification |
|---:|---|---|---|
| 1 | `74670937a8f4c1efee61c7c7489ef563b60c5613` | docs: establish dashboard ownership and contracts | worthy — foundation, owner boundary, package marker, bootstrap contracts and docs |
| 2 | `cc922f41ef90da775be4515d7375cb8384ae354a` | feat: add live goal projection and operator UI | worthy — initial projection, server, source adapters, web UI and tests |
| 3 | `b135b43af90a32bf1915db669d50de020830e94c` | fix: align adapters with live owner payloads | merged — projection/source-adapter correctness |
| 4 | `ac9fa1e9514f231872e64ec7f9be1b2cada22c29` | feat: add task-local correlation envelope adapter | worthy — typed correlation contract and adapter |
| 5 | `df64ffc51ca507bb8e48e6e85f9ddb61b0183086` | feat: show correlation chain in operator UI | merged — correlation UI presentation |
| 6 | `af7a27df75bca2a2b4fc35d0890984b169b42261` | fix: ignore holder handoff from input scan | merged — wake/return input hardening |
| 7 | `c780c472f378ddbd1476dad55edff299ef0d3e50` | fix: preserve filtered returns beside deferred pressure | merged — correlation/pressure correctness |
| 8 | `deeae442af33e53eeac3e6594aa79dcf369107a4` | test: follow live filtered return count | merged — regression coverage |
| 9 | `e8a13e8e139fec8e865b8e75d82a459116a07569` | fix: bind returned correlation holder to master | merged — exact owner/master binding |
| 10 | `6e50ba56a6c82dc2fdbdf8ac7d1be7e432d40a39` | feat: adapt dashboard to Codex wake receipts | worthy — wake receipt source family and bounded projection |
| 11 | `cbd5a752ea19469cf676726d717e98acc2d70f3b` | feat: add cursor-retained correlation and pressure contracts | worthy — cursor/checkpoint/observation/projection/pressure schemas and modules |
| 12 | `b7fa4eb0dce5e1b5fbc8d5a0dbee6603fd5c3447` | feat: expose pressure inbox and retention UI | merged — pressure/retention presentation |
| 13 | `69dd9dc580112a87033e8576a18e74e9d1a14492` | fix: keep replay digests stable across reads | merged — replay identity hardening |
| 14 | `b2c8e7c7fbe20df2d7e343cef5de07babd10bc09` | fix: bound Codex v1 wake provenance and unknown fields | merged — v1 provenance and null/unknown posture |
| 15 | `1b0fd3da39e4b1aa90f2c9af384d3206ba7a2fcb` | Repair wake receipt compatibility admission and parity | merged — wake admission/parity hardening |
| 16 | `9f3e4cefd2af415525e6d7b750e6b6f2516767c6` | fix: authenticate cursor provenance and collisions | merged — cursor provenance/conflict correctness |
| 17 | `454072c2f512d7d93ab99f56fc36d8613a2615ca` | test: cover recoverable cursor materialization | merged — recovery regression coverage |
| 18 | `a529ef9bee4e654df03527ecedb4bbdab4b05807` | fix: close cursor and pressure review findings | merged — schema/adapter/pressure review closure |
| 19 | `7b7dfb00bb0e97ca083abf223afa875209278e18` | docs: state recoverable redacted dashboard boundary | merged — public boundary and redaction claim |
| 20 | `950a414636996cfe67152287b759b09d458bfc06` | Normalize wake receipt attempts in derived correlation | merged — attempts normalization |

## Complete reachable-commit ledger

The following table accounts for every reachable commit, including the
first-parent entries above and the non-first-parent commits that were merged
into the landed source.

| # | Exact commit | Subject | Classification |
|---:|---|---|---|
| 21 | `530da158b11a72c8b6fcd98197706910cce2fbee` | Harden malformed wake receipt envelopes | merged — malformed receipt safety |
| 22 | `88348026ac2651204f19bab379e33904c498aae0` | fix: harden pressure cursor provenance and ledger binding | merged — pressure/cursor provenance and source binding |
| 23 | `3e200d5cdda33a91b7d523d829936d2b20e0e210` | fix: bind pressure cursor writes and diagnostics | merged — locked materialization and diagnostics |
| 24 | `d31ca79adc7233f18d54b908c2aa299a431a2f14` | fix: make pressure ledger capability opaque | merged — capability/effect ceiling |
| 25 | `8001f3a239fd8e4241bb224027ac2ea1758566cd` | merge: preserve wake receipt compatibility candidate | duplicate — merge-only integration |
| 26 | `500d0fef8f477c3282ecd2202bb52979abf505b1` | merge: reconcile cursor pressure read model | duplicate — merge-only integration |
| 27 | `6f269db09817f569f6be19462fcd1ae98ba61125` | fix: retain malformed receipt evidence during cursor rebuild | merged — malformed evidence retention |
| 28 | `9efd3a9e9c9960915fab385e222188ae2f0e2aee` | test: remove duplicate projection fixture import | internal/noise — test-fixture cleanup |
| 29 | `ae5bc022af9baf95bfdca647e13562e4b9dd8f80` | fix: retain non-object receipt envelopes safely | merged — input safety |
| 30 | `5a8d3bd1676012421b8792e32b93fc96912e4ce1` | docs: remove duplicate reconciliation summary | internal/noise — duplicate documentation cleanup |
| 31 | `c4cccc267b4a80ec395002997c09ed99cd33c4fe` | fix: admit safe v2 cursor metadata | merged — v2 cursor metadata boundary |
| 32 | `8f76a2748e8a930e1fd54b25d630486d7c0226a5` | feat: add bounded external actor activity view | worthy — allowlisted actor/process/session/terminal/usage observation surface |
| 33 | `7050b15f3979dc124b22d6403a6d1c3c837d9d54` | merge: reconcile bounded wake receipt line with actor activity | duplicate — integration merge |
| 34 | `82319b3967228b3b93c7e3adb2480fa7ff02cb2b` | merge: land repaired pressure cursor with wake and actor activity | duplicate — integration merge |
| 35 | `2e24071653438e09a99a4bddf66f8762fe899c61` | feat: establish bounded dashboard organ contract | worthy — contract, required surfaces, admission posture, release posture, validator, CI and tests |
| 36 | `6a8462714155928ce1ec63859cb6632e5b0b7878` | ci: install schema validation test dependency | merged — validation reproducibility |
| 37 | `179a271db239d57f480a1cbdf41c0dd4775100f0` | fix: generalize master filter currentness | worthy — owner currentness schema/binding and migration boundary |
| 38 | `5988ec70d6fee05a5c40eb2a6117fffca8562bb7` | test: make projection reconciliation hermetic | merged — validation hardening |
| 39 | `ce58855b722f011d6d14df7a03fdb1408b1cea16` | merge: integrate D1 organ and D8 currentness | duplicate — branch integration; PR #1 carries the semantic item |
| 40 | `1123c7dcccde645044e4839c3fcb8a2dc4478a73` | Integrate D1 organ contract with D8 master-filter currentness | duplicate — GitHub PR #1 merge commit |
| 41 | `7f0f7cc21b7f8ce87e4a8ec30d5a19e30312305e` | fix: make currentness advancement content-derived | worthy — owner-controlled advancement, rollback, idempotence and migration |
| 42 | `6a19c736ee296b1b98dd39f6e7a50e33166c5e6b` | Merge pull request #2 from 8Dionysus/luna/currentness-dogfood-20260820 | duplicate — PR #2 merge commit |
| 43 | `841179de67c40e53df0280875b1c2c52e72b47b4` | feat: add native desktop shell | worthy — native package/desktop/loopback lifecycle surface |
| 44 | `ad03a6d421a83bb3ef76493855c184fbe03e08c8` | Merge pull request #3 from 8Dionysus/luna/desktop-shell-20260820 | duplicate — PR #3 merge commit |
| 45 | `dca4fa288f6d29f1dae3f2158f5b8283b7699033` | feat: add bilingual operator UI | worthy — localization capability |
| 46 | `4f788988c57ee2bc78661d2e838ea53bf47b5bd5` | feat: add dashboard theme layer | worthy — light/dark/system theme capability |
| 47 | `79fe4e7abb72fc71a047625a29907c45ae128ccd` | integrate bilingual dark desktop UI | merged — PR #4 integration of public UI capabilities |
| 48 | `3f06b100bb1de15ce102f3a6acc9a4732132cc5c` | Merge bilingual dark integration | duplicate — PR #4 merge commit |
| 49 | `468e25d2dfbe93a1550a4ff9484cdae676513c3e` | feat: bridge native presentation preferences | worthy — strict web/native language/theme bridge |
| 50 | `c0fec92d36b0fd1f6c0c4a9802b37d22cea2c598` | Merge pull request #5 from 8Dionysus/luna/native-preference-bridge-20260821 | duplicate — PR #5 merge commit and observed landed endpoint |

No reachable commit in this source range was generated churn. Test and
documentation cleanup is marked internal/noise where it has no standalone
public behavior; merge commits are retained as duplicate integration events.

## Merged PR coverage

| PR | Merge commit | Release coverage |
|---:|---|---|
| #1 | `1123c7dcccde645044e4839c3fcb8a2dc4478a73` | D1 organ contract, D8 currentness, release posture, source validation and boundary docs |
| #2 | `6a19c736ee296b1b98dd39f6e7a50e33166c5e6b` | content-derived currentness advancement and migration/rollback semantics |
| #3 | `ad03a6d421a83bb3ef76493855c184fbe03e08c8` | GTK4/Libadwaita/WebKitGTK native shell and package lifecycle |
| #4 | `3f06b100bb1de15ce102f3a6acc9a4732132cc5c` | bilingual UI and light/dark/system theme integration |
| #5 | `c0fec92d36b0fd1f6c0c4a9802b37d22cea2c598` | strict native preference bridge and final observed landed source |

## Intentionally excluded work

The following lines were visible locally but are not ancestors of the observed
landed main and therefore are not in this release:

- `6654436196b9d8ba8c945d41b11a5ed889487c8e`, `872f955be87c3dcf6c566bc66c23957f8e921a37`, `1e375467b14b66b27df65c9b39ccdbe90572f199`, `185fdad819efe94ca72fd0a3e93ee7f2e6d32db1`, and `8baf09d64cd501dcfa58a0a21c5103d93e8ec003`: active Goal Space implementation/review/residual work.
- `a98101fa224ca323421c9416044af66df77a98a4`: active owner-aware reconciliation line.
- `651acfcf3d0f1ea55e5c83eb9d7da62ce50ea160` and `a8cae17d6f1c6036a1d7488bcc4bcc2f037acf00`: standalone bilingual/theme branches superseded by the landed PR #4 integration.
- Untracked `build/`, `dist/`, and `src/aoa_dashboard.egg-info/` in evaluation worktrees: generated churn outside the landed range, preserved and not released.

The release-prep changes themselves are intentionally outside the observed
baseline above. After the PR lands, the final report must append the exact
release-prep merge commit as the tag target and rerun the release gates against
that new source range.
