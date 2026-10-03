# Control V4 — NO_WORK governed replenishment

Status: public current-truth extension for Control V4.

## Purpose

Prevent a governed project from becoming operationally idle merely because the canonical runtime queue has no runnable task while the already-committed current Mission still contains eligible OPEN work.

Current Mission scope is already semantic authority. Therefore an admitted TICK that initially finds no executable queue item may bind an **already-authorized** gap to an exact existing public candidate without another principal approval, but only when that candidate already exists, is unambiguous and comes from the canonical owner/repository. The mechanism may never invent Mission scope, create a candidate, merge a pull request, enable integration or grant production authority.

## Exact behavior

After the trusted V4 runtime carrier has computed provisional `NO_WORK`, one bounded step reloads current private `main` authority and the canonical `control-runtime-state` queue using the same admitted private capability. That provisional carrier result is not yet the Runner-visible terminal result.

Automatic mutation is enabled only when current private `main` contains the exact replenishment policy marker:

```text
auto_materialization_policy=MISSION_OPEN_EXACT_CANDIDATE_V1
```

If that marker is absent, public tooling remains proposal-only and performs no queue mutation.

The freshly loaded private state must also have `runtime_enabled=true` and `integration_enabled=false`. Runtime disablement is an authority boundary: when runtime is disabled, candidate discovery/materialization is not attempted and no replenishment queue write can occur.

For currently eligible unmaterialized OPEN gaps, in deterministic repository/Mission order, the step looks for an existing public PR whose body contains the exact current markers:

- `Mission: `<mission_id>` revision `<mission_revision>``;
- `Gap: `<gap_id>``.

Private identifiers are used only inside the trusted job and are never emitted publicly by this path.

A candidate is eligible for automatic materialize+acquire only when all of these remain true:

- the gap is `OPEN`, unmaterialized and every declared dependency is canonically satisfied;
- current Mission and repository-authority blobs still bind the gap;
- freshly loaded runtime authority is enabled and integration remains disabled;
- the target repository is exact and public;
- exactly one open PR claims the exact current Mission revision and gap;
- the PR is authored by the canonical owner;
- the PR head repository equals the governed repository exactly and is public; external/fork heads are rejected;
- that PR targets `main`, is unmerged and currently mergeable;
- exact PR source identity is rechecked on the exact PR read;
- there is no execution lock;
- the originating command is the exact admitted TICK and has not been superseded;
- exact PR head branch/SHA and exact current base branch/SHA still match immediately before the durable mutation;
- private `main`, runtime ref and queue blob still match the fresh snapshot;
- the originating TICK is still within the existing freshness window immediately before and at the atomic CAS boundary.

At most **one** candidate is processed per admitted TICK. The existing owner-admin logic first constructs the ordinary `ACTIVE/REVIEW` task in memory. The existing runtime acquisition primitive then acquires that exact new task in the same in-memory queue image. Only after the full WORK capsule exists are command currency and exact public target identity revalidated and the combined materialize+acquire queue image committed with the existing `_write_queue_exact` private-main no-op + runtime-ref atomic CAS.

There is therefore no durable intermediate state in which auto-replenishment created an unlocked task and waits for a later TICK. One durable mutation both materializes the task and establishes the ordinary holder.

If that CAS succeeds, the Runner-visible result for the admitted TICK is ordinary `WORK`. If no exact candidate is available, no queue mutation occurs and the Runner-visible result may remain ordinary terminal `NO_WORK`, optionally enriched by the existing public-safe read-only replenishment proposal. **A published terminal `NO_WORK` never accompanies an auto-replenishment queue mutation.**

Before entering the only path that can write, the step pre-seeds a public-safe fail-closed `ERROR` result. If transport becomes ambiguous around the CAS, result publication therefore cannot fall back to the carrier's original `NO_WORK`. A successful write is followed only by publication of the already-computed WORK capsule; no second target read or second queue transition is needed.

## Fallback discovery

If eligible Mission work exists but no exact candidate is available, no queue mutation occurs. The existing public-safe `replenishment_proposals` remain available as diagnostic/governance evidence. They contain only public repository identity plus opaque authority/activation keys and do not authorize candidate-less BUILD.

Multiple exact PR claims, an exact claim from an untrusted/fork source, target drift, stale authority, dependency ambiguity or any other identity inconsistency fails closed instead of guessing which candidate to activate.

## Authority boundary

Automatic replenishment consumes **existing Mission authority**; it does not create new authority.

The change removes only the redundant approval handshake between an already-authoritative current OPEN gap and an already-existing exact trusted candidate. It does not remove or weaken any later boundary:

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
- existing runtime task acquisition and WORK-capsule functions;
- the existing admitted carrier private capability;
- the existing runtime `_write_queue_exact` atomic private-main no-op + runtime-ref CAS;
- the same current-TICK supersession and freshness checks at the CAS boundary.

There is still one canonical queue, one runtime CAS model and one Scheduled Runner.

## Runner contract

The canonical Runner generation remains `b6f42d03a917ce58`. No prompt rotation is needed because the Runner-visible result contract is preserved:

- `BUSY` remains terminal and mutation-free;
- terminal published `NO_WORK` remains mutation-free;
- a successful acquisition-producing mutation is represented by the existing `WORK` result;
- TICK/EVENT wire shapes, holder lifecycle, lease, target-effect fences and semantic review/repair policy are unchanged.

The replenishment helper acts inside the already-admitted TICK workflow before final result publication; it does not introduce a new command or result type.

## Failure behavior

The path is fail-closed. Disabled runtime authority, invalid private state, stale authority, candidate ambiguity, untrusted/fork candidate source, non-public target, stale/moved target identity, live execution lock, stale/superseded TICK, private ref/queue movement or CAS rejection cannot create a task.

If there is no exact candidate, ordinary terminal `NO_WORK` plus public-safe replenishment proposals is preserved because no mutation occurred. If the automatic path reaches a potential write and then fails or becomes ambiguous, publication uses fail-closed `ERROR`, never the original `NO_WORK`.

## Reversibility

This change introduces no schema migration, durable discovery state, new queue, new scheduler, new Runner, feature flag, database, lifecycle state or Runner prompt generation.

Rollback is an ordinary reviewed source rollback of:

- `scripts/control_v4_auto_replenish.py`;
- its bounded post-carrier workflow step;
- the focused tests and documentation.

Already materialized/acquired tasks use the ordinary V4 task and holder schema and require no queue migration or rewind. Git history is the rollback record.

## Non-goals

This is not a generic planner, Mission generator, candidate creator, candidate-less BUILD mechanism, auto-merge mechanism, retry ledger, fairness system or second state plane. New Mission scope still requires the existing governed authority-evolution process.
