# Control V4 passive tooling

Status: candidate-only preparation for `market-predictions/control-plane#224`.

This public tooling is deliberately passive. It provides:

- JSON Schema Draft 2020-12 contracts for V4 Missions, repository authority and the canonical queue;
- deterministic static/cross-record validation;
- exact committed-Git authority loading that rejects ambiguous JSON, reads inert regular blobs from `HEAD`, validates the trusted V4 contracts, and derives the actual Mission/repository-authority blob SHAs instead of trusting caller-supplied SHA mappings;
- pure helpers that model atomic acquisition and the passed-review transition for regression proof;
- review evidence validation bound to the exact `(candidate_sha, expected_base_branch, expected_base_sha)` identity so base-only drift invalidates prior PASS evidence;
- pure safety guards that reject class-4 authority supersession while any persisted execution lock exists and reject integration when live candidate/base facts differ, native GitHub stale-base rejection is unproven, or Runner bypass of that guard is not excluded;
- a bounded V3.1 -> V4 transform wrapper that consumes the exact committed V4 authority blobs and fails closed unless the fenced source has zero live claims and the reviewed queued-implementation shape;
- a bounded fact-first pre-V4-80 rollback derivation that can require the current committed V4 Mission blob set to equal the exact V4-40 frozen set, normalizes satisfied prerequisites and emits only V3.1-valid pre-existing terminal/result facts.

It does **not** provide a V4 scheduler, writer workflow, GitHub mutator, merge executor, provider client, broker, heartbeat, renewal protocol, second queue or second state plane.

The repository manifest remains `CONTROL_AUTONOMY_V3_1` while this tooling is passive. V4 activation is governed separately by the reviewed V4 architecture and requires the V4-30 protection/capability fence before any V3.1 writer retirement or Runner activation.
