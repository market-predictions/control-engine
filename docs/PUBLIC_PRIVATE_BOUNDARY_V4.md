# Public / Private Boundary — Control V4

## Authority

The private repository `market-predictions/control-plane` remains the sole Control Mission/authority and mutable runtime-state plane.

The public `market-predictions/control-engine` repository owns deterministic contracts, validation and bounded transport/carrier code. It owns **no semantic runtime authority** and persists no private Control runtime state.

## Runtime writer

The one recurring ChatGPT Control Runner remains the semantic V4 Runner. Scheduled ChatGPT may read and mutate public GitHub surfaces, but current execution evidence shows direct private-repository mutation is not a reliable Scheduled capability. V4 therefore does not depend on Scheduled direct private writes.

Normal runtime mutation uses this bounded path:

```text
ChatGPT Scheduled semantic Runner
        ↓ owner-bound typed public command/event
control-engine issue #106 transport
        ↓ trusted deterministic carrier
scoped GitHub App capability: control-plane contents:write only
        ↓ exact old-ref CAS + readback
control-plane@control-runtime-state:control/DISPATCH_QUEUE.json
```

The runtime carrier is **not** a second semantic worker. It accepts no arbitrary queue document or patch. It fresh-reads current private V4 runtime authority, the bound Runner config/prompt, current V4 Mission/repository authority, and the one canonical queue; validates them with trusted public V4 contracts; applies only reviewed typed transitions; and writes only the canonical queue file.

Every private queue mutation requires the exact observed private `main`, exact observed runtime branch head and exact observed queue blob to remain current. The carrier creates a descendant commit from that exact runtime head and moves `control-runtime-state` only through non-force GraphQL `updateRefs` with `beforeOid=<exact observed runtime head>`, followed by mandatory ref and queue readback. Stale writers fail closed/retry rather than overwriting newer ownership.

Public issue comments are transport/audit evidence only. They never become queue, Mission, status or authority state. The public response is deliberately reduced to publicly observable target/candidate facts plus an opaque task token. Raw private task identity, gap/Mission identity, acceptance text, authority blob identities, review records, blockers, lock state, queue state and Mission documents are not mirrored to the public transport.

The V1 carrier is deliberately activation-bounded to `integration_enabled=false`. It restores acquisition/review/repair/wait liveness without introducing merge authority. A later integration-capable carrier extension requires separate concrete need, implementation and review. V1 also supports only publicly readable target repositories; private/unreadable targets fail closed instead of adding a second target credential path. This public-read proof is required even when a BUILD task has no candidate yet: the repository name is not emitted until unauthenticated repository metadata proves the target is publicly readable.

The V3.1 GitHub Actions semantic runtime writer remains retired. No V3.1 claim/record/release path is reintroduced.

## Status scope

`ENGINE_MANIFEST.json` is a **component-local manifest** for `market-predictions/control-engine` and is never a source for current **global Control runtime status**.

```text
semantic_runtime_authority=false
```

means this public component does not own Control semantics. It does **not** mean that the canonical Control V4 Runner is inactive, and it does not deny that this component hosts the bounded deterministic private-state carrier described above.

Current global Control status must be reconstructed from current private V4 runtime authority and the canonical `control-runtime-state` queue, with bounded target evidence when activity details are required. Public carrier comments can corroborate transport outcomes but never override private authority/state.

A consumer must never promote a component-local manifest or public carrier result into global Control state. If authoritative private current-state sources cannot be read, the result is incomplete observability.

## Retained V3.1 code

V3.1 kernel/migration/validation code may remain while it has concrete rollback, migration, carry-forward-validation or historical validation value. Retained code is passive library material once writer reachability is retired; executable source presence alone grants no runtime authority.

Runtime-only V3.1 paths converge after the maintained rollback window. Shared helpers required by canonical V4 migration/validation semantics remain only while that dependency exists.

## Read-only validation

Ordinary repository CI and read-only private validation remain separate from runtime mutation. They do not grant runtime authority.

## Private state

Canonical mutable state remains exactly one private queue file:

`market-predictions/control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`

Git history remains the mutation audit trail. No queue, cache, database or public mirror is added.

## Semantic boundary

Normal V4 engineering uses one ChatGPT Runner with BUILD, REVIEW and REPAIR phases. Same-Runner review is intentionally called review, not independent assurance.

External review is candidate evidence only when Mission policy requires it. Provider/quota/transport unavailability is retryable review unavailability: the carrier may record the bounded retryable status and release/yield the lock, but it can never manufacture an external PASS.

Candidate/head/base drift is deterministic GitHub evidence and does not require Codex. When a held REVIEW candidate no longer matches the live public PR identity, the carrier returns the same stable private task to REPAIR without issuing a duplicate external review request.

## Consequential authority

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed in private Mission/repository/project authority.