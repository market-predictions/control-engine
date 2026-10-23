# Control Engine

Deterministic Control validation, GitHub transport and guarded private-state carrier. **Not an AI programmer or a second Control authority.**

## Current operating policy (2026-10-18)

The principal-approved [Control Operating Model](https://github.com/market-predictions/control-plane/blob/main/control/CONTROL_OPERATING_MODEL.md) in the **private** Control Plane is the canonical human-facing policy:

- **`control-go`** starts work in an active ChatGPT Control project chat. ChatGPT is the **primary developer**, not Codex or Work.
- Existing **GitHub Actions** performs applicable project tests/CI and bounded background completion of already-requested reviews.
- **Codex GitHub Code Review** is the independent exact-head reviewer. Codex Cloud environments for Codex **code implementation** are not a prerequisite for ordinary review; each target repository still needs actual review access.
- **Work** is optional for specific browser or cross-application requirements. It is not part of the routine critical path.
- The **Scheduled ChatGPT Runner and retired Guardians are disabled**, and push notifications are off by principal choice. They must not be re-enabled as an assumed fix for earlier unattended GitHub write restrictions.
- **Scoped productive milestone (2026-10-18):** Weekly ETF PR #131 exercised same-holder phase continuation, an independent finding, repair, exact-head CI/re-review and separately approved integration/owner-admin DONE closeout. It does not prove unattended AI reasoning or productive next-task execution.


### Core-flow scope (Agent/Hermes excluded by default)

The native `mode: control-go` path is Control engineering/orchestration, **not the Agent-framework product**. To avoid recurring false Control gates, it skips `market-predictions/agent` both when queuing new authorized Mission gaps and when selecting existing tasks. Its previous Agent task remains unchanged in the canonical queue and can be handled separately when explicitly requested; neither Agent CI nor any required Agent acceptance check is suppressed. The historical event/legacy paths do not inherit this selection filter. All tasks in scope still use the original V4 private authority, holder, lease, CAS, review, and integration holds.

**This excludes the optional Agent/Hermes product from default task selection; it does not disable legitimate project acceptance checks or claim the Agent project is fixed.**


### Selected private target repositories (Control V4 scoped capability)

The same native `control-go` workflow accepts an **exact** `owner/name`
repository from current private Mission and repository authority, including
selected private repositories. For a targeted start use `mode: control-go` and supply the exact repository.
With an empty input, Control selects a publicly readable authorized task;
private repositories require an explicit exact owner/name selection.

Trusted existing GitHub Actions computes at most one exact current-authorized
target and mints a short-lived GitHub App **read-only target token** only if
that target is private. Public targets keep the original anonymous GitHub read
path. The pre-existing `control-plane` contents-write capability remains a
separate repository-restricted token; it cannot write target code. An ordinary
ChatGPT engineer needs its own fresh valid Control holder and independently
authorized project write capability. No target read token is a merge grant.

The existing exact-head PR, CI, Codex-review, holder, lease, CAS and
`HOLD_AFTER_PASS` controls are unchanged. An inaccessible or unauthorized
private repository fails closed; no scope expansion by public comments or
automatic discovery. Unattended NO_WORK replenishment proposals remain
public-only rather than minting tokens for every registered private Mission.
Before issuing a private EVENT read capability, the scope selector reuses the
carrier's full WORK binding: task token, action, repository, exact PR/head/base,
and current unexpired holder must all match. A matching run ID alone is insufficient.
Public issue/audit transport may expose repository, PR, commit and status
metadata, never private file content, tokens, private queue or Mission bodies.

### Native same-task continuation (adopted; productive milestone 2026-10-18)

New `mode: control-go` starts use `v41:control-go:<GitHub run id>`. A validated
progress EVENT can return ordinary `WORK` for the next phase of the **same task**,
retaining the exact original lock, start time and expiry in its one atomic CAS.
No new acquisition, queue field, permission grant or lease renewal is introduced.
The distinct run identity preserves historical `v41:gh:` EVENT release behavior
and the disabled Scheduled Runner compatibility contract.

`YIELD`, `REVIEW_UNAVAILABLE`, `READY`, a blocked/no-progress result and candidate
drift release the holder. An active chat may briefly observe CI/Codex completion;
after at most 180 seconds of waiting in that invocation, or before ending the
turn, it must YIELD while the holder is valid. Original target-effect freshness
clocks still apply. Public same-run TICKs can revalidate a retained holder, but
cannot acquire a task after release or expiry. Later semantic engineering uses a new native start and current evidence. The
bounded background review-completion job below needs no new semantic start.

Engine PR #188 adopted the interaction. The scoped PR #131 milestone supplies
real native start, same-holder phase and authorized closeout evidence; current
status remains a fresh projection of canonical authority/queue and target facts.

### Review feedback on the next Control handover

For an already-governed `ACTIVE / REVIEW` task with an exact candidate PR,
the existing owner-started `control-go` carrier reads the live public
GitHub Codex summary and current commit check-runs **before acquiring the
holder**. The normal `CONTROL_INTERACTIVE_HANDOVER_V1` receipt includes a
small `review_observation` with the exact head, Codex progress/findings and
observed CI state. Stale heads, missing data, ambiguous comments and GitHub
errors are reported as unknown or stale, never as success. Only the verified
Codex bot's summary for the exact head is eligible for a no-findings
observation; previous-commit results do not carry forward.

This is **read-only advisory metadata**, not a new queue state, external
review attestation, independent approval, or authorization to send, integrate
or mark a task `PASS`. Current owner/holder/lease/event/CAS and separate CI,
acceptance and merge gates remain unchanged. ChatGPT must still read GitHub
afresh when resuming; no background wake-up or repeated review request is
implied. Existing `BUILD` tasks without a bound candidate do not receive
review observations until the normal `CANDIDATE_READY` transition.

### Mission-driven task replenishment (implemented 2026-10-14)

The native owner-started `control-go` path now proposes to materialize
**at most one** dependency-eligible, unmaterialized `OPEN` gap from the
*currently authorized Mission and repository authority* as ordinary
`QUEUED / BUILD / candidate=null`. The same canonical V4 private queue,
validator and main/runtime atomic CAS are reused. Normal task priority and
the existing Agent task are not changed. No PR is manufactured.

This is **not** authority to promote new analysis findings into Mission
scope: analyses may inform a reviewed Mission update, after which current
OPEN gaps are eligible for queue replenishment. No new queue, service,
scheduler, autonomous background worker or bypass is introduced.

The authorized queue append was verified on 2026-10-14: WRO-GAP-50 was appended as `QUEUED/BUILD`; no second queue was introduced.

### Owner-controlled finalization after squash merge

The existing `FINALIZE_INTEGRATED` Control owner-admin operation accepts an
exact reviewed PR merged by GitHub's normal merge, squash or rebase method.
For rewritten merge histories it checks the PR-bound `merge_commit_sha`
against the **current target base branch** via GitHub ancestry. A merged flag,
unrelated commit, stale candidate head or unadvanced target branch alone never
grants `DONE`. Exact queue candidate identity, protected owner command,
private-main/runtime atomic CAS and `HOLD_AFTER_PASS` are unchanged.
GitHub's squash merge is *not* automatic Control task finalization; an explicit
owner-admin closeout is still required.

### Native start and background review completion

`Control V4 Runtime Carrier → Run workflow → mode: control-go` is the native
human start. It acquires one governed task and posts the existing handover on
issue #106. Native `v41:control-go:` progress retains its exact original holder;
YIELD, READY and drift release it. Engine PR #188 and Weekly ETF PR #131 provide
scoped historical proof of same-task finding/repair/re-review and approved closeout.

The optional `repository` input (for example `market-predictions/weekly-etf`)
narrows both OPEN-gap materialization and the actual task claim to that current
Mission's repository. Leave it empty to retain queue priority. It grants no new
Mission scope, never claims unrelated client work, and cannot select Agent through
the core start. Unknown repositories fail before queue mutation. The input is
ignored by review-resume and issue-comment continuation; the exact holder still
controls every continuation.

The same workflow's hourly `:30` **review-resume** job (also manually selectable)
finishes one already-requested clean EXTERNAL review without waking ChatGPT.
The initial scheduled runs were blocked: run
[39159113103](https://github.com/market-predictions/control-engine/actions/runs/39159113103)
was rejected before job creation because the repository's Actions execution
policy then omitted `schedule`. On 2026-10-18, policy 4000 initially allowed only
`issue_comment`, `pull_request`, `push` and `workflow_dispatch`, with actor
`market-predictions`. Check **Settings → Actions → Policies**, separately from
Actions General. After explicit principal approval on 2026-10-18, the owner saved
only the addition of `schedule`; GitHub confirmed **Policy updated**. The sole
owner actor restriction, Active enforcement and all other settings were preserved.
A policy edit, manual run or successful CI alone does not prove a scheduled run
or productive background completion. Keep the existing implementation and await
actual scheduled evidence; do not add a substitute clock to bypass this policy.

It reads the existing private queue, requires no live holder, exact internal PASS,
immutable owner request/trusted Codex PASS, no current-head findings and all
explicitly configured GitHub Actions checks successful on that exact commit.
Empty check configuration, stale head/base, edited/ambiguous evidence and failures
stay pending. A matching expired claim from an interrupted chat is cleared only
in that same task completion using the existing expiry rule; other claims stay
untouched. The final evidence recheck precedes the existing atomic private
main/runtime CAS; duplicates see READY and do nothing. No target writes, repair,
new work, lease renewal or merge occurs. A real delayed review reaching READY
with the chat closed is required before claiming productive background liveness.

For an already-registered interactive request, the private pending record binds
the task and exact request reference. Its immutable owner-authored public comment
must explicitly request review of the full current head and base after internal
PASS. It need not repeat private Mission/gap tokens from the separate owner-admin
import envelope; owner-admin imports retain that envelope requirement. Both paths
reuse the same immutable trusted-bot exact-candidate PASS validation.
The manual diagnostic run
[39165602292](https://github.com/market-predictions/control-engine/actions/runs/39165602292)
exposed this request-format mismatch on 2026-10-18: a green Actions run returned
`PENDING` and did not complete the task. Require the actual `READY` result and
canonical task transition; green workflow status alone is not completion proof.

Private authority remains data only. Cron lives in the existing public Engine;
GitHub may delay/drop runs or disable public schedules after 60 inactive days.
The next run reads pending work afresh; use native GitHub re-enablement after
inactivity. No Guardian or keep-alive commits. Existing push/e-mail settings
remain off. Read `CONTROL_V4_REVIEW_RESUME` in Actions logs for the actual result.
The replaced Work handoff, probe and inert PULSE pilot have been removed.

Project-specific stack failures (such as Agent's Hermes/FreeLLMAPI live model check) are not outages of Control infrastructure. A required failing test still blocks **that project's** acceptance; it never justifies a fabricated PASS.

## V4 runtime security boundary — still binding

`market-predictions/control-engine` owns **no semantic Control authority** and persists **no private queue**. Mission, repository and runtime authority remain in `market-predictions/control-plane@main`; the only mutable runtime queue is `control-runtime-state:control/DISPATCH_QUEUE.json`.

Existing V4 guarded transitions enforce exact task/holder, nonrenewable lease, fresh public TICK, authenticated command/result correlation, exact PR/head/base, atomic private-main no-op + runtime-ref GraphQL compare-and-swap and atomic EVENT holder release. `integration_enabled=false` remains a protected merge hold; owner-authorized integration is a separate action. Public issue #106 is transport/audit **only**.

The legacy Scheduled prompt/configuration stays bound compatibility data for existing V4 validation; the AI Runner remains disabled. The background-review job is deterministic and does not supply unattended ChatGPT reasoning.

V4 replenishment remains bounded by current Mission, repo authority, dependency and exact owner-authored candidate PR eligibility. No phantom BUILD task or synthetic PR is allowed. Never invent a new Mission, bypass an approval or fabricate a queue status for a dashboard.

No parallel Runner/queue/broker/Guardian/retry ledger or duplicate state plane. Existing carrier code remains subject to current V4 protocol validations and tests.

## Documentation

- [Private canonical Control System Index](https://github.com/market-predictions/control-plane/blob/main/control/SYSTEM_INDEX.md) and [Operating Model](https://github.com/market-predictions/control-plane/blob/main/control/CONTROL_OPERATING_MODEL.md): actual user interaction and authority hierarchy.
- [Public/private boundary](docs/PUBLIC_PRIVATE_BOUNDARY_V4.md): enforced technical trust and CAS controls.
- [Replenishment history](docs/CONTROL_V4_REPLENISHMENT_DISCOVERY.md) and [stabilization record](docs/CONTROL_V4_STABILIZATION_2026_09_09.md): technical background; current queue/authority always need live readback.
