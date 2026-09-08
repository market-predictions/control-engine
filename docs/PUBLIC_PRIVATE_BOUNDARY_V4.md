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

Every private queue mutation requires the exact observed private `main`, exact observed runtime branch head and exact observed queue blob to remain current. The carrier creates a descendant commit from that exact runtime head and submits one atomic non-force GraphQL `updateRefs` mutation containing both a no-op `main` authority fence (`beforeOid=<exact observed main>`, `afterOid=<same exact main>`) and the `control-runtime-state` advance (`beforeOid=<exact observed runtime head>`, `afterOid=<new descendant>`). If either ref precondition is stale, no ref update lands. Mandatory `main`, runtime-ref and queue readback follows every successful mutation. Stale writers fail closed/retry rather than overwriting newer ownership.

Public issue comments are transport/audit evidence only. They never become queue, Mission, status or authority state. The public response is deliberately reduced to publicly observable target/candidate facts plus an opaque task token. Raw private task identity, gap/Mission identity, acceptance text, authority blob identities, review records, blockers, lock state, queue state and Mission documents are not mirrored to the public transport. In particular, execution-lock timestamps or other lock-derived values are never emitted in a public work capsule.

### Stateless transport/recovery boundary

Issue #106 is typed transport plus audit evidence only. It is never queue, lease, retry, holder or recovery state.

Every normal Scheduled invocation starts with one new unique fresh `CONTROL_V4_RUNTIME_TICK`. The carrier reads current canonical private state and decides:

```text
no live lock      -> select/acquire -> WORK or NO_WORK
expired lock      -> deterministic expired-lock recovery -> select/acquire -> WORK or NO_WORK
live foreign lock -> BUSY
```

A TICK has acquisition authority only while its immutable GitHub issue-comment `created_at` is current. The carrier workflow enforces a **120-second maximum TICK admission age before it issues the scoped private write capability**. A TICK with an invalid, future, or older timestamp cannot reach private state and therefore cannot create a delayed/orphan lease after the Scheduled invocation that posted it has already moved on. This 120-second bound is an admission fence only: it is not public runtime state, is never persisted, does not trigger replay, and is never used to reconstruct holder/recovery state from issue history. EVENT semantics remain protected by exact current-holder, unexpired-lease and candidate/base validation in the canonical protocol/carrier path.

`BUSY`, `NO_WORK`, a missing/ambiguous result, or another fail-closed transport outcome ends only that invocation. A later normal Scheduled wake starts again with a new fresh TICK. The private queue's fixed non-renewable 5400-second lease plus carrier-side objectively expired-lock recovery is the sole cross-invocation holder/crash-recovery mechanism.

Current V4 therefore has no startup scan of public issue history to decide forward progress, no unresolved-TICK or unresolved-EVENT runtime state, no same-command replay loop, no public replay clock, no public EVENT-retirement/spent-identity clock, no transport cursor/retry ledger, and no cross-invocation holder reconstruction from public comments.

A lost transport response is not evidence about whether a private transition landed. The next invocation asks current canonical private state again rather than replaying transport history.

### Maintenance-fenced prompt generation changes

The public carrier accepts only the exact reviewed canonical Runner prompt generation. A prompt-generation change across public `control-engine` trust code and private `control-plane` authority is therefore performed under an **outside-Runner maintenance fence**, not by keeping two current prompt hashes trusted in normal operation: disable and read back the same canonical Runner, merge the reviewed public trust generation, trusted-validate and exact-old-SHA adopt the reviewed private authority generation, rebind/read back that same Runner, then re-enable. During the bounded interval between public trust merge and private adoption the Runner remains disabled, so no normal runtime command is expected to succeed against a mixed generation. This avoids a permanent compatibility trust window while preserving one current prompt truth after adoption.

### Canonical TICK/EVENT wire contract

`control_engine/v4_runtime_protocol.py` is the **single protocol owner** for `CONTROL_V4_RUNTIME_TICK` and `CONTROL_V4_RUNTIME_EVENT`. The workflow transports the raw issue-comment body unchanged; it contains no compatibility parser or alternate EVENT normalizer.

Every EVENT echoes the correlated trusted `WORK` capsule identity exactly:

- `run_id`;
- `task_token`;
- `repository`;
- `action`;
- `candidate` exactly when the `WORK` capsule contains one;
- `event` plus only that event type's explicitly allowed fields.

The protocol parser rejects unknown fields and malformed identities. Holder binding then requires `repository`, `action`, and the complete candidate object to match the current task resolved by the opaque token before translating that public identity into the existing private holder checks. The Runner does not construct or transmit private task IDs, Mission data, queue fields, lock state, or an alternative `holder_*` public envelope.

This single-owner rule deliberately replaces the former workflow-level compatibility normalization. Protocol adaptation is not split between YAML and Python.

The V1 carrier is deliberately activation-bounded to `integration_enabled=false`. It restores acquisition/review/repair/wait liveness without introducing merge authority. A later integration-capable carrier extension requires separate concrete need, implementation and review. V1 also supports only publicly readable target repositories; private/unreadable targets fail closed instead of adding a second target credential path. This public-read proof is required even when a BUILD task has no candidate yet: the repository name is not emitted until unauthenticated repository metadata proves the target is publicly readable.

The V3.1 GitHub Actions semantic runtime writer remains retired. No V3.1 claim/record/release path is reintroduced.

## Consequential target effects

Transport success does not authorize a target mutation. Any non-transport target/review write additionally requires fresh acquisition in the current Scheduled invocation, exact same-run pre-effect revalidation, bounded freshness/time windows, current target identity, sufficient remaining private lease, and mandatory exact effect readback. The second same-run TICK is revalidation only and never renews the fixed private lease.

Lost, timed-out or ambiguous side effects are reconciled fact-first and never blindly retried.

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

Git history remains the mutation audit trail. No queue, cache, database, public mirror, retry ledger or recovery database is added.

## Semantic boundary

Normal V4 engineering uses one ChatGPT Runner with BUILD, REVIEW and REPAIR phases. Same-Runner review is intentionally called review, not independent assurance.

External review is candidate evidence only when Mission policy requires it. Provider/quota/transport unavailability is retryable review unavailability: the carrier records `INDETERMINATE` and releases/yields the lock, but it can never manufacture an external PASS. Across later acquisition cycles, such a retryable `ACTIVE/REVIEW/EXTERNAL` item is deliberately considered only **after** ordinary productive ACTIVE work, integration-authorized READY work when integration is enabled, and eligible QUEUED work. It remains selectable when no higher-value work is available. No cooldown database, retry queue, retry counter, or second state plane is introduced.

Candidate/head/base drift is deterministic GitHub evidence and does not require Codex. When a held REVIEW candidate no longer matches the live public PR identity, the carrier returns the same stable private task to REPAIR without issuing a duplicate external review request. The carrier re-reads the live public PR identity immediately before applying any REVIEW event that can alter review state (`INTERNAL_PASS`, `INTERNAL_REPAIR`, `EXTERNAL_REQUESTED`, `EXTERNAL_FINDING`, `EXTERNAL_PASS`, or `REVIEW_UNAVAILABLE`); drift wins over the incoming event and deterministically returns the task to REPAIR.

## Consequential authority

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed in private Mission/repository/project authority.
