# Control V4 — holder revalidation liveness fix — 2026-09-23

Status: candidate stabilization fix.

## Observed production failure

On 2026-09-23 the canonical Runner acquired `WEEU-GOLDEN-PATH-20` in `REPAIR` under one valid run/lease. The mandatory second same-run TICK, used only for immediate pre-effect holder revalidation, was admitted and loaded private state successfully but returned public-safe `FAIL_CLOSED`. The target PR remained open and unchanged on the same head/base.

The runtime carrier implementation performed a public target-repository/PR read while servicing an already-held same-run `REPAIR` TICK. That made holder revalidation depend on a second target-network read even though the canonical Runner contract requires the fresh target identity read *after* the trusted second WORK and immediately before the target effect.

## Root-cause correction

For an unexpired execution lock owned by the same `run_id`, `_tick()` now validates the canonical private queue/holder as before and returns `safe_work_capsule()` directly from that private truth. It performs no target-repository or target-PR network read in that same-holder branch.

This does not weaken target correctness:

- initial acquisition still validates target repository/candidate state before acquiring work;
- EVENT transitions that semantically depend on live candidate state still perform their existing target validation;
- the Runner still performs the mandatory fresh public target identity read after the trusted second WORK and immediately before every target effect;
- lease, command freshness, same-run supersession, authority binding, exact candidate/base EVENT binding and CAS fences remain unchanged.

The second same-run TICK is therefore again what the canonical contract says it is: holder revalidation only, not an additional target-network gate.

## Verification

Focused regression coverage proves that a same-run locked `REPAIR` holder returns the canonical WORK capsule even when all target-read helpers are forced to fail if called. A different run still receives `BUSY` without target access. Full Control Engine regression, surface and smoke CI remain required before adoption.

## Reversibility

No schema, state, queue, scheduler, Runner generation, capability, lifecycle or authority change is introduced. Reverting the carrier commit restores the previous behavior; no private queue or Mission migration is required.

## Non-goals

This fix does not add retries, authenticated cross-repository target access, a transport fallback, a new recovery mechanism, a lease renewal path or relaxed fail-closed semantics. It only removes one redundant target-network dependency from same-holder revalidation.