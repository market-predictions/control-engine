# Public / Private Boundary — Control V4

## Authority

The private repository `market-predictions/control-plane` remains the sole Control Mission/authority and mutable runtime-state plane. The public `market-predictions/control-engine` repository owns deterministic contracts, validation and bounded transport/carrier code. It owns **no semantic runtime authority** and persists no private Control runtime state.

## Runtime writer

The one recurring ChatGPT Control Runner remains the semantic V4 Runner. Normal Scheduled runtime does not depend on direct private-repository access. Private mutation uses the reviewed bounded path:

```text
ChatGPT Scheduled semantic Runner
        ↓ owner-bound typed public TICK/EVENT
control-engine issue #106 transport
        ↓ trusted deterministic carrier
scoped GitHub App capability: control-plane contents:write only
        ↓ exact old-ref CAS + mandatory readback
control-plane@control-runtime-state:control/DISPATCH_QUEUE.json
```

The carrier is not a second semantic worker. It accepts no arbitrary queue document or patch. It fresh-reads current private runtime authority, Runner config/prompt, V4 Mission/repository authority and the one canonical queue; applies only reviewed typed transitions; and writes only the canonical queue file.

Every private queue mutation remains fenced by the exact observed private `main`, runtime branch head and queue blob. The carrier submits one atomic non-force GraphQL `updateRefs` mutation containing the no-op `main` authority fence and the runtime-ref advance, followed by mandatory authority/runtime/queue readback. Concurrent movement fails closed.

Public issue comments/results are transport and audit evidence only. They never become queue, Mission, holder, lease, retry, status or recovery state. Public WORK capsules expose only public target/candidate facts plus an opaque task token; private task/Mission/acceptance/authority/lock/queue details remain private.

## Pre-acquisition Runner generation fence

Before posting any acquisition-capable TICK, the canonical Runner performs one read-only scheduler readback and requires the same reviewed object `6a9a7e0b18b08191876c134d83cfbba2`, title `Control V4 Runner`, enabled state, exact hourly `:30` Europe/Amsterdam schedule, the current prompt identity/generation, and no second enabled Control V4 Runner. Failure means zero public command writes.

The current command generation is `965d03fc71359d0e`. Immediate predecessor generation `9510d79361e01a74` is historical only. A generation is not reusable: any prompt change that can alter command authority, acquisition, correlation, holder-closeout or target-effect behavior requires a new previously unused generation before adoption.

The public workflow accepts only the current generation-bound run id before it creates private capability:

```text
v4:6a9a7e0b18b08191876c134d83cfbba2:965d03fc71359d0e:<32 lowercase hex>
```

The carrier then independently fresh-validates the exact private runtime-authority → Runner-config → prompt-blob chain. Scheduler readback is an operational binding fence, never Control runtime authority.

## Stateless TICK transport and liveness

Every normal invocation starts with one fresh TICK and current canonical private state:

```text
no live lock      -> select/acquire -> WORK or NO_WORK
expired lock      -> canonical expired-lock recovery -> select/acquire -> WORK or NO_WORK
live foreign lock -> BUSY
```

TICK authority remains protected by the existing three stateless freshness fences against the immutable GitHub comment `created_at`: workflow admission before private capability, transition-time recheck before `_tick()`, and durable-CAS recheck immediately before `updateRefs`. The closed age interval remains 0..120 seconds. Same-run supersession remains bounded to canonical issue #106 commands and prevents an earlier TICK becoming current after a later same-run command; it derives no holder or queue state from transport history.

Every command has its immutable GitHub comment id. Every trusted result echoes that exact id as `command_comment_id`; the Runner accepts only the result correlated to the exact command it just posted. The just-merged parser behavior remains canonical: both one-space and one-newline TICK/EVENT framing are parsed by the single `parse_public_command` implementation.

After any acquisition-capable TICK, the invocation retains live-TICK responsibility until either a trusted exact-command result arrives, or the immutable TICK is older than 120 seconds, the uniquely correlated `Control V4 runtime command <command_comment_id>` workflow run is observed terminal `completed`, and one final exact-command result read after that terminal observation still finds no result. Age alone is never sufficient. No replacement TICK is posted merely because a run is slow.

This rule persists no timer, cursor, retry record, scheduler state, carrier-run ledger, cancellation state or runtime state. The fixed private 5400-second non-renewable lease plus carrier expired-lock recovery remains the only cross-invocation holder/crash-recovery mechanism.

## Holder closeout after WORK

A trusted `WORK` result creates an invocation-local **holder-closeout obligation**. The semantic Runner must not normally end while that exact acquired holder is still live merely because reasoning, target facts, candidate drift, time pressure, or a safe target effect cannot proceed.

After WORK, the Runner continues the exact current action and consumes correlated semantic EVENT results until the holder is released or the lifecycle transitions. An EVENT result that returns `WORK` is explicitly **not** closeout: the holder remains live and same-holder processing continues.

For REPAIR candidate drift, the Runner first performs bounded read-only target reconciliation. If `live_candidate` is an already-published repair candidate on the same governed PR, head branch and base context and is safely within the task acceptance scope, the Runner performs no duplicate target write. It sends exactly one existing `CANDIDATE_READY` EVENT populated from the exact live-candidate fields. The carrier remains authoritative for live PR verification and private candidate transition, and the Runner consumes the correlated EVENT result and continues when it returns WORK.

If REPAIR drift is ambiguous, outside scope, on the wrong PR/head/base, or otherwise not safely reconcilable, the Runner sends exactly one existing `YIELD` EVENT while the holder remains valid and consumes the correlated `YIELDED` result. More generally, before any normal exit after WORK, if the exact holder is still live and no safe semantic progress EVENT is possible, the Runner sends YIELD and consumes its exact correlated result.

A missing or ambiguous EVENT result remains fail-closed transport ambiguity. The Runner never blind-replays that EVENT and never fabricates holder-closeout evidence. The closeout obligation is invocation-local and is derived only from the trusted WORK and its exact correlated EVENT results; private holder state is never reconstructed from public history.

This repair reuses the existing `CANDIDATE_READY` and `YIELD` transitions. It adds no scheduler, queue, state plane, recovery ledger, cancellation protocol, lease renewal or carrier semantic authority.

## Canonical EVENT wire contract

`control_engine/v4_runtime_protocol.py` remains the single semantic protocol owner. Every semantic EVENT copies the correlated WORK identity exactly:

- `run_id`;
- `task_token`;
- `repository`;
- `action`;
- `candidate` iff WORK contained one;
- `event` plus only that event's explicitly allowed fields.

`command_comment_id`, `live_candidate`, protocol/result fields and private `holder_*` data are not copied into EVENT payloads. The carrier revalidates current private authority, current exact holder, unexpired lease and candidate/base identity before any EVENT-driven queue mutation.

After a correlated holder-releasing `YIELD` or `REVIEW_UNAVAILABLE`, the token may be added only to the invocation-local yielded-token set and a new same-run acquisition TICK may query unrelated eligible work. Yielded tokens never cross invocation boundaries and are not durable state.

## Consequential target effects

Transport success alone never authorizes a target mutation. Existing target-effect fences remain unchanged: fresh holder acquisition in the current invocation, a second same-run TICK immediately before the effect, exact holder/candidate/base identity, acquisition TICK age ≤660 seconds, revalidation WORK age ≤15 seconds at effect start, target effect plus mandatory readback bounded to ≤300 seconds, and no lease renewal. If a valid holder cannot safely proceed, the closeout rule requires YIELD rather than silent abandonment.

Lost, timed-out or ambiguous target effects remain fact-first and are never blindly retried.

## Maintenance-fenced prompt generation changes

Normal runtime trusts one current prompt hash and one current generation. A prompt-generation change across public trust code and private authority is adopted only through the existing outside-Runner maintenance fence and independent review. Dual-current prompt trust is not a steady-state mechanism; Git history carries predecessor identity.

## Scope and retained boundaries

The V1 carrier remains activation-bounded to `integration_enabled=false` and publicly readable target repositories. It does not merge, deploy or converge. V3.1 semantic runtime writers remain retired. The one mutable private state file remains `control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`; Git history remains mutation audit history.

`ENGINE_MANIFEST.json` is component-local and `semantic_runtime_authority=false` means the public engine does not own Control semantics. Current global status must be reconstructed from current private V4 authority and the canonical private queue, with bounded target evidence as needed.

Same-Runner BUILD/REVIEW/REPAIR remains semantic execution; external review evidence is used only when Mission policy requires it. Provider/quota/transport unavailability cannot manufacture PASS. Candidate/head/base drift remains deterministic GitHub evidence.

Repository integration never implies production deployment, delivery, client-data admission, broker/portfolio mutation, paid-provider use, destructive production migration, or final legal/compliance/certification authority. Those remain separately governed in private Mission/repository/project authority.
