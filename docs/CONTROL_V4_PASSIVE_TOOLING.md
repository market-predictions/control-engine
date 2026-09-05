# Control V4 passive tooling

Status: current passive tooling for Control V4.

This public tooling is deliberately passive. It provides:

- JSON Schema Draft 2020-12 contracts for V4 Missions, repository authority and the canonical queue;
- deterministic static/cross-record validation;
- exact committed-Git authority loading that rejects ambiguous JSON, disables replacement refs, validates trusted V4 contracts and derives actual Mission/repository-authority blob SHAs instead of trusting caller-supplied SHA mappings;
- immutable rollback authority binding: frozen V4 authority is read from the exact recorded V4-40 40-char Git commit pin rather than ambient `HEAD`, and frozen V3.1 authority is likewise trusted-validated and loaded directly from its exact recorded pre-cutover commit object even though current private `main` no longer exposes V3.1 as current authority;
- pure helpers that model atomic acquisition and passed-review transitions for regression proof;
- review evidence validation bound to the exact stored `(candidate_sha, expected_base_branch, expected_base_sha)` identity; live target-base facts remain separate integration-guard/reconciliation inputs rather than rewriting that frozen review identity;
- pure safety guards that reject class-4 authority supersession while any persisted execution lock exists and reject integration when live candidate/base facts differ, native GitHub stale-base rejection is unproven, or Runner bypass of that guard is not excluded;
- a bounded V3.1 -> V4 transform wrapper that consumes exact committed authority blobs, fails closed unless the fenced source has zero live claims and the reviewed queued-implementation shape, and preserves migration facts only after canonical `migration_v31.validate_migration_facts()` semantics accept them;
- a bounded fact-first pre-V4-80 rollback derivation that compares current V4 Mission blobs with the immutable V4-40 pinned set, interprets V3.1 migration facts as satisfaction only through canonical exact `(mission_id, frozen_mission_revision, gap_id)` semantics, preserves that full revision identity through semantic rollback-Mission retirement, normalizes only proven satisfied prerequisites and emits only V3.1-valid pre-existing terminal/result facts.

It does **not** provide a V4 scheduler, writer workflow, GitHub runtime mutator, merge executor, provider client, broker, heartbeat, renewal protocol, second queue or second state plane.

The current global semantic runtime is the single reviewed ChatGPT Control V4 Runner governed by private V4 authority. `market-predictions/control-engine` has `semantic_runtime_authority=false`; this component-local fact must never be interpreted as global Control runtime status.

Retained V3.1 library/schema/validator material exists only where current V4 migration, rollback or historical exact-candidate validation still depends on it. `scripts/control_kernel_v31.py` is retained **only as passive source for still-binding rollback/integration regression tests**: no current workflow invokes it and it grants no current semantic runtime authority. The obsolete V3.1 current-boundary document is removed; the V4 boundary is the only current boundary document. Runtime-only V3.1 source must be deleted when those remaining regression/rollback dependencies are retired at convergence; Git history remains the provenance archive.
