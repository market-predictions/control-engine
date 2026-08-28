# Control Minimal Core V1

Canonical governance contract: `market-predictions/control-plane#206`.

## Objective

Restore reliable autonomous progression with the smallest state machine that preserves Control's governance boundaries.

```text
QUEUED task
  -> scheduled ChatGPT role-worker wake
  -> bounded exact-role claim in DISPATCH_QUEUE
  -> semantic worker execution
  -> immutable exact task/run result
  -> atomic terminalization + at most one direct successor
```

A scheduler only wakes a worker. A current queue claim is the only proof that work started.

## One mutable authority

`control/DISPATCH_QUEUE.json` is the **only mutable Minimal Core execution authority**.

Minimal Core does not read or write `control/DISPATCH_RUNS.json`. That file remains legacy/audit history only. Creating a second mutable run projection would duplicate ownership truth and reintroduce the stale-state class this redesign removes.

Run identity needs no separate state plane:

- while executing, the exact `run_id` lives in the task's current `claim`;
- an immutable worker result binds exact `task_id + run_id`;
- after semantic terminalization, the task keeps that exact identity as `terminal_run_id` for replay validation;
- execution failures clear ownership and leave only `last_execution_error` on the same queued task;
- Git history on the authoritative runtime branch is the durable audit trail of queue mutations and attempts.

Thus the active state is:

```text
task + current claim OR terminal_run_id + immutable result + one-step successor authority
```

not queue + runs + intake + handover + completion + retry lineage.

## Worker wake topology

Control reuses the existing recurring ChatGPT A1 and B1 role workers as the single semantic worker-scheduler family. Scheduler state has no governance authority.

A role-worker invocation calls the deterministic Minimal Core actuator for its own role. The actuator reconciles expired/current results, selects the preferred eligible task, persists exactly one bounded claim in the queue, then rereads that queue. Semantic work starts only after the exact claim is `START_PROVEN`.

`.github/workflows/scheduled-worker-a-v2.yml` is deliberately an actuator, not a scheduler. It has no cron, performs no semantic implementation/assurance and cannot create an ownerless scheduled claim.

## Core invariants

1. One canonical queue is active authority.
2. One task has one immutable operation and role.
3. A1/B1 share one bounded claim mechanism with role capacity 1 and repository exclusivity.
4. Current ownership exists only in the task claim.
5. One immutable result belongs to one exact task/run.
6. Terminalization clears the claim, stores `terminal_run_id`, and creates at most one direct successor in the same queue mutation.
7. Infrastructure failure is not semantic state; it requeues the same task.
8. Time expires authority. An expired run cannot terminalize PASS/FAIL/INDETERMINATE or create successor authority.
9. A1 cannot assure; B1 cannot implement, repair, integrate, merge or release.
10. Candidate-bound operations and B1 results use an exact 40-character candidate SHA.
11. `principal_manual_relay_count` must exist and be exact integer `0`.
12. A direct successor ID must be free before the predecessor can be claimed.
13. `PROJECT_INTEGRATION` is terminal for its task purpose and has no successor authority.

## Task lifecycle

Minimal Core uses only:

- `QUEUED`
- `EXECUTING`
- `TERMINAL`

Operation-to-role mapping:

| operation | role |
| --- | --- |
| `IMPLEMENTATION` | A1 / `implementation_operations` |
| `REPAIR` | A1 / `implementation_operations` |
| `PROJECT_INTEGRATION` | A1 / `implementation_operations` |
| `ASSURANCE` | B1 / `governance_release_assurance` |

Semantic outcomes:

- A1: `COMPLETED | BLOCKED`
- B1 assurance: `PASS | FAIL | INDETERMINATE`

Infrastructure diagnostics such as `EXECUTOR_UNAVAILABLE`, `TIMEOUT`, `NETWORK_ERROR`, `LEASE_EXPIRED` and `INVALID_PERSISTED_RESULT` are never semantic outcomes.

## One-step successor authority

A task stores only its **immediate** `successor_by_outcome`; no recursive lifecycle tree is authoritative.

Fail-closed transitions:

- IMPLEMENTATION/REPAIR `COMPLETED` -> ASSURANCE
- IMPLEMENTATION/REPAIR `BLOCKED` -> none
- ASSURANCE `PASS` -> PROJECT_INTEGRATION
- ASSURANCE `FAIL` -> REPAIR
- ASSURANCE `INDETERMINATE` -> none
- PROJECT_INTEGRATION -> none

For IMPLEMENTATION/REPAIR completion, the validated A1 result supplies the exact resulting candidate SHA. The fresh ASSURANCE successor is bound to that SHA. When a successor is materialized, the kernel deterministically gives it only its own immediate transition contract.

This supports repeated:

```text
FAIL -> REPAIR -> new SHA -> ASSURANCE -> FAIL -> REPAIR -> newer SHA -> ASSURANCE
```

without H2/H3/H4 lineage or a prebuilt nested plan.

## Result and expiry ordering

Each role-worker wake performs:

1. validate the canonical queue;
2. expire claims whose lease is no longer current;
3. for claims still current, discover an immutable result by exact `task_id + active run_id`;
4. finalize a valid exact result idempotently, or requeue invalid current-run output as `INVALID_PERSISTED_RESULT`;
5. select the preferred eligible task for the role;
6. reject a claim if its direct successor ID is already occupied;
7. claim with role-capacity/repository-exclusivity checks;
8. authoritative queue reread proves `START_PROVEN`.

A result discovered after lease expiry cannot recover semantic authority. Retrying work is safer than allowing an expired owner to create a verdict.

Exact terminal replay requires the same outcome, result reference, `terminal_run_id`, predecessor/successor identity and—where candidate-bound—the same exact successor candidate SHA.

## Legacy boundary and cutover

Historical intake, handover, claim-completion, retry lineage and `DISPATCH_RUNS.json` remain audit evidence. Minimal Core does not delete them and does not use them as active authority.

Cutover is bounded:

1. independently assure and merge the exact Minimal Core candidate;
2. change the existing legacy assurance profile from `ACTIVE` to explicit `RETIRED`;
3. reread and validate that exact retirement state before any Minimal Core mutation;
4. verify the legacy B1 scheduler idles via its existing non-ACTIVE gate;
5. enable exactly the existing recurring ChatGPT A1 and B1 role-worker tasks;
6. materialize current required work as Minimal Core tasks;
7. prove the live `#204 -> #202 if still needed -> GAP-10` chain without manual lifecycle repair.

The actuator fails closed unless the legacy profile exists and validates exactly as `RETIRED`, including exact integer relay zero. No second lock, queue, run state plane, scheduler family, provider route, B2/B3 or task-specific recovery framework is introduced.

## Production acceptance

Minimal Core is production-proven only when the live chain demonstrates:

- autonomous A1 and B1 wake/claim through the existing role workers;
- START_PROVEN from authoritative queue reread;
- A1 completion creates exactly one exact-candidate assurance successor;
- B1 PASS/FAIL/INDETERMINATE routes exactly as specified;
- a repair can create a new SHA and re-enter assurance repeatedly;
- expiry or invalid output requeues the same task without semantic lineage;
- exact result replay is idempotent;
- successor-ID collision is rejected before semantic work;
- no Minimal Core read/write depends on `DISPATCH_RUNS.json`;
- the next eligible task advances without principal relay;
- the real Control mission chain completes without manual lifecycle repair.
