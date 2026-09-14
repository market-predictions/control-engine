# Public / Private Boundary — Control V4

```text
document_id=PUBLIC_PRIVATE_BOUNDARY_V4
status=CURRENT
source_of_truth=GITHUB
```

## Authority

Private `market-predictions/control-plane` is the sole Mission, runtime-authority and mutable runtime-state plane.

Public `market-predictions/control-engine` owns deterministic contracts, validation and bounded transport/carrier code. It owns no semantic runtime authority and persists no private Control runtime state. A component-local manifest or public carrier result must never be promoted into global Control state and is never a source for current **global Control runtime status**; global status is reconstructed from current private authority/queue truth plus bounded target evidence when needed. A public component stating that it has no semantic runtime authority does **not** mean that the canonical Control V4 Runner is inactive.

Canonical mutable state is exactly:

`market-predictions/control-plane@control-runtime-state:control/DISPATCH_QUEUE.json`

Git history is the mutation audit trail. There is no second queue, database, retry ledger or recovery state plane.

## One Runner, bounded transport

The one recurring ChatGPT `Control V4 Runner` is the semantic executor. It emits owner-bound typed TICK/EVENT commands through public issue #106. Public comments are transport/audit evidence only; they never become queue, Mission, holder, lease, status or runtime state.

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

## Owner-approved bounded administration

A principal approval in the canonical dashboard handshake may authorize one exact action without enabling standing integration authority. The existing public V4 administration gate accepts typed owner-admin commands on issue #106:

`CONTROL_V4_OWNER_ADMIN {...}`

This is **outside normal Runner runtime** and supports only two present requirements:

1. `FINALIZE_INTEGRATED`: after the principal approved one exact merge and the target PR is already merged, reconcile the matching exact `READY/PASS` queue task to `DONE`;
2. `ACTIVATE_ROOT_CANDIDATE`: after the principal approved a project-level replenishment cycle, bind one already-existing public PR candidate to one exact gap in the approved eligible set, require that gap to remain currently eligible, and enter `ACTIVE/REVIEW`.

### Project-level replenishment authority

The human approval is intentionally project-scoped, not task-by-task. One approval such as `Replenish Solid Privacy from its current Mission` authorizes Control to process **all gaps that are already eligible in that project's one fresh replenishment snapshot**. It does not authorize future gaps that become eligible later, a Mission revision, new scope, integration, deployment, publication or any unrelated project.

Immediately after that owner decision, Control freezes the approved eligible set as one owner-authored audit comment on canonical issue #106:

`CONTROL_V4_REPLENISH_APPROVAL {...}`

That audit comment contains only:

- the public repository name;
- one opaque `authority_key` bound to the exact current private Mission id/revision/repository plus Mission and repository-authority blob identities;
- the sorted unique set of opaque `eligible_activation_keys` for exactly the gaps eligible in that approved snapshot.

It contains no private Mission id, revision, gap id, acceptance criteria, task id, queue content or private Git ref. The comment itself is **not** treated as immutable state. Instead its exact UTF-8 body is SHA-256 hashed when the snapshot is created. Every activation command carries that exact `approval_body_sha256` together with the approval-comment id. The gate accepts the evidence only when the comment is still the original owner-authored comment on canonical issue #106, `updated_at` still equals `created_at`, and the current body hashes to the exact digest carried by the activation command.

Control creates each bounded candidate separately and activates each candidate separately. Every activation command references the exact approval-comment id, exact approval-body digest, candidate's opaque activation key and exact public target identity. The private gate requires all of the following:

- the referenced approval comment is on canonical issue #106 and is owner-authored;
- the comment has never been edited when consumed;
- its exact body SHA-256 equals the digest frozen in the activation command;
- its repository equals the activation repository;
- its opaque authority key still matches exact current Mission/repository authority;
- the requested activation key is a member of the digest-bound owner-approved key set;
- that same key still resolves to exactly one **currently** eligible unmaterialized OPEN gap;
- the candidate remains exact and valid.

After preparing the private queue commit and revalidating the exact public target, the gate re-reads the same approval comment and rechecks the same digest immediately before the atomic private CAS. Editing the comment cannot expand an already-issued activation because the activation command is permanently bound to the original digest; editing it also causes subsequent activations from that cycle to fail closed because `updated_at != created_at` and the body digest no longer matches. No approval database, mutable approval record or second state plane is introduced.

This two-sided check closes both directions of drift: work that becomes eligible only **after** approval is absent from the digest-bound key set and cannot borrow older authority; work from the approved set that becomes stale/ineligible before activation also fails current eligibility.

The activation key itself is derived from exact private Mission id/revision/gap id plus the exact current Mission/repository authority fingerprint. It remains opaque on the public surface and is never stored in the queue.

A gap is currently activation-eligible only when private authority proves all of the following:

- the exact current Mission and repository authority validate;
- the gap is `OPEN`;
- no current queue task already exists for the same `(mission_id, mission_revision, gap_id)`;
- every dependency is canonically satisfied either by a current-revision `DONE` task with valid review evidence or by valid exact `DONE_CARRY_FORWARD` evidence for a RETIRED dependency;
- the candidate PR is still open, unmerged, mergeable, exact-head bound and based on the exact current expected base SHA.

The resulting task is materialized directly as ordinary `ACTIVE/REVIEW` with the exact candidate. Candidate-less `BUILD` is not introduced.

Both owner-admin operations require no current execution lock, current private Mission/repository authority, an exact current queue blob and exact public target identity. The resulting queue is validated against current private authority before mutation. The write uses the **same atomic authority fence** as normal runtime:

```text
private main:           expected SHA -> same SHA
control-runtime-state: expected SHA -> new queue commit
```

No REST ref write, force update, second queue, approval database, scheduler, service or standing integration switch is introduced. `integration_enabled=false` remains unchanged.

This bounded path is deliberately **not** generic autonomous Mission replenishment by the Scheduled Runner. It cannot create candidate-less BUILD work, infer new Mission scope, merge a target PR, send a report, deploy, or grant production/business-final-decision authority.

## Reversibility

This change does not modify the Scheduled Runner command/acquisition/effect contract, the queue schema, scheduler binding or global integration authority. Therefore it requires no Runner-generation rotation.

Rollback is a normal Git revert/adoption of the owner-admin/dashboard-governance change. Already activated tasks remain ordinary current-schema `ACTIVE/REVIEW`, `READY` or `DONE` tasks understood by the predecessor Runner; no queue rewind or compatibility state plane is required. Pre-activation candidate PRs can simply remain unmerged or be closed. Historical approval audit comments remain inert audit history and grant no authority once the reverted gate no longer accepts them. Git history is the rollback record.

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
- automatic/generic Mission-to-queue root-work materialization by normal Runner runtime;
- candidate-less BUILD execution;
- task-by-task principal approval for one project replenishment snapshot;
- activation of later-eligible work from an older replenishment approval;
- special `OVERIGE` runtime semantics;
- standing integration authority.

Retired mechanisms remain only in Git history, not as competing current code or normative documentation.

## Current product boundary

A governed project may request replenishment only from already-committed current Mission scope. Project-level approval does not create future standing authority: when later dependencies complete and additional gaps become eligible, a later dashboard projection must surface a new replenishment need and produce a new digest-bound approval snapshot.

`market-predictions/overige` may be registered as an inert governed Mission/repository. `[control] task overige: ...` is not end-to-end executable unless current Mission authority contains an eligible gap and a bounded exact candidate can be created under an owner-approved project replenishment cycle. The bounded owner-admin path is not a generic project planner and never invents Mission scope.
