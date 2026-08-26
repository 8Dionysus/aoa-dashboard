# Goal context consumers

`src/aoa_dashboard/goal_context.py` consumes two explicit, read-only owner
publications for the selected Goal and exact master thread:

- `aoa-session-memory:goal-thread-board` at the exact merged owner result
  `f19b598368d9422152c6ca41d09ffe5de22637dd`;
- `aoa-agents:goal-participant-graph` at the exact owner contract
  `db7b7f7ac7465406b3a90ca26d3cf31ac81706fe`.

Bindings are supplied under `goal_context_sources.thread_board` and
`goal_context_sources.participant_graph` (or the corresponding legacy
top-level source keys) and are never discovered by path scanning. A runtime
binding may carry them under `sources.goal_context`; path or owner capability
transport remains explicit and read-only.

The thread board contributes only reviewed public-safe item identity, source
page order, structural parent/fork relations, and its own negative states. A
missing branch publisher stays missing. The participant graph contributes only
dimension states and a publisher-owned `relation_key` summary; records are
admitted only when the binding supplies an exact publisher scope. Names, raw
payloads, prompts, transcript bodies, paths, processes, model metadata,
liveness, completion, proof, acceptance, and action execution are not inferred.

The browser shows the board in the existing Goal Inspector and assignment
dimensions in the People lens. Source refs are behind closed optional detail;
Observe remains a read model and Operate remains local non-executing intent
recording.
