# Control V4 — Interactive PULSE pilot (V4.1 candidate, NOT adopted)

Status: **read-only pilot candidate**. Existing V4 authority, canonical Scheduled
Runner generation, private runtime queue, lease, CI/review and CAS stay unchanged.
This file is a companion to the current V4 architecture, not a new authority.

## Outcome and scope

Use one short interactive ChatGPT project-chat instruction to advance authorized
engineering work without needing unattended Scheduled GitHub writes. Preserve
Work/Codex capacity for required fresh independent external review; ordinary
interactive ChatGPT performs engineering and internal review.

Short user instruction: `[control] PULSE`.

That instruction must trigger the following behavior **in the active chat**:

1. Read *current* private Mission, repository authority, runner configuration,
   canonical queue and public target PR/CI. Past conversation is context, not proof.
2. Use the existing V4 selection order and current authority. The read-only helper
   `control_engine.v4_runtime_protocol.plan_interactive_pulse_v4` may classify the
   queue and an independently fetched target candidate. It does **not** acquire
   a holder and never authorizes a Control or target effect.
3. If there is safe, currently authorized engineering work, perform as much as
   possible in the current interactive invocation, preserving every existing
   target-effect and review gate. Never manufacture a TICK, holder, generation,
   lease, semantic PASS or manual queue transition.
4. Put code, test and exact-head CI evidence in GitHub. Make changes on a governed
   PR/branch and perform readback. Do not treat a code push as V4 lifecycle DONE.
5. If execution is blocked, report the *specific* gate with links and next step.
   No invented completion or automatic Work review.
6. GitHub Actions can complete deterministic CI between chat sessions; new
   ChatGPT reasoning does **not** continue in the background after the turn ends.

## Read-only planner contract

Input must be a current queue previously validated against *private main*
Mission/authority (the existing carrier's `_load_current` does this), plus exact
booleans `runtime_enabled` and `integration_enabled`. Optional
`live_candidate` must come from a **fresh trusted** public PR read for the exact
repository/PR, not user-supplied comments, Work text or a cached candidate.

The output is **PRIVATE diagnostic data** and must not be logged or published
in a public GitHub Actions run: it includes the private task identity.

Result statuses:

- `RUNTIME_DISABLED`, `INTEGRATION_HOLD`: no execution.
- `HOLDER_PRESENT_NO_INTERACTIVE_ACQUISITION`: current/expired holder needs
  the canonical recovery path; never clear the lock from Chat.
- `NO_ELIGIBLE_QUEUED_TASK`: no selectable *queued* task; does not prove
  Mission work is exhausted.
- `BUILD_REQUIRES_INTERACTIVE_BINDING`: a candidate-less BUILD remains legitimate governed engineering, but this planner cannot grant a holder or target effect. Other candidate-less phase combinations fail closed.
- `FRESH_TARGET_READ_REQUIRED`: obtain current PR facts before classification.
- `CANDIDATE_DRIFT_REQUIRES_GOVERNED_RECONCILIATION`: do not rebind the queue
  manually or reinterpret old review evidence as current.
- `TARGET_EXACT_INTERACTIVE_BINDING_REQUIRED`: PR identity matches the queue
  snapshot, but **interactive V4 acquisition/target effects are NOT authorized**
  without a separately implemented, reviewed and adopted identity/lease/authority
  binding. The helper never claims otherwise.

The pure helper has no network, write, scheduled trigger, second queue or state
plane. It delegates task priority and validation to existing V4 functions.

## Evidence gathered so far

- Interactive connected GitHub comment
  [#6099101304](https://github.com/market-predictions/control-engine/issues/106#issuecomment-6099101304)
  was created 2026-10-10 and exact-body readback succeeded. This proves
  interactive **chat** GitHub write on that session, not mobile-device parity,
  unattended runtime write, private queue write or durable autonomous liveness.
- A previously observed private queue versus public candidate mismatch
  demonstrated that PULSE must fail closed on drift. Keep exact private queue
  identities, hashes, task state and candidate bindings in private Control
  surfaces only; do not publish even abbreviated snapshots in this repository.
- The current Scheduled Runner, retired Guardians and Work POC remain disabled.
  Do not re-enable them as part of this pilot.

## Acceptance gates before any production V4.1 adoption

1. Focused planner tests plus complete exact-head Control Engine CI SUCCESS;
   verify read-only side effects and privacy.
2. Mobile interactive GitHub comment proof separately, if mobile parity matters.
3. Fresh independent review of an **explicit** interactive authority/admission
   design that retains current Mission/generation/holder/lease/freshness/target
   effect/atomic private CAS; no shared-GitHub-app identity spoofing and no
   second mutating ingress.
4. Paired public/private adoption and a genuinely productive end-to-end PULSE
   that performs a governed candidate transition, leaves no ghost holder and
   resumes cleanly from canonical GitHub truth. Only then expand to six PULSE
   sessions and optional read-only notifications.

Until those gates are met, PULSE is an interactive engineering aid and
**not** a second semantic Control Runner.

## Native owner-start attribution pilot (read-only)

This same candidate also adds an **inert** `human-start-probe` job inside the
*existing* V4 carrier workflow (no new runner, queue, scheduler, or workflow
file). To prove the distinction, the owner must post exactly
`CONTROL_V41_HUMAN_START_PROBE` using the **native GitHub website/mobile UI**
on public Control Engine issue #106. The job reads the immutable comment back
via its own GitHub read token, requiring owner login, exact issue/comment/body,
age <=120s and an explicitly present null `performed_via_github_app` field.
Any comment created by the connected ChatGPT/Work GitHub app must be rejected.
The diagnostic job has `contents:read` / `issues:read`, creates no private
capability and cannot mutate Control state.

A native owner credential/PAT could also produce null GitHub App attribution:
this evidence proves *non-ChatGPT-app owner credentials*, **not** physical human
presence, and does not authenticate a later separate ChatGPT EVENT. Additional
binding is needed before any V4.1 authority adoption. Missing GitHub API
attribution fields fail closed. This is a testable least-privilege trust boundary,
not a claim that a ChatGPT-written issue comment proves interactive origin.

No unattended Work use, API-billed LLM provider, or owner self-approval is
introduced.
