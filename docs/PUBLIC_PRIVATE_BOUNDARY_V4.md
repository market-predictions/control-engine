# Public / Private Boundary — Control V4

```text
document_id=PUBLIC_PRIVATE_BOUNDARY_V4
status=CURRENT
source_of_truth=GITHUB
```

## Authority

Private `market-predictions/control-plane` is the sole Mission, runtime-authority and mutable runtime-state plane.

Public `market-predictions/control-engine` owns deterministic contracts, validation and bounded transport/carrier code. It owns no semantic runtime authority and persists no private Control runtime state. A component-local manifest or public carrier result must never be promoted into global Control state; global status is reconstructed from current private authority/queue truth plus bounded target evidence when needed.

Canonical mutable state is exactly:

`market-predictions/control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`

Git history is the mutation audit trail. There is no second queue, database, retry ledger or recovery state plane.

## One Runner, bounded transport

The one recurring ChatGPT `Control V4 Runner` is the semantic executor. It emits owner-bound typed TICK/EVENT commands through public issue #106. Public comments are transport/audit evidence only; they never become queue, Mission, holder, lease, status or authority state.

The trusted public carrier obtains only the scoped private capability required to apply deterministic queue transitions. Public results contain only a bounded safe projection and opaque task token; private Mission/acceptance/authority/queue/lock content is not mirrored publicly.

## Runtime transaction boundary

Every private queue mutation is prepared from an exact fresh private snapshot and requires:

- exact private `main` authority SHA;
- exact `control-runtime-state` SHA;
- exact current queue blob;
- current typed command identity;
- applicable TICK freshness or EVENT holder identity.

The carrier creates one descendant runtime commit and submits one atomic non-force GraphQL `updateRefs` mutation containing:

```text
main:                  expected SHA -> same SHA
control-runtime-state: expected SHA -> new queue commit
```

The no-op `main` update is the authority fence. If either expected ref is stale, the atomic update is rejected.

**A successful `updateRefs` response is the definitive commit acknowledgement.** The carrier performs no fallible Git-ref, branch-projection or queue-content read after that successful CAS. A second network observation cannot strengthen the atomic transaction and previously created the invalid state `durable success + public ERROR`. The next command reloads and validates canonical private truth afresh.

## TICK

TICK is intentionally limited to:

```text
fresh admission
  -> fresh private authority/queue snapshot
  -> bounded same-run supersession check
  -> transition-time freshness check
  -> expired-holder recovery when required
  -> select task
  -> bounded public target eligibility/candidate observation when needed
  -> acquire
  -> final freshness check immediately before CAS
  -> atomic CAS
  -> WORK
```

Any public target read needed to prove the target is supported or to supply the existing REPAIR compatibility hint occurs **before a new holder CAS**. Semantic candidate-drift decisions do not occur on TICK; they occur at EVENT.

TICK performs no target-repository or pull-request network verification after durable ownership is acquired. Acquisition must not be followed by fallible network work that can turn a successful holder write into a reported failure. A same-run TICK that merely revalidates an already-held REPAIR task may refresh its read-only compatibility hint because that command performs no holder write.

A live foreign holder returns `BUSY`; no eligible work returns `NO_WORK`. The fixed private lease remains non-renewable. Objectively expired-holder recovery is derived only from canonical private state.

## EVENT

EVENT is the semantic verification/transition boundary:

```text
bind exact WORK identity
  -> verify current holder/lease/candidate semantics
  -> perform target/candidate read only when that event requires it
  -> compute semantic transition
  -> transition + holder release in one queue image
  -> atomic CAS
  -> READY or YIELDED
```

Review/candidate events re-resolve the live target PR when current target identity can affect the transition. Candidate drift wins over an incoming review event and returns the task to REPAIR while releasing the holder in that same queue CAS.

Every accepted semantic EVENT is an atomic holder boundary. It never returns a new WORK capsule directly.

## Command freshness and correlation

The outer workflow rejects stale/wrong-generation TICK commands before creating private capability. The carrier separately checks the immutable GitHub command `created_at` against the current 0..120-second window before `_tick()` and again immediately before a durable CAS. A later same-run typed command supersedes an older TICK through the bounded issue-comment supersession read.

Every public result echoes the immutable triggering `command_comment_id`. Same-invocation TICKs may share `run_id`; command-comment identity is the exact transport correlation key.

The Runner remains responsible for an acquisition-capable TICK until it receives the exact correlated terminal result or proves the exact carrier run terminal and a final post-terminal result read still finds no correlated result. Age alone is not missing-result evidence.

## Consequential target effects

Transport success does not authorize arbitrary target mutation. Consequential target/review writes remain governed by current Runner instructions, fresh holder identity, target identity, lease sufficiency and exact effect readback. The second same-run TICK remains revalidation only and never renews the private lease.

## Activation limits

The current carrier is bounded to `integration_enabled=false`. It provides acquisition, review, repair and wait-state transport only; it has no merge/integration authority.

The current carrier also relies on publicly readable target repositories. General private-target credentials are not part of V4 current scope. Unsupported/private target eligibility therefore fails closed before a new holder is acquired; target/candidate EVENT verification remains fail closed at the semantic boundary.

## Retired and explicitly absent mechanisms

Current V4 does **not** use:

- post-CAS Git-ref polling or retry;
- post-CAS private-main readback;
- post-CAS queue/blob readback;
- TICK-side semantic candidate-drift reconciliation;
- target/PR network verification after a new acquire CAS;
- V3.1 semantic runtime writers;
- a second scheduler or semantic worker;
- a second queue or public runtime-state mirror;
- a retry ledger, cursor, heartbeat, lease renewal or cancellation state plane;
- generic Mission-to-queue root-work materialization;
- candidate-less BUILD execution;
- special `OVERIGE` runtime semantics;
- integration authority.

Retired mechanisms remain only in Git history, not as competing current code or normative documentation.

## Current product boundary

`market-predictions/overige` may be registered as an inert governed Mission/repository. `[control] task overige: ...` is **not** end-to-end executable until generic root-work materialization and initial BUILD execution are separately justified and implemented. That future feature must reuse the same Runner and canonical queue rather than create another intake/runtime system.
