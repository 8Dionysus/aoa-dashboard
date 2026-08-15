# aoa-dashboard local guidance

`aoa-dashboard` is an owner-bounded operator read model. It may own only its
derived projection, operator annotations, and non-executing action intents.

It does not own role meaning, actor mandates, runtime lifecycle, proof or eval
verdicts, reviewed memory, owner acceptance, or facts from another repository.
Those surfaces remain owned by `aoa-agents`, `aoa-skills`, `aoa-sdk`,
`abyss-stack`, `.aoa` session memory, `aoa-evals`, `aoa-memo`, `aoa-stats`, and
KAG respectively. Every displayed external fact must retain a source or
provenance reference and a claim limit.

The first slice is intentionally read-mostly and host-local. The configured
paths are bindings to real sources, not fixtures. Missing publishers are
reported as `missing` or `unknown`; a recent file timestamp is not proof of
freshness, process health, return, review, or acceptance.
