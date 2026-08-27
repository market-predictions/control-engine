# Control Minimal Core V1

Canonical governance contract: `market-predictions/control-plane#206`.

## Objective

Restore reliable autonomous progression by removing accidental orchestration complexity while preserving Control's governance invariants.

The active execution model is deliberately small:

```text
queued task
  -> bounded exact-role claim
  -> worker execution
  -> immutable task+run result
  -> atomic terminalization + at most one predefined successor
```

A scheduler only wakes a worker. A current canonical claim is the only proof that work started.

## First-principles rules

1. **One queue is active authority.** `control/DISPATCH_QUEUE.json` remains the only executable state plane.
2. **One task, one purpose.** `operation` and `role` are immutable for the lifetime of a task.
3. **One claim mechanism.** A1/B1 use the same lifecycle kernel with role capacity 1 and repository exclusivity.
4. **One result mechanism.** One immutable result belongs to one task and one run.
5. **One terminalization.** Result finalization clears ownership and creates at most one predefined successor in the same queue mutation.
6. **Execution failure is not semantic state.** Infrastructure or invalid executor output requeues the same task with `last_execution_error`; it does not create H2/H3/H4-style lineage.
7. **Persisted result wins over expired lease only when valid for the exact active task/run.** Invalid current-run output is an execution failure, never a semantic verdict.
8. **Independent assurance remains mandatory.** A1 cannot assure. B1 outcomes are only `PASS`, `FAIL`, or `INDETERMINATE`.
9. **Exact candidate binding remains mandatory.** An assurance task and B1 result require the same concrete 40-character candidate SHA.
10. `principal_manual_relay_count` remains zero.

## Minimal task state

A Minimal Core task adds `lifecycle_model: CONTROL_MINIMAL_CORE_V1` and uses only three execution statuses:

- `QUEUED`
- `EXECUTING`
- `TERMINAL`

The operation determines the worker role:

| operation | role |
| --- | --- |
| `IMPLEMENTATION` | `implementation_operations` / A1 |
| `REPAIR` | `implementation_operations` / A1 |
| `PROJECT_INTEGRATION` | `implementation_operations` / A1 |
| `ASSURANCE` | `governance_release_assurance` / B1 |

A task stores its predefined `successor_by_outcome`. The lifecycle kernel copies at most one matching template after a valid terminal result. This makes successor creation deterministic rather than a planner/reconciler side effect.

Authority routing is fail-closed:

- `IMPLEMENTATION` / `REPAIR` `COMPLETED` may create only an exact-candidate `ASSURANCE` successor;
- `IMPLEMENTATION` / `REPAIR` `BLOCKED` creates no successor authority;
- `ASSURANCE` `PASS` may create only `PROJECT_INTEGRATION`;
- `ASSURANCE` `FAIL` may create only `REPAIR`;
- `ASSURANCE` `INDETERMINATE` creates no successor authority.

## Semantic versus execution outcomes

Semantic task outcomes are operation-specific:

- A1 implementation/repair/integration: `COMPLETED` or `BLOCKED`.
- B1 assurance: `PASS`, `FAIL`, or `INDETERMINATE`.

Infrastructure conditions such as `EXECUTOR_UNAVAILABLE`, `NETWORK_ERROR`, `TIMEOUT`, `LEASE_EXPIRED`, and `INVALID_PERSISTED_RESULT` are run diagnostics only. They return the same task to `QUEUED` and cannot create integration authority or a new assurance lineage.

## Recovery

Every lifecycle wake performs the same ordering:

1. discover persisted results for currently executing Minimal Core tasks by exact task + active run;
2. finalize a valid exact task/run result idempotently;
3. requeue invalid current-run result output as execution failure;
4. release remaining expired claims as `LEASE_EXPIRED`;
5. select the preferred eligible task for the requested role;
6. claim only after role-capacity and repository-exclusivity checks.

There is no separate terminal-completion authority in the Minimal Core path. Replaying an already-applied exact result returns the authoritative terminal state and never creates a duplicate successor.

## Legacy artifacts

Existing project-intake, handover, claim-completion, H/R retry, and historic queue records remain immutable audit evidence. They are not deleted.

After cutover they are not allowed to materialize, supersede, retry, or otherwise mutate Minimal Core tasks. New active execution must not depend on intake-revision or handover reconciliation.

## Cutover

The migration is bounded and deliberately not a long-running dual control plane:

1. implement and independently assure the Minimal Core kernel and bridge;
2. merge the exact independently assured candidate;
3. set the existing legacy assurance execution profile to an existing non-`ACTIVE` state and reread it before any Minimal Core task is materialized;
4. verify the existing legacy `canonical-b1` scheduler now idles through its existing profile gate;
5. stop creating new local H/R recovery lineages;
6. materialize current work as Minimal Core tasks while preserving exact repository/PR/SHA/contracts;
7. prove the real chain `#204 -> #202 -> GAP-10` without manual lifecycle repair;
8. keep old active recovery machinery retired while retaining its history.

The Minimal Core bridge itself refuses to reconcile, claim, or record Minimal Core lifecycle state while Minimal Core tasks exist and the legacy B1 profile is still `ACTIVE`. This makes the cutover ordering fail-closed without adding a second lock, queue, scheduler or migration service.

No second queue, scheduler family, provider marketplace, B2/B3, TTL/GC subsystem, or workflow-per-task recovery is permitted.

## Acceptance proof

Minimal Core is production-proven only when all are true:

- A1 autonomously claims an eligible A task;
- A1 `COMPLETED` creates exactly one predefined assurance successor when a successor is required and leaves no ghost claim;
- A1 cannot create integration authority directly from implementation or repair;
- B1 independently claims that assurance with a current lease;
- infrastructure failure or invalid executor output requeues the same task without new semantic lineage;
- B1 `PASS` creates exactly one predefined integration successor when configured;
- B1 `FAIL` creates exactly one predefined repair successor when configured;
- B1 `INDETERMINATE` creates no integration authority;
- exact result replay is idempotent;
- the next scheduled invocation selects the next task without principal relay;
- any current task can be explained from one queue record plus at most one result file;
- the live `#204 -> #202 -> GAP-10` chain completes without manual lifecycle repair.
