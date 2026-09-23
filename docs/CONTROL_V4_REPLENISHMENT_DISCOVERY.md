# Control V4 — NO_WORK replenishment discovery

Status: proposed public current-truth extension for Control V4.

## Purpose

Prevent a governed project from becoming operationally idle merely because the canonical runtime queue has no runnable task while the already-committed current Mission still contains eligible OPEN work.

The extension is deliberately discovery-only. It does **not** give the Scheduled Runner authority to invent scope, materialize tasks, create candidates, merge pull requests, enable integration, or mutate Mission authority.

## Exact behavior

After the existing trusted V4 runtime carrier has successfully returned `NO_WORK`, one read-only workflow step reloads current private `main` authority and the current `control-runtime-state` queue. It then reuses the existing owner-admin replenishment calculation for every governed repository.

If current Mission scope contains one or more currently eligible, unmaterialized OPEN gaps, the public `CONTROL_V4_RUNTIME_RESULT` remains `NO_WORK` and gains `replenishment_proposals`. Each proposal contains only:

- a repository name that has first been confirmed publicly readable;
- an opaque authority key bound to the exact current Mission/authority snapshot;
- the sorted opaque activation keys that are eligible in that snapshot;
- the exact `CONTROL_V4_REPLENISH_APPROVAL` command for that snapshot.

Mission IDs, Mission revisions, gap IDs, acceptance text, queue contents and private blob identities remain private. A private or unavailable target repository is not published; discovery fails closed before emitting the enriched result.

If no eligible OPEN gap exists, the `NO_WORK` result is byte-semantically backward compatible apart from normal JSON serialization: no replenishment field is added.

## Authority boundary

A proposal is evidence of discoverable governed work, **not approval and not a task**.

The existing owner-admin path remains the only materialization path:

1. Control discovers an exact opaque replenishment snapshot after `NO_WORK`.
2. The owner explicitly posts the exact `CONTROL_V4_REPLENISH_APPROVAL` snapshot.
3. `ACTIVATE_ROOT_CANDIDATE` must still reference an activation key contained in that exact approval.
4. Current authority, dependency eligibility, candidate identity, approval digest and private-main/runtime-ref CAS are revalidated before the canonical queue changes.

A later-eligible gap cannot borrow an older approval snapshot. Scope not present in current Mission authority cannot be discovered or activated by this mechanism.

## Failure behavior

Discovery is fail-closed. Unexpected authority/replenishment inconsistencies, invalid V4 private-state validation, or a private/unavailable proposed target repository make the discovery step fail rather than fabricate, broaden, or publish a proposal. Validation failures are caught at the discovery boundary so private validation details are not emitted through an uncaught traceback in the public workflow. The underlying successful carrier result remains separately observable, and no private mutation is performed by discovery.

## Reversibility

This change introduces no schema migration, durable discovery state, new queue, new scheduler, new Runner, feature flag, database or new lifecycle state.

Rollback is therefore ordinary source rollback of:

- `scripts/control_v4_replenishment_snapshot.py`;
- its workflow step in `control-v4-runtime-carrier.yml`;
- the focused tests and this documentation.

Existing queue data, Mission authority, owner approvals and previously materialized tasks require no rewind. The pre-change runtime carrier remains valid because its command/result state machine is unchanged.

## Non-goals

This is not a generic planner, Mission generator, candidate-less BUILD mechanism, auto-approval mechanism, auto-merge mechanism, retry ledger, fairness system or second state plane. New Mission scope still requires the existing governed authority-evolution process.
