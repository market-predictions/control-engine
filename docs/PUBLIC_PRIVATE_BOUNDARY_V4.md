# Public / Private Boundary — Control V4

## Authority

Private `market-predictions/control-plane` remains the sole Control Mission/authority and mutable runtime-state plane.

Public `market-predictions/control-engine` owns deterministic contracts, validation and the bounded runtime carrier. It owns **no semantic runtime authority** and persists no private Control runtime state.

The canonical mutable runtime truth is exactly:

`market-predictions/control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`

including the one global execution lock. Git history is the mutation audit trail.

## Runtime path

The one recurring ChatGPT Control Runner remains the semantic V4 Runner. A Scheduled wake is only a wake-up; it is never ownership or runtime state.

Normal runtime mutation uses:

```text
ChatGPT Scheduled Runner
        ↓ fresh typed TICK / exact typed EVENT
control-engine issue #106
        ↓ deterministic public carrier
scoped GitHub App capability: control-plane contents:write only
        ↓ exact current private authority + queue + lock
non-force exact-old-ref CAS + mandatory readback
        ↓
control-plane@control-runtime-state:control/DISPATCH_QUEUE.json
```

The carrier is not a second semantic worker. It accepts no arbitrary queue payload or patch. It fresh-reads current private runtime authority, exact Runner config/prompt, current Mission/repository authority and the one canonical queue; validates them with trusted public V4 contracts; applies only reviewed typed transitions; and writes only the canonical queue file.

Every private queue mutation is fenced by exact observed private `main`, runtime branch head and queue blob. A successful mutation creates a descendant runtime commit and atomically advances the runtime ref while no-op fencing the exact observed private `main`. Mandatory authority/runtime/queue readback follows. Stale writers fail closed rather than overwrite newer state.

## Stateless current-state handshake

Public issue #106 is **transport/audit evidence only**. It is not a queue, holder ledger, retry store, recovery state machine, cursor or liveness database.

Every Scheduled invocation starts by posting one fresh unique TICK. The carrier decides from current private truth:

```text
no current lock
  -> select eligible work
  -> acquire using fresh TICK run_id
  -> WORK + acquired_now=true

objectively expired lock
  -> recover expired private lock
  -> select/acquire eligible work
  -> WORK + acquired_now=true

current live lock
  -> create no competing holder
  -> return current holder WORK directly
  -> WORK + acquired_now=false

no eligible work
  -> NO_WORK
```

The Runner does not scan historical issue comments to reconstruct unresolved TICKs, EVENTS, retries, holder age or recovery state before entering the carrier.

The private non-renewable **5400-second execution lease remains** the durable crash/holder timeout primitive. Public 120-second TICK replay, public 5400-second unresolved-EVENT retirement, spent transport identities, earliest-TICK reconstruction and BUSY/resume roundtrips are obsolete and are not current runtime semantics.

If a command result is missing or ambiguous, the Runner stops the current invocation without replaying the old command. The next Scheduled invocation sends a fresh TICK; the carrier then reconciles actual current private state.

## Exact command/result correlation

The workflow passes the raw command body and the immutable triggering GitHub issue-comment id to the canonical carrier.

Every public result includes:

```text
command_comment_id=<exact triggering issue-comment id>
```

The Runner retains the id/body/created_at returned when it posts its command, reads only comments created at or after that timestamp, and accepts exactly one trusted `github-actions[bot]` result with the matching `command_comment_id`.

This is invocation-local transport correlation only. `command_comment_id` is not persisted in the private queue and does not become runtime state.

## Public-safe WORK metadata

A WORK capsule exposes only public-safe execution identity:

```text
run_id
task_token
repository
action
candidate       # only when present
live_candidate  # only where already required for public target drift
acquired_now
```

`acquired_now=true` means the exact TICK that produced the result created the current private holder. `acquired_now=false` means a live holder already existed and was returned directly.

No private task id, Mission/gap/acceptance payload, authority blob identity, review record, blocker, queue, lock timestamp or other private state is mirrored publicly.

A resumed holder (`acquired_now=false`) may perform read-only reasoning and holder-fenced carrier EVENTs but may not initiate a target-repository or external-review write. If it needs such an effect it must YIELD the existing holder and later obtain a fresh acquisition.

## Canonical EVENT wire contract

`control_engine/v4_runtime_protocol.py` is the single protocol owner for public TICK/EVENT wire semantics. The workflow transports raw command bodies unchanged and contains no compatibility parser or alternate EVENT normalizer.

Every EVENT echoes one correlated trusted WORK identity exactly:

- `run_id`;
- `task_token`;
- `repository`;
- `action`;
- `candidate` iff WORK contained candidate;
- `event` plus only that event type's explicitly allowed fields.

`acquired_now`, `command_comment_id`, `protocol`, `result`, `live_candidate` and private `holder_*` fields are result/internal metadata and must never be copied into an EVENT.

The parser rejects unknown/malformed fields. Holder binding then requires repository, action and complete candidate identity to match the current task resolved by the opaque token; current lock ownership, lease and authority are revalidated immediately before private mutation. Drift fails closed.

## Consequential target effects

A non-transport write to a target repository or external-review surface requires a fresh holder acquired in the current invocation (`acquired_now=true`). A resumed holder cannot write externally.

Before each target effect the Runner must additionally preserve the initial acquisition command identity, remain within the 660-second acquisition freshness window, obtain an immediate same-holder revalidation TICK, start the effect within 15 seconds of that trusted revalidation result, re-read minimum current target identity, and bound effect plus mandatory readback to 300 seconds. Revalidation never renews the private lease or acquisition freshness.

Lost/ambiguous target effects are reconciled fact-first and never blindly retried.

## Carrier scope

Carrier V1 remains deliberately bounded to `integration_enabled=false` and publicly readable target repositories. It restores BUILD/REVIEW/REPAIR/wait liveness but has no merge/deploy/converge authority. Any integration-capable extension requires separate concrete need, implementation and review.

The retired V3.1 GitHub Actions semantic writer is not reintroduced.

## Review/fairness semantics

Current target GitHub evidence is review fact source. Same-Runner review is not independent assurance.

External provider/quota/transport unavailability records retryable `INDETERMINATE` and releases ownership; it can never manufacture PASS. Across later acquisitions such work is considered only after ordinary productive ACTIVE and eligible QUEUED work and remains selectable when nothing higher-value exists. No cooldown database, retry queue, retry counter or second state plane exists.

Candidate/head/base drift is deterministic target evidence. The carrier re-reads live public candidate identity before review-state EVENTs; exact drift wins and returns the same stable task to REPAIR.

## Status and observability

`ENGINE_MANIFEST.json` is component-local. `semantic_runtime_authority=false` means the public engine does not own Control semantics; it does not imply the V4 Runner is inactive.

Current global Control status is reconstructed from private V4 authority and canonical runtime queue, with bounded current target evidence as required. Public issue comments and Actions runs corroborate transport but never override private truth.

## Retained V3.1 support

V3.1 kernel/migration/validation code may remain only while it has a concrete pre-V4-80 rollback/migration validation dependency. It is passive rollback-only support, not current runtime authority. When that dependency closes, V3.1-only code/docs/tests are deleted rather than carried indefinitely.

## Absolute boundary

Repository integration never implies production deployment, delivery, real-client-data admission, broker/portfolio mutation, payment, paid-provider use, destructive production migration or final legal/compliance/certification authority. Those remain separately governed.
