# Public / Private Boundary — Control V4

## Authority

Private `market-predictions/control-plane` remains the sole Control Mission/authority and mutable runtime-state plane.

Public `market-predictions/control-engine` owns deterministic contracts, validation and bounded transport/carrier code. It owns **no semantic runtime authority** and persists no private Control runtime state.

## Runtime writer

The one recurring ChatGPT Control Runner remains the semantic V4 Runner. Normal private runtime mutation uses only:

```text
ChatGPT Scheduled semantic Runner
        ↓ owner-bound typed public TICK/EVENT
control-engine issue #106 transport
        ↓ trusted deterministic carrier
scoped GitHub App capability: control-plane contents:write only
        ↓ exact old-ref CAS + mandatory readback
control-plane@control-runtime-state:control/DISPATCH_QUEUE.json
```

The carrier is not a second semantic worker. It accepts no arbitrary queue document/patch. It fresh-reads current private V4 authority, exact Runner config/prompt, Mission/repository authority and canonical queue, applies only reviewed typed transitions, and writes only the canonical queue.

Every queue mutation requires exact observed private `main`, runtime branch head and queue blob to remain current. Writes use non-force CAS plus mandatory authority/runtime/queue readback. Stale writers fail closed rather than overwriting newer ownership.

## Stateless transport and recovery boundary

Issue #106 is **transport and audit evidence only**. It is never queue, lease, retry, holder or recovery state.

Every Scheduled invocation enters through one new unique fresh `CONTROL_V4_RUNTIME_TICK`. The carrier reads current canonical private state and decides:

```text
no lock      -> select/acquire -> WORK or NO_WORK
expired lock -> deterministic expired-lock recovery -> select/acquire -> WORK or NO_WORK
live foreign lock -> BUSY
```

`BUSY`, NO_WORK or a missing/ambiguous/error result ends only that invocation. A later normal Scheduled wake again sends a fresh TICK. The private queue's fixed non-renewable 5400-second lease and carrier-side expired-lock recovery are the sole cross-invocation holder/crash-recovery mechanism.

Current V4 therefore has **no**:

- startup scan of issue history to decide recovery;
- unresolved-TICK or unresolved-EVENT runtime state;
- same-command replay loop;
- public 120-second replay clock;
- public 5400-second EVENT-retirement/spent-identity clock;
- transport cursor/retry ledger;
- cross-invocation holder reconstruction from public comments.

A lost transport response is not evidence about whether a private transition landed. The next invocation asks current canonical state again rather than replaying history.

## Canonical public wire contract

`control_engine/v4_runtime_protocol.py` is the single owner of typed `CONTROL_V4_RUNTIME_TICK` and `CONTROL_V4_RUNTIME_EVENT`. The workflow passes raw issue-comment bodies unchanged and contains no compatibility parser or alternate EVENT normalizer.

Every semantic EVENT echoes the trusted WORK identity exactly:

- `run_id`;
- `task_token`;
- `repository`;
- `action`;
- `candidate` exactly when WORK contains it;
- `event` plus only explicitly allowed event-specific fields.

Unknown fields and malformed identity fail closed. Holder binding revalidates repository, action and complete candidate identity against current private state before mutation. The Runner never transmits private task IDs, Mission/gap/acceptance/authority data, queue state, lock state or an alternate public `holder_*` envelope.

Public responses are deliberately reduced to public target/candidate facts plus opaque task correlation. Private Mission/task/acceptance/authority/review/blocker/lock/queue content is never mirrored publicly.

## Activation-bounded capability

Carrier V1 requires `integration_enabled=false`, supports public target repositories only, and contains no INTEGRATE/CONVERGE authority. Private/unreadable targets fail closed instead of adding another credential path. A later integration-capable extension requires separate concrete need and review.

The V3.1 semantic GitHub Actions writer remains retired. No V3.1 claim/record/release runtime path is reintroduced.

## Review and fairness

Same-Runner review is engineering review, not independent assurance. External review is candidate evidence only when Mission policy requires it.

Provider/quota/transport unavailability records `INDETERMINATE` and releases/yields the holder. Across later acquisitions, such retryable external-review work is considered after ordinary productive ACTIVE and eligible QUEUED work; it remains selectable when nothing higher-value exists. No cooldown database, retry counter, retry queue or cursor is introduced.

Candidate/base drift is deterministic GitHub evidence. The carrier re-reads live public PR identity before review-state mutations; drift wins and returns the same stable task to REPAIR rather than creating duplicate review work.

## Consequential target effects

Transport success does not authorize a target mutation. Target effects additionally require fresh acquisition in the current Scheduled invocation, exact same-run pre-effect revalidation, bounded freshness/time windows, current target identity and mandatory effect readback. The private lease is never renewed by revalidation.

Lost/ambiguous side effects are reconciled fact-first and never blindly retried.

## Status scope

`ENGINE_MANIFEST.json` is a **component-local manifest** and is never a source for current **global Control runtime status**. `semantic_runtime_authority=false` means this public component does not own Control semantics; it does **not** mean that the canonical Control V4 Runner is inactive.

Current global status is reconstructed from current private authority + canonical runtime queue + only required live target facts. Public comments/actions may corroborate transport but never override private state.

## Retained V3.1 code

V3.1 kernel/migration/validation code may remain only while a concrete pre-V4-80 rollback/migration/historical-validation dependency exists. It is passive rollback support, not current authority, and should be deleted when that dependency closes.

## Private state

Canonical mutable state remains exactly:

`market-predictions/control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`

Git history is mutation audit history. No public mirror, retry store, queue, status cache or recovery database is added.

## Consequential authority

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed.
