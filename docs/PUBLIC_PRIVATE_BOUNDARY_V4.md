# Public / Private Boundary — Control V4

## Authority

The private repository `market-predictions/control-plane` remains the sole Control Mission/authority and mutable runtime-state plane.

The public `market-predictions/control-engine` repository is a deterministic library and validation surface. It owns no active Control runtime writer under V4 and persists no private Control runtime state.

## Runtime writer

After V4 cutover, canonical runtime mutation is performed only by the one recurring ChatGPT Control Runner through the connected GitHub contents surface using exact blob-SHA compare-and-swap.

The V3.1 GitHub Actions runtime writer is retired at the V4 activation fence only after reversible fencing, proof of the exact private-main authority-adoption path using the reviewed exact-old-SHA `updateRefs.beforeOid` condition, and proof of the exact scheduled Runner effective capability. Native branch protection on private `control-plane@main` is optional defense in depth under the accepted V4 risk posture; it is not a retirement prerequisite. No GitHub Actions workflow in this repository may mutate `control-runtime-state` under normal V4 operation.

## Status scope

`ENGINE_MANIFEST.json` is a **component-local manifest** for `market-predictions/control-engine`. Its runtime-related fields describe only whether this public engine component owns semantic runtime authority or an active runtime writer.

The manifest is never a source for current **global Control runtime status**. In particular:

```text
semantic_runtime_authority=false
```

means that the public engine is deterministic tooling and does not itself own the V4 semantic runtime. It does **not** mean that the canonical Control V4 Runner is inactive.

Current global Control status must be reconstructed from the current private V4 runtime authority and the canonical `control-runtime-state` queue, with bounded recent Git/target evidence when activity details are required. Scheduler observations may corroborate liveness but are not semantic authority. Durable documentation may interpret those live facts but may not override them.

A consumer must never promote a component-local manifest field into global Control state. If the authoritative private current-state sources cannot be read, the correct result is incomplete observability, not a fallback conclusion derived from this manifest.

## Retained V3.1 code

V3.1 kernel/migration/validation code may remain while it has concrete rollback, migration, carry-forward-validation or historical validation value. Retained code is passive library material once writer reachability is retired; executable source presence alone grants no runtime authority.

Runtime-only V3.1 paths converge after the maintained rollback window. Shared helpers required by canonical V4 migration/validation semantics remain only while that dependency exists.

## Read-only validation

Ordinary repository CI and read-only private validation may remain active when they have no canonical runtime write capability.

## Private state

Canonical mutable state is the single private queue file:

`market-predictions/control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`

Git history is the mutation audit trail.

## Semantic boundary

Normal V4 engineering uses one ChatGPT Runner with separate BUILD, REVIEW and REPAIR phases. Same-runner review is intentionally called review, not independent assurance.

External review is candidate evidence only when Control architecture/runtime changes or a Mission explicitly requires it. It is not a second Control worker or state plane.

## Consequential authority

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed in private Mission/repository/project authority.
