# Public / Private Boundary — Control Autonomy V3.1

Status: **historical / rollback-only support before V4-80**.

This document no longer defines current Control runtime authority. Current authority is Control V4. It is retained only because the pre-V4-80 rollback path still validates frozen historical V3.1 commits with trusted public code.

## Historical V3.1 boundary

Under V3.1 the private repository `market-predictions/control-plane` was the Control planning/authority and runtime-state plane, while `market-predictions/control-engine` supplied the deterministic Control Kernel writer. The retired workflow was `/.github/workflows/control-kernel-v3-1.yml`; it is no longer present on current public `main` and is not a current execution route.

Canonical V3.1 runtime state consisted of `control/DISPATCH_QUEUE.json` plus immutable worker results. Semantic workers A1/B1 did not directly write canonical state, and integration was deterministic rather than semantic worker work.

## Current V4 boundary

Current Control uses the reviewed scheduled V4 Runner as the sole semantic runtime. Private `main` contains current V4 declarative authority; `control-runtime-state:control/DISPATCH_QUEUE.json` is the single mutable runtime document. Public Control Engine tooling is deterministic/passive and has `semantic_runtime_authority=false`.

V3.1 schemas, validator and deterministic code retained in this repository may be used only to validate or derive bounded migration/rollback behavior against exact frozen historical commits. They do not authorize a V3.1 scheduler, writer, worker topology, queue, integration path or current-status interpretation.

Historical implementations remain available from Git history. Do not reconstruct a current V3.1 runtime from retained rollback code.
