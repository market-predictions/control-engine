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

### Pre-acquisition Runner generation fence

A Scheduled invocation must not obtain acquisition authority merely because it contains text that resembles the Runner prompt. Before the invocation posts its first TICK, the canonical Runner prompt requires a read-only scheduler readback of the exact reviewed automation object, exact `:30` schedule, enabled state, current prompt identity/generation, and absence of a second enabled Control V4 Runner. Failure means zero public command writes.

The current candidate command generation is `c81e7a4f2d1b9306`. Predecessor generation `dcd5dd2495113a68` is historical-only once this candidate is adopted. This generation rotation compacts the canonical Runner prompt to make the same reviewed semantics scheduler-deployable; it changes no semantic authority, queue topology, fixed lease, or atomic EVENT holder-boundary behavior. A generation is not a reusable descriptive label: any canonical Runner prompt change that can alter command authority, acquisition, command correlation, holder-closeout or target-effect behavior requires a new previously unused generation before adoption.

This platform readback is an **operational generation/binding fence**, not a new source of Control runtime authority and not a cryptographic per-invocation credential: the platform exposes no stable Scheduled credential identifier that can be committed as authority. The complete boundary therefore remains fail-closed and layered:

1. the canonical Scheduled prompt verifies the current reviewed scheduler object before emitting any command;
2. the public workflow accepts only the exact current generation-bound `run_id` before creating the scoped private capability;
3. the carrier then fresh-validates the exact current private runtime-authority → Runner-config → prompt-blob chain before any queue transition.

The generation-bound `run_id` format identifies both the reviewed automation object and current prompt generation plus a fresh invocation-local random suffix. Old prompt generations therefore cannot accidentally remain acquisition-compatible during a maintenance-fenced cutover. This protects against stale/overlapping Runner generations; it is not presented as authentication against an arbitrary hostile actor that already controls the trusted GitHub principal or scheduler administration surface.

### Stateless transport/recovery boundary

Issue #106 is typed transport plus audit evidence only. It is never queue, lease, retry, holder or recovery state.

Every normal Scheduled invocation starts with one new unique fresh `CONTROL_V4_RUNTIME_TICK`. The carrier reads current canonical private state and decides:

```text
no live lock      -> select/acquire -> WORK or NO_WORK
expired lock      -> deterministic expired-lock recovery -> select/acquire -> WORK or NO_WORK
live foreign lock -> BUSY
```

A TICK has acquisition authority only while its immutable GitHub issue-comment `created_at` is current. The carrier workflow first enforces a **120-second maximum TICK age before it issues the scoped private write capability**. It also rejects any command whose `run_id` is not bound to the exact current Runner object/prompt generation. A TICK with an invalid, future, already-old, or wrong-generation identity therefore cannot obtain private capability.

That outer admission is necessary but not sufficient: private-authority and correlation reads consume time. After the carrier has loaded current private authority/queue state and performed the bounded same-run supersession check, it captures a fresh transition time and re-evaluates the **same immutable GitHub `created_at`** against the exact closed interval **0..120 seconds immediately before `_tick()`**. A TICK that entered the workflow just inside the age limit but aged out during those reads is rejected before transition.

A TICK transition may still need private Git-object construction before a queue write becomes durable. Therefore every central `_update_refs_exact` call reparses the current typed public command and, when it is a TICK, rechecks that same immutable `created_at` again using fresh UTC time **immediately before the GraphQL `updateRefs` mutation**. A TICK that ages out while blob/tree/commit material is being prepared is rejected before the durable private ref CAS. EVENT-driven ref CAS remains governed by exact current-holder/lease/candidate semantics and is not subjected to the TICK age fence. All three TICK age checks are stateless and persist nothing.

Same-invocation TICKs intentionally retain one `run_id` so invocation-local yielded-task exclusions remain stable. The unique command identity is instead the immutable GitHub command-comment id. Every published carrier result echoes that triggering id as `command_comment_id`; the Runner accepts a result only when it matches the exact command comment it just posted. This prevents a result from an earlier same-run TICK or EVENT from being mistaken for the current command result.

A separate protection prevents a duplicated earlier TICK from reacquiring after a later same-run holder release. After the carrier has loaded the current private authority/queue snapshot and before it performs the TICK transition, it performs one bounded read of issue #106 comments from that TICK's immutable `created_at`. It considers only canonical Control commands from the trusted `market-predictions` principal. If a later same-`run_id` TICK or EVENT already exists by immutable `(created_at, comment id)` order, the older TICK is superseded and rejected. The check is bounded to the TICK freshness window and fails closed if the bounded result set is unexpectedly saturated.

This supersession read has one purpose only: establish whether **this public command identity is still current within its invocation**. It never derives queue state, lock ownership, lease expiry, task selection, retry state, holder recovery, or forward scheduling from comments. It persists no cursor, ledger, counter, retry record or public runtime state. The decisive ordering is:

```text
fresh private authority/queue snapshot
        ↓
bounded immutable-command supersession check
        ↓
transition-time immutable-created_at freshness recheck (0..120s)
        ↓
typed TICK transition / prepare exact queue commit
        ↓
durable-CAS immutable-created_at freshness recheck (0..120s)
        ↓
exact private old-ref/blob CAS + readback
```

That ordering closes the carrier-side time and concurrency races without a transport state machine: a release that landed before the snapshot is visible as a later command and supersedes the old TICK; a release that occurs after the snapshot leaves the loaded queue holding the same run and therefore the old TICK does not perform a fresh acquisition; a command that ages out during private reads or Git-object preparation is rejected before durable mutation; any concurrent private write that invalidates the snapshot is rejected by the existing exact CAS.

The matching Runner-side liveness rule closes the remaining queued-workflow/result-publication race. After posting **any acquisition-capable TICK**—initial acquisition, post-event/post-yield acquisition, or same-run pre-effect revalidation—the Scheduled invocation remains responsible for that exact immutable command until either:

1. a trusted terminal result with the exact triggering `command_comment_id` is observed and consumed; or
2. all no-result facts are proven in order:
   - immutable TICK `created_at` is strictly more than 120 seconds old;
   - exactly one GitHub Actions run is identified for `.github/workflows/control-v4-runtime-carrier.yml`, event `issue_comment`, with exact display title `Control V4 runtime command <command_comment_id>`;
   - that exact run has terminal GitHub Actions status `completed`;
   - one final exact-command result read performed **after observing that terminal run state** still finds no correlated result.

**Age alone is never sufficient.** A carrier can durably mutate just before the 120-second boundary and still be completing mandatory private readback or public result publication after the TICK is too old to begin another transition. Before the complete no-result proof above, the Runner must not classify the TICK result as missing, end the invocation because of that missing result, or post a replacement acquisition/revalidation TICK.

This **live-TICK responsibility window** is invocation-local control flow, not recovery state. The exact correlated carrier run is ephemeral transport-execution evidence only; it is not Control queue, holder, lease, work-selection or recovery state. The rule persists no timer, cursor, retry record, scheduler state, carrier-run ledger, cancellation record, replay marker or runtime state and never derives holder/queue state from public history.

`BUSY` or `NO_WORK` ends the invocation after its correlated result is handled. Other fail-closed outcomes end the invocation according to the canonical prompt. A TICK result may be classified as missing only under the full terminal-run responsibility rule above. A later normal Scheduled wake starts again with a new fresh TICK. The private queue's fixed non-renewable 5400-second lease plus carrier-side objectively expired-lock recovery is the sole cross-invocation holder/crash-recovery mechanism.

Current V4 therefore has no startup scan of public issue history to decide forward progress, no unresolved-TICK or unresolved-EVENT runtime state, no same-command replay loop, no public replay clock, no public EVENT-retirement/spent-identity clock, no transport cursor/retry ledger, and no cross-invocation holder reconstruction from public comments.

A lost transport response is not evidence about whether a private transition landed. For TICK, only after the exact correlated carrier run is terminal and the post-terminal final exact-command read still finds no result may that invocation classify the result missing; a later invocation then asks current canonical private state again rather than replaying transport history.

### Holder closeout after WORK — atomic EVENT boundary

A trusted `WORK` result creates an invocation-local **holder-closeout obligation**. The Runner must not normally end while that exact acquired holder is still live merely because reasoning, target facts, candidate drift, time pressure, or a safe target effect cannot proceed.

Every accepted semantic EVENT is an **atomic holder boundary**. The semantic transition and release of the exact current holder are part of the same next queue image and therefore land in the same exact private queue CAS. The carrier never returns a new `WORK` capsule directly from an accepted EVENT. It returns `READY` when that EVENT made the task READY, otherwise `YIELDED`, and both results imply that the holder is absent in the mandatory private readback.

This removes the architectural dependency on one Scheduled ChatGPT invocation surviving across a semantic phase boundary. Further work after a progress EVENT is reacquired only through a fresh same-`run_id` TICK, which asks current canonical private state again. `CANDIDATE_READY`, `INTERNAL_PASS`, `INTERNAL_REPAIR` and `EXTERNAL_FINDING` are progress boundaries: their task token is not added to the invocation-local yielded set, so the next fresh TICK may reacquire the same task in its new phase. `YIELD`, `REVIEW_UNAVAILABLE` and `EXTERNAL_REQUESTED` are wait/release boundaries: their task token is added when the invocation continues so unrelated eligible work can proceed without immediate same-task reacquisition.

For REPAIR candidate drift, the Runner first performs bounded read-only target reconciliation. A safely reviewable already-published candidate on the same governed PR, head branch and base context is reconciled with exactly one existing `CANDIDATE_READY` EVENT populated from the exact `live_candidate` fields; no duplicate target write is required. Its correlated `YIELDED` proves the REPAIR holder was atomically released, and REVIEW is reacquired only with a fresh TICK. Ambiguous, out-of-scope, wrong-identity or otherwise unreconcilable drift is closed out with exactly one existing `YIELD` EVENT while the holder remains valid.

Candidate drift detected while an incoming REVIEW EVENT is being revalidated follows the same invariant: the deterministic REVIEW→REPAIR reconciliation and holder release are written together in one queue CAS, and the EVENT returns `YIELDED`, never `WORK`.

A missing or ambiguous EVENT result remains fail-closed transport ambiguity. The Runner never blind-replays that EVENT and never fabricates holder-release evidence. This obligation is invocation-local and derives only from the trusted WORK and exact correlated EVENT result; it never reconstructs private holder state from public history. The rule reuses existing transitions and adds no scheduler, queue, state plane, recovery ledger, cancellation protocol, lease renewal or carrier semantic authority.

### Maintenance-fenced prompt generation changes

The public carrier accepts only the exact reviewed canonical Runner prompt generation. A prompt-generation change across public `control-engine` trust code and private `control-plane` authority is therefore performed under an **outside-Runner maintenance fence**, not by keeping two current prompt hashes trusted in normal operation: disable and read back the same canonical Runner, merge the reviewed public trust generation, trusted-validate and exact-old-SHA adopt the reviewed private authority generation, rebind/read back that same Runner, then re-enable. During the bounded interval between public trust merge and private adoption the Runner remains disabled, so no normal runtime command is expected to succeed against a mixed generation. This avoids a permanent compatibility trust window while preserving one current prompt truth after adoption.

Dual-current prompt trust is not a supported steady-state or rollout mechanism. Git history carries predecessor identity; current runtime binding carries one accepted prompt hash and one current command generation.

### Canonical TICK/EVENT wire contract

`control_engine/v4_runtime_protocol.py` is the **single semantic protocol owner** for `CONTROL_V4_RUNTIME_TICK` and `CONTROL_V4_RUNTIME_EVENT`. The workflow transports the raw issue-comment body unchanged; it contains no compatibility parser or alternate EVENT normalizer. Workflow admission may reject stale/wrong-generation commands before private capability, and the result publisher adds only the immutable triggering `command_comment_id` as transport-correlation metadata.

Every EVENT echoes the correlated trusted `WORK` capsule identity exactly:

- `run_id`;
- `task_token`;
- `repository`;
- `action`;
- `candidate` exactly when the `WORK` capsule contains one;
- `event` plus only that event type's explicitly allowed fields.

`command_comment_id` is never copied into an EVENT. It identifies the public command/result pair only and is not semantic holder identity.

The protocol parser rejects unknown fields and malformed identities. Holder binding then requires `repository`, `action`, and the complete candidate object to match the current task resolved by the opaque token before translating that public identity into the existing private holder checks. The Runner does not construct or transmit private task IDs, Mission data, queue fields, lock state, or an alternative `holder_*` public envelope.

This single-owner rule deliberately replaces the former workflow-level compatibility normalization. Protocol adaptation is not split between YAML and Python.

The V1 carrier is deliberately activation-bounded to `integration_enabled=false`. It restores acquisition/review/repair/wait liveness without introducing merge authority. A later integration-capable carrier extension requires separate concrete need, implementation and review. V1 also supports only publicly readable target repositories; private/unreadable targets fail closed instead of adding a second target credential path. This public-read proof is required even when a BUILD task has no candidate yet: the repository name is not emitted until public repository metadata proves the target is publicly readable.

The V3.1 GitHub Actions semantic runtime writer remains retired. No V3.1 claim/record/release path is reintroduced.

## Consequential target effects

Transport success does not authorize a target mutation. Any non-transport target/review write additionally requires fresh acquisition in the current Scheduled invocation, exact same-run pre-effect revalidation, bounded freshness/time windows, current target identity, sufficient remaining private lease, and mandatory exact effect readback. The second same-run TICK is revalidation only and never renews the fixed private lease. It must itself pass all TICK age boundaries and remains subject to the same live-TICK responsibility window; its result must carry the exact triggering `command_comment_id`, so a stale or late result from an older same-run TICK cannot satisfy the pre-effect fence. A fresh phase reacquisition creates a fresh acquisition identity for any subsequent target effect.

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

Candidate/head/base drift is deterministic GitHub evidence and does not require Codex. When a held REVIEW candidate no longer matches the live public PR identity, the carrier returns the same stable private task to REPAIR without issuing a duplicate external review request. The carrier re-reads the live public PR identity immediately before applying any REVIEW event that can alter review state (`INTERNAL_PASS`, `INTERNAL_REPAIR`, `EXTERNAL_REQUESTED`, `EXTERNAL_FINDING`, `EXTERNAL_PASS`, or `REVIEW_UNAVAILABLE`); drift wins over the incoming event, atomically returns the task to REPAIR and releases the holder in that same EVENT queue CAS.

## Consequential authority

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed in private Mission/repository/project authority.
