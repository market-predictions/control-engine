# Control V4 — NO_WORK governed replenishment

Status: public current-truth extension for Control V4.

## Purpose

Prevent a governed project from becoming operationally idle merely because the canonical runtime queue has no runnable task while the already-committed current Mission still contains eligible OPEN work.

Current Mission scope is already semantic authority. Therefore a fresh successful `NO_WORK` may materialize an **already-authorized** gap without another principal approval, but only when an exact executable public candidate already exists and is unambiguous. The mechanism may never invent Mission scope, create a candidate, merge a pull request, enable integration or grant production authority.

## Exact behavior

After the trusted V4 runtime carrier has successfully returned `NO_WORK`, one bounded post-result step reloads current private `main` authority and the canonical `control-runtime-state` queue using the same admitted private capability.

For currently eligible unmaterialized OPEN gaps, in deterministic repository/Mission order, it looks for an existing public PR whose body contains the exact current markers:

- `Mission: `<mission_id>` revision `<mission_revision>``;
- `Gap: `<gap_id>``.

Private identifiers are used only inside the trusted job and are never emitted publicly by this path.

A candidate is materializable only when all of these remain true:

- the gap is `OPEN`, unmaterialized and every declared dependency is canonically satisfied;
- current Mission and repository-authority blobs still bind the gap;
- the target repository is exact and public;
- exactly one open PR claims the exact current Mission revision and gap;
- that PR targets `main`, is unmerged and currently mergeable;
- exact PR head branch/SHA and exact current base branch/SHA still match immediately before the queue write;
- there is no execution lock;
- private `main`, runtime ref and queue blob still match the fresh snapshot;
- the originating TICK is still current and within the existing freshness window at the atomic CAS boundary.

At most **one** candidate is materialized per `NO_WORK` invocation. It becomes the same ordinary `ACTIVE/REVIEW` task already produced by the existing owner-admin activation logic. The next fresh canonical TICK sees that task through normal V4 selection.

The public runtime result for the invocation remains the already-computed `NO_WORK`; materialization is logged only with public candidate identity. No private Mission/gap/queue data is added to the public result protocol.

## Fallback discovery

If eligible Mission work exists but no exact candidate is available, no queue mutation occurs. The existing public-safe `replenishment_proposals` remain available as diagnostic/governance evidence. They contain only public repository identity plus opaque authority/activation keys and do not authorize candidate-less BUILD.

Multiple exact PRs claiming the same governed gap, target drift, stale authority, dependency ambiguity or any other identity inconsistency fails closed instead of guessing which candidate to activate.

## Authority boundary

Automatic replenishment consumes **existing Mission authority**; it does not create new authority.

The change removes only the redundant approval handshake between an already-authoritative current OPEN gap and an already-existing exact candidate. It does not remove or weaken any later boundary:

- new or changed Mission scope still requires governed Mission evolution;
- candidate creation is outside this mechanism;
- review policy remains exact;
- `HOLD_AFTER_PASS` remains an owner/integration boundary;
- `integration_enabled=false` remains unchanged;
- deployment, publication, delivery and irreversible external effects remain separately governed.

The existing explicit owner-admin replenishment path remains available for bounded administrative use; it is no longer required for the automatic exact-candidate path.

## One writer model

This mechanism deliberately does not add a second queue writer. It reuses:

- existing owner-admin eligibility and task materialization functions;
- the existing admitted carrier private capability;
- the existing runtime `_write_queue_exact` atomic private-main no-op + runtime-ref CAS;
- the same current TICK freshness check at the CAS boundary.

There is still one canonical queue, one runtime CAS model and one Scheduled Runner.

## Failure behavior

The path is fail-closed. Invalid private state, stale authority, candidate ambiguity, non-public target, stale/moved target identity, live execution lock, stale TICK, private ref/queue movement or CAS rejection cannot create a task.

If there is no exact candidate, ordinary `NO_WORK` plus public-safe replenishment proposals is preserved. If the automatic path detects an ambiguity or consistency defect, the workflow fails visibly while the underlying public-safe carrier result can still be published; no guessed queue mutation is performed.

## Reversibility

This change introduces no schema migration, durable discovery state, new queue, new scheduler, new Runner, feature flag, database, lifecycle state or Runner prompt generation.

Rollback is an ordinary reviewed source rollback of:

- `scripts/control_v4_auto_replenish.py`;
- its bounded post-`NO_WORK` workflow step;
- the focused tests and documentation.

Already materialized tasks are ordinary V4 tasks and require no queue migration or rewind. Git history is the rollback record.

## Non-goals

This is not a generic planner, Mission generator, candidate creator, candidate-less BUILD mechanism, auto-merge mechanism, retry ledger, fairness system or second state plane. New Mission scope still requires the existing governed authority-evolution process.
