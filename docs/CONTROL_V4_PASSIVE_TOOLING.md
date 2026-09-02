# Control V4 passive tooling

Status: candidate-only preparation for `market-predictions/control-plane#224`.

This public tooling is deliberately passive. It provides:

- JSON Schema Draft 2020-12 contracts for V4 Missions, repository authority and the canonical queue;
- deterministic static/cross-record validation;
- pure helpers that model atomic acquisition and the passed-review transition for regression proof;
- a bounded V3.1 -> V4 transform that fails closed unless the fenced source has zero live claims and the reviewed queued-implementation shape;
- a bounded fact-first pre-V4-80 rollback derivation that normalizes satisfied prerequisites and emits only V3.1-valid pre-existing terminal/result facts.

It does **not** provide a V4 scheduler, writer workflow, GitHub mutator, merge executor, provider client, broker, heartbeat, renewal protocol, second queue or second state plane.

The repository manifest remains `CONTROL_AUTONOMY_V3_1` while this tooling is passive. V4 activation is governed separately by the reviewed V4 architecture and requires the V4-30 protection/capability fence before any V3.1 writer retirement or Runner activation.
