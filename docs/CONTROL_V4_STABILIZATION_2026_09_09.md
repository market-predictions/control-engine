# CONTROL V4 STABILIZATION — 2026-09-09

```text
document_id=CONTROL_V4_STABILIZATION_2026_09_09
status=CURRENT_STABILIZATION_RECORD
source_of_truth=GITHUB
scope=RUNTIME_READ_AFTER_WRITE_RELIABILITY_ONLY
```

## Objective

Restore deterministic correspondence between a successful durable private queue mutation and the carrier result without reopening Control V4 architecture.

The observed failure was narrow: the GraphQL `updateRefs` mutation successfully advanced `control-runtime-state`, while the immediately following higher-level `/branches/...` readback briefly returned the previous ref. The carrier therefore published `FAIL_CLOSED` even though the durable acquire had landed.

## Fix

The runtime carrier now:

1. preserves the existing exact-old-ref atomic `updateRefs` CAS, including the no-op private `main` authority fence;
2. verifies the changed runtime head through the direct Git ref endpoint rather than the higher-level branch projection;
3. allows only six bounded observations with 0.5-second sleeps between attempts;
4. fails closed when the exact expected ref still cannot be observed inside that bounded window;
5. keeps exact queue-content/blob readback against the new commit mandatory;
6. performs no retry of the semantic runtime command and introduces no durable retry state.

This is a readback reliability change only. It does not change task selection, lease duration, holder semantics, EVENT boundaries, authority, scheduler topology, queue topology, integration authority, command generation or target-effect rules.

## Cleanup

The public private-authority validator no longer retains the unused `V4_40_FROZEN_AUTHORITY_COMMIT` / `load_frozen_v4_40_authority` code path. Post-live Mission evolution is the current validated model; Git history is the record of the former rollback-window implementation.

## Explicitly out of scope

The following are not part of this stabilization change:

- generic Mission-to-queue root-work materialization;
- executable candidate-less BUILD;
- special OVERIGE runtime logic;
- a second queue, scheduler, task type, intake engine or state plane;
- changes to the canonical Runner prompt or `runner_command_generation`;
- enabling integration.

`market-predictions/overige` and its inert Mission registration may remain present, but `[control] task overige: ...` is not considered end-to-end supported until a separate, explicitly approved feature decision closes the root-work intake gap.

## Definition of done

Stabilization is DONE only when all are true:

- focused propagation/readback regression tests pass;
- full exact-head Control Engine CI passes;
- one fresh behavior-first exact-head review finds no concrete executable/authority/liveness material defect;
- the reviewed PR is merged with exact-head protection;
- one subsequent normal scheduled `:30` cycle reconciles the pre-existing expired holder from canonical private state and completes without a false-negative readback or ghost holder;
- current documentation states the bounded direct-ref behavior and does not claim generic OVERIGE/root-work intake is implemented;
- stale conflicting current code/doc statements found in this stabilization scope are removed or corrected.
