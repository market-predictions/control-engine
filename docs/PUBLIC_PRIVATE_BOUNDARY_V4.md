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

Every private queue mutation requires the exact observed private `main`, exact observed runtime branch head and exact observed queue blob to remain current. The carrier creates a descendant commit from that exact runtime head and submits one atomic non-force GraphQL `updateRefs` mutation containing both a no-op `main` authority fence (`beforeOid=<exact observed main>`, `afterOid=<same exact main>`) and the `control-runtime-state` advance (`beforeOid=<exact observed runtime head>`, `afterOid=<new descendant>`). If either ref precondition is stale, no ref update lands. Mandatory `main`, runtime-ref and queue readback follows every successful mutation. Stale writers fail closed rather than overwriting newer ownership.

## Stateless current-state handshake

Public issue comments are **transport/audit evidence only**. They are not a recovery ledger. Normal Runner execution never reconstructs current holder, queue, retry, lease or next-action state from earlier issue comments.

Every Scheduled invocation begins with one fresh `CONTROL_V4_RUNTIME_TICK`. The carrier reads the authoritative private state and deterministically reconciles it:

```text
fresh TICK
   ↓
read current private queue + authority
   ├─ expired holder → recover expired lock
   ├─ no live holder → select + acquire current eligible work
   └─ live holder    → return that current holder
   ↓
WORK or NO_WORK
```

For TICK-produced `WORK`, `acquired_now=true` means that exact TICK created the current holder; `acquired_now=false` means a still-live holder already existed and is being resumed. `acquired_now` is a public-safe capability fact only; it is not persisted in the queue and grants no authority by itself.

Every published carrier result is bound to the exact triggering GitHub command comment using `command_comment_id`. The Runner correlates only the command it just posted with the trusted result created for that command. It may inspect a bounded current-command result window, but it does not scan previous invocations to infer recovery state.

If a command/result exchange is missing, ambiguous or fails closed, the current invocation stops safely. It does **not** replay the TICK or EVENT and does not derive completion from transport age. The next normal Scheduled wake issues a new fresh TICK, and the carrier again reads current private truth. The private fixed non-renewable lock lease remains the sole time-based holder recovery mechanism.

A resumed holder (`acquired_now=false`) may perform read-only reasoning and holder-fenced carrier EVENTs but may not initiate a target effect. If target mutation is required, the Runner first YIELDs the resumed holder, then reacquires through a fresh TICK and proceeds only from `acquired_now=true` under the existing consequential-effect fence.

This stateless handshake deliberately retires the former public-history recovery machinery: unresolved-TICK replay, unresolved-EVENT retirement, public command-age recovery clocks, earliest-TICK reconstruction across invocations, spent-transport identities and BUSY/resume roundtrips are not current runtime semantics.

The public response is deliberately reduced to publicly observable target/candidate facts plus opaque transport identity. Raw private task identity, gap/Mission identity, acceptance text, authority blob identities, review records, blockers, lock state, queue state and Mission documents are not mirrored to the public transport. In particular, execution-lock timestamps or other lock-derived values are never emitted in a public work capsule.

### Canonical EVENT wire contract

`control_engine/v4_runtime_protocol.py` is the **single protocol owner** for `CONTROL_V4_RUNTIME_EVENT`. The workflow transports the raw issue-comment body unchanged; it contains no compatibility parser or alternate EVENT normalizer.

Every EVENT echoes the correlated trusted `WORK` capsule identity exactly:

- `run_id`;
- `task_token`;
- `repository`;
- `action`;
- `candidate` exactly when the `WORK` capsule contains one;
- `event` plus only that event type's explicitly allowed fields.

The protocol parser rejects unknown fields and malformed identities. Holder binding then requires `repository`, `action`, and the complete candidate object to match the current task resolved by the opaque token before translating that public identity into the existing private holder checks. `acquired_now` and `command_comment_id` are result-only fields and never enter an EVENT. The Runner does not construct or transmit private task IDs, Mission data, queue fields, lock state, or an alternative `holder_*` public envelope.

This single-owner rule deliberately replaces the former workflow-level compatibility normalization. Protocol adaptation is not split between YAML and Python.

The V1 carrier is deliberately activation-bounded to `integration_enabled=false`. It restores acquisition/review/repair/wait liveness without introducing merge authority. A later integration-capable carrier extension requires separate concrete need, implementation and review. V1 also supports only publicly readable target repositories; private/unreadable targets fail closed instead of adding a second target credential path. This public-read proof is required even when a BUILD task has no candidate yet: the repository name is not emitted until unauthenticated repository metadata proves the target is publicly readable.

The V3.1 GitHub Actions semantic runtime writer remains retired. No V3.1 claim/record/release path is reintroduced.

## Consequential target effects

Target mutation remains more strictly fenced than carrier-side state transitions. A target effect requires a fresh current-invocation acquisition (`acquired_now=true`), the preserved initial acquisition command identity/time, a same-holder immediate pre-effect TICK, exact holder/task/repository/action/candidate match, acquisition age no greater than 660 seconds, pre-effect result age no greater than 15 seconds, and effect plus mandatory exact readback bounded to 300 seconds. Revalidation TICKs do not renew the fixed 5400-second private lease.

This safety fence is intentionally retained because it protects consequential external effects; it is separate from the retired public-history recovery machinery.

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

Git history remains the mutation audit trail. No queue, cache, database, cursor or public mirror is added.

## Semantic boundary

Normal V4 engineering uses one ChatGPT Runner with BUILD, REVIEW and REPAIR phases. Same-Runner review is intentionally called review, not independent assurance.

External review is candidate evidence only when Mission policy requires it. Provider/quota/transport unavailability is retryable review unavailability: the carrier records `INDETERMINATE` and releases/yields the lock, but it can never manufacture an external PASS. Across later acquisition cycles, such a retryable `ACTIVE/REVIEW/EXTERNAL` item is deliberately considered only **after** ordinary productive ACTIVE work, integration-authorized READY work when integration is enabled, and eligible QUEUED work. It remains selectable when no higher-value work is available. No cooldown database, retry queue, retry counter, or second state plane is introduced.

Candidate/head/base drift is deterministic GitHub evidence and does not require Codex. When a held REVIEW candidate no longer matches the live public PR identity, the carrier returns the same stable private task to REPAIR without issuing a duplicate external review request. The carrier re-reads the live public PR identity immediately before applying any REVIEW event that can alter review state (`INTERNAL_PASS`, `INTERNAL_REPAIR`, `EXTERNAL_REQUESTED`, `EXTERNAL_FINDING`, `EXTERNAL_PASS`, or `REVIEW_UNAVAILABLE`); drift wins over the incoming event and deterministically returns the task to REPAIR.

## Consequential authority

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed in private Mission/repository/project authority.
