# Control V4 trusted passive tooling

Status: current trusted deterministic support for the live Control V4 architecture.

This public tooling is deliberately passive. It provides:

- JSON Schema Draft 2020-12 contracts for V4 Missions, repository authority and the canonical queue;
- deterministic static/cross-record validation;
- exact committed-Git authority loading that rejects ambiguous JSON, disables replacement refs, validates trusted V4 contracts and derives actual Mission/repository-authority blob SHAs instead of trusting caller-supplied SHA mappings;
- immutable rollback authority binding: frozen V4 authority is read from the exact recorded V4-40 Git commit pin, and frozen V3.1 authority is trusted-validated and loaded directly from its exact recorded pre-cutover commit object rather than from current private `main`;
- pure helpers that model acquisition, review transitions, authority supersession, integration safety and rollback for regression proof;
- review evidence validation bound to the exact stored `(candidate_sha, expected_base_branch, expected_base_sha)` identity; live target-base facts remain separate integration-guard/reconciliation inputs rather than rewriting that frozen review identity;
- pure safety guards that reject class-4 authority supersession while any persisted execution lock exists and reject integration when live candidate/base facts differ, native GitHub stale-base rejection is unproven, or Runner bypass of that guard is not excluded;
- bounded V3.1 -> V4 and pre-V4-80 rollback helpers that use frozen historical authority, not a competing current V3.1 control plane.

It does **not** provide a V4 scheduler, semantic runtime writer, merge executor, provider client, broker, heartbeat, lease renewal protocol, second queue or second state plane.

The live semantic runtime is the one reviewed ChatGPT Scheduled V4 Runner bound by private V4 authority. This repository has component-local `semantic_runtime_authority=false`; it supplies deterministic validation/transition tooling only. Retained V3.1 code/schema support exists solely for bounded pre-V4-80 migration/rollback validation and has no current runtime authority.
