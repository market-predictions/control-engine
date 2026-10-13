# Control Engine

Deterministic Control validation, GitHub transport and guarded private-state carrier. **Not an AI programmer or a second Control authority.**

## Current operating policy (adopted 2026-10-13)

The principal-approved [Control Operating Model](https://github.com/market-predictions/control-plane/blob/main/control/CONTROL_OPERATING_MODEL.md) in the **private** Control Plane is the canonical human-facing policy:

- **`control-go`** starts work in an active ChatGPT Control project chat. ChatGPT is the **primary developer**, not Codex or Work.
- Existing **GitHub Actions** performs the applicable project tests/CI.
- **Codex GitHub Code Review** is the independent exact-head reviewer. Codex Cloud environments for Codex **code implementation** are not a prerequisite for ordinary review; each target repository still needs actual review access.
- **Work** is optional for specific browser or cross-application requirements. It is not part of the routine critical path.
- The **Scheduled ChatGPT Runner and retired Guardians are disabled**, and push notifications are off by principal choice. They must not be re-enabled as an assumed fix for earlier unattended GitHub write restrictions.
- This is **INTERACTIVE_WORKING**, **not yet SEMI_AUTONOMOUS_LIVE**: the trusted interactive holder/candidate-reconciliation and semantic closeout step through current Control authority is still unproven. A direct ChatGPT GitHub edit is not a Control TICK/EVENT or a holder claim.

Project-specific stack failures (such as Agent's Hermes/FreeLLMAPI live model check) are not outages of Control infrastructure. A required failing test still blocks **that project's** acceptance; it never justifies a fabricated PASS.

## V4 runtime security boundary — still binding

`market-predictions/control-engine` owns **no semantic Control authority** and persists **no private queue**. Mission, repository and runtime authority remain in `market-predictions/control-plane@main`; the only mutable runtime queue is `control-runtime-state:control/DISPATCH_QUEUE.json`.

Existing V4 guarded transitions enforce exact task/holder, nonrenewable lease, fresh public TICK, authenticated command/result correlation, exact PR/head/base, atomic private-main no-op + runtime-ref GraphQL compare-and-swap and atomic EVENT holder release. `integration_enabled=false` remains a protected merge hold; owner-authorized integration is a separate action. Public issue #106 is transport/audit **only**.

The existing Agent relay retains the historical `CONTROL_WORK_POC_REQUEST_20261009` transport marker for compatibility; this marker is **not** a Work dependency and the old Work task stays disabled. Renaming it would require a second cross-repository workflow change and would not improve the first productive handoff. The legacy Scheduled Runner uses typed TICK/EVENT messages only if separately authorized and enabled; it remains **disabled**. The existing `workflow_dispatch` `interactive-resume` job now accepts an **owner-native GitHub Actions start** and a correlated readiness response from the already-active ChatGPT conversation (not Work). The owner run does **not** acquire a private holder until the verified READY response. It then uses the unchanged V4 carrier to acquire one holder, sends its bounded WORK capsule to Agent PR #3 and retains the existing failure-YIELD safeguard. Only the normal, exact holder-bound V4 EVENT can advance review/candidate state and atomically release the holder. This path is still a **candidate pending live validation**: the connected GitHub app cannot perform a native owner `workflow_dispatch` on the user's behalf with available tools, so one explicit GitHub owner click is required per launch. It is not evidence that interactive closeout or next-task continuation already works.

V4 replenishment remains bounded by current Mission, repo authority, dependency and exact owner-authored candidate PR eligibility. No phantom BUILD task or synthetic PR is allowed. Never invent a new Mission, bypass an approval or fabricate a queue status for a dashboard.

No parallel Runner/queue/broker/Guardian/retry ledger or duplicate state plane. Existing carrier code remains subject to current V4 protocol validations and tests.

## Documentation

- [Private canonical Control System Index](https://github.com/market-predictions/control-plane/blob/main/control/SYSTEM_INDEX.md) and [Operating Model](https://github.com/market-predictions/control-plane/blob/main/control/CONTROL_OPERATING_MODEL.md): actual user interaction and authority hierarchy.
- [Public/private boundary](docs/PUBLIC_PRIVATE_BOUNDARY_V4.md): enforced technical trust and CAS controls.
- [Interactive PULSE pilot](control/CONTROL_V41_INTERACTIVE_PULSE_PILOT.md): **historical, non-adopted pilot**, not the current command.
- [Replenishment history](docs/CONTROL_V4_REPLENISHMENT_DISCOVERY.md) and [stabilization record](docs/CONTROL_V4_STABILIZATION_2026_09_09.md): technical background; current queue/authority always need live readback.
