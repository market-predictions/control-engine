# Control V4 — Replenishment Discovery

## Purpose

Control must not become idle merely because the current runtime queue has no runnable work while current Mission authority still contains dependency-eligible OPEN gaps. At the same time, the Scheduled Runner must not invent scope or silently create canonical tasks.

This extension closes that gap with **autonomous work discovery without autonomous scope authority**.

## Trigger

Discovery runs only after the existing trusted V4 runtime carrier has produced a successful `NO_WORK` result.

It is an advisory read-only projection. The carrier's queue transition, holder semantics, TICK/EVENT protocol, lease, freshness checks and CAS boundary are unchanged.

`NO_WORK` can also be invocation-local after the Runner has yielded a task. Therefore discovery suppresses a project while its current Mission still has an `ACTIVE` `BUILD`, `REVIEW` or `REPAIR` task. A same-invocation skip cannot masquerade as project exhaustion.

## Source of truth

Discovery reads the same current private sources already used by governed replenishment:

- current `control-plane@main` Mission and repository authority;
- current `control-runtime-state:control/DISPATCH_QUEUE.json`;
- existing dependency and carry-forward semantics.

It reuses the existing `eligible_unmaterialized_gaps_v4()` and `replenishment_approval_payload_v4()` logic. No second planner, queue, database, cursor, retry ledger or state plane exists.

## Public result

Only repositories that independently resolve through the existing **public target boundary** are eligible for public proposal output. A private, missing or otherwise unsupported repository is omitted and can produce only the generic incomplete-observability marker; its repository identity is not projected.

When eligible unmaterialized work exists for a supported public target, the `NO_WORK` result may contain:

```json
{
  "replenishment_proposals": [
    {
      "repository": "owner/repository",
      "authority_key": "<opaque sha256>",
      "eligible_activation_keys": ["<opaque sha256>"]
    }
  ]
}
```

The projection intentionally exposes no Mission id, Mission revision, gap id, acceptance criteria, private authority blobs, queue state or review evidence. The keys are the same opaque authority-bound identifiers already used by project-level replenishment approval.

If discovery cannot safely observe one or more projects, it may add only:

```json
{"replenishment_observability":"INCOMPLETE"}
```

That marker grants no authority and does not convert `NO_WORK` into a runtime error.

## Authority boundary

A replenishment proposal is **not** a task, approval or candidate.

The existing governance sequence remains mandatory:

1. current Mission authority defines the business work;
2. discovery identifies only already-authorized dependency-eligible OPEN gaps;
3. the principal authorizes one exact current project snapshot through the existing `CONTROL_V4_REPLENISH_APPROVAL` handshake;
4. exact public candidates are created outside normal Scheduled runtime;
5. each candidate is separately activated through existing `ACTIVATE_ROOT_CANDIDATE` governance;
6. only then does the canonical queue contain executable candidate-bound work.

A proposal cannot authorize later-eligible gaps, a later Mission revision, new scope, integration, deployment, publication or any other project.

If the business objective requires work that is not present in current Mission authority, discovery must not create it. That still requires the existing governed Mission-revision process and principal authority where applicable.

## Failure isolation

Discovery is deliberately non-critical to runtime transport.

The workflow keeps the original trusted carrier result as a fallback. If the discovery step itself fails, the original carrier result is published unchanged. Therefore advisory discovery cannot strand a holder, suppress `NO_WORK`, mutate the queue or turn a durable runtime result into an error.

A failure isolated to one project does not suppress a valid proposal for another project. It only marks replenishment observability incomplete.

## Reversibility

The feature introduces no persistent state and requires no migration.

Rollback is ordinary Git rollback of:

- `scripts/control_v4_replenishment_discovery.py`;
- its one post-carrier workflow step/result enrichment;
- associated tests/documentation.

After rollback, Control returns to plain carrier `NO_WORK`; existing queue, Mission authority, approvals and activated tasks remain valid and unchanged.

## Explicit non-goals

This feature does not implement:

- arbitrary task invention;
- generic Mission generation;
- candidate-less BUILD execution;
- automatic principal approval;
- automatic candidate creation or PR creation;
- automatic queue activation;
- integration/merge/deploy/send authority;
- another scheduler, Runner, semantic worker or state plane.

The design is intentionally narrow: **discover existing authorized work; never promote it to executable authority without the existing approval and activation gates.**
