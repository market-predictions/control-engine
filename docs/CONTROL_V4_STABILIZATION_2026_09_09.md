# CONTROL V4 STABILIZATION — 2026-09-09

```text
document_id=CONTROL_V4_STABILIZATION_2026_09_09
status=CURRENT_STABILIZATION_RECORD
source_of_truth=GITHUB
scope=RUNTIME_TRANSACTION_SIMPLIFICATION
```

## Objective

Restore one-to-one correspondence between a successful durable private queue mutation and the carrier result while reducing the runtime to the smallest sound transaction model.

Two live failures proved the prior model was wrong at the boundary: the exact private `updateRefs` compare-and-swap successfully advanced `control-runtime-state`, but fallible verification performed after that durable mutation could still produce `FAIL_CLOSED`. This created the invalid observable combination `durable success + public ERROR` and left a holder that the Runner believed had not been acquired.

## Current design

The runtime follows two deliberately small rules:

```text
TICK  = pre-CAS eligibility -> acquire -> WORK
EVENT = verify semantics -> transition + release
```

### Atomic CAS is the commit boundary

Before a queue write the carrier verifies current private authority, runtime ref, queue blob and command freshness. The GraphQL `updateRefs` mutation atomically:

1. fences private `main` at the exact expected authority SHA with a no-op before/after OID;
2. advances `control-runtime-state` only from the exact expected old SHA to the newly created queue commit.

A successful `updateRefs` response is the definitive commit acknowledgement. The carrier performs no Git-ref polling, branch-projection readback or queue reread after that acknowledgement. Such reads cannot strengthen the atomic transaction and can introduce a false negative after durable success. Every subsequent command reloads and validates canonical private state afresh.

### TICK stops at WORK after the holder CAS

A TICK may recover an expired holder and select one eligible task. Any bounded public target check required to prove the selected target is supported, or to provide the existing REPAIR `live_candidate` compatibility hint, occurs before a **new** holder CAS. The task is then acquired through the exact CAS and the carrier returns a bounded public-safe WORK capsule with no further target/PR network I/O after that acquire succeeds.

Semantic candidate-drift reconciliation remains on EVENT boundaries such as candidate-ready and review transitions, where current target identity can legitimately decide whether a transition is accepted, reconciled or rejected. A same-run TICK over an already-existing REPAIR holder may refresh its read-only compatibility hint because that command does not create a new holder write.

## Preserved invariants

This simplification does not alter:

- the single canonical ChatGPT Scheduled Runner;
- the single mutable private V4 queue;
- private control-plane Mission/runtime authority;
- public issue transport-only semantics;
- TICK admission, supersession and freshness fences;
- exact old-ref CAS and private-main authority fence;
- public-target eligibility before a new public WORK holder is exposed;
- EVENT holder/token/candidate identity checks;
- atomic semantic EVENT transition plus holder release;
- fixed non-renewable lease semantics;
- `integration_enabled=false` and no merge authority;
- `principal_manual_relay_count=0`;
- fail-closed handling before a durable commit boundary.

## Removed obsolete complexity

The following mechanisms are retired from current runtime code and documentation:

- post-CAS Git-ref polling/retry;
- post-CAS private-main reread;
- post-CAS queue/blob reread;
- any claim that a successful atomic CAS still requires a second network observation to become committed;
- TICK-side semantic candidate-drift reconciliation;
- target/PR network verification after a new acquire CAS;
- unsupported-target blocking performed only after ownership had already been persisted.

Git history remains the audit history for these retired mechanisms; they are not retained as parallel current code paths.

## Explicitly out of scope

This stabilization does not add:

- generic Mission-to-queue root-work materialization;
- candidate-less BUILD execution;
- special OVERIGE runtime logic;
- another queue, scheduler, task type, inbox, retry ledger or state plane;
- integration/merge authority;
- a second Runner or scheduler object.

The same canonical Runner is intentionally rebound to reviewed generation `f7beb2a3571eae1f` because its command-authority contract changed; that trust-anchor rotation is part of this stabilization, not new runtime architecture.

`market-predictions/overige` may remain registered inertly, but `[control] task overige: ...` is not end-to-end supported until the separate root-work intake gap is explicitly implemented.

## Definition of done

This stabilization is DONE only when all are true:

- focused tests prove no post-CAS failure path remains in `_write_queue_exact`;
- focused tests prove a new-acquire TICK contains no fallible target-network dependency after its holder CAS;
- existing stale/EVENT/CAS/public-boundary safety regressions remain green;
- full exact-head Control Engine CI succeeds;
- a fresh behavior-first exact-head review finds no concrete correctness, authority, security or liveness defect;
- reviewed code is merged with exact-head protection;
- a subsequent normal scheduled cycle recovers any pre-existing expired holder and completes acquire/WORK/EVENT/release without `durable success + ERROR`;
- current public and private documentation describes the simplified boundary;
- stale/conflicting runtime code, tests, helpers, stabilization claims and superseded PR surfaces found in scope are removed or closed.
