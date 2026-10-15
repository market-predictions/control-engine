# Control Engine

Deterministic Control validation, GitHub transport and guarded private-state carrier. **Not an AI programmer or a second Control authority.**

## Current operating policy (adopted 2026-10-13)

The principal-approved [Control Operating Model](https://github.com/market-predictions/control-plane/blob/main/control/CONTROL_OPERATING_MODEL.md) in the **private** Control Plane is the canonical human-facing policy:

- **`control-go`** starts work in an active ChatGPT Control project chat. ChatGPT is the **primary developer**, not Codex or Work.
- Existing **GitHub Actions** performs the applicable project tests/CI.
- **Codex GitHub Code Review** is the independent exact-head reviewer. Codex Cloud environments for Codex **code implementation** are not a prerequisite for ordinary review; each target repository still needs actual review access.
- **Work** is optional for specific browser or cross-application requirements. It is not part of the routine critical path.
- The **Scheduled ChatGPT Runner and retired Guardians are disabled**, and push notifications are off by principal choice. They must not be re-enabled as an assumed fix for earlier unattended GitHub write restrictions.
- **Interactive Control holder/event path proven (2026-10-15):** native owner run `38712403129` published a handover; the valid `INTERNAL_REPAIR` EVENT atomically transitioned Agent task to `ACTIVE/REPAIR` and released the holder. This proves governed rejection/closeout, **not** accepted end-to-end project delivery.


### Core-flow scope (Agent/Hermes excluded by default)

The native `mode: control-go` path is Control engineering/orchestration, **not the Agent-framework product**. To avoid recurring false Control gates, it skips `market-predictions/agent` both when queuing new authorized Mission gaps and when selecting existing tasks. Its previous Agent task remains unchanged in the canonical queue and can be handled separately when explicitly requested; neither Agent CI nor any required Agent acceptance check is suppressed. The historical event/legacy paths do not inherit this selection filter. All tasks in scope still use the original V4 private authority, holder, lease, CAS, review, and integration holds.

**This excludes the optional Agent/Hermes product from default task selection; it does not disable legitimate project acceptance checks or claim the Agent project is fixed.**

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

### Native owner-started direct handover (start and guarded review rejection verified)

The existing **Control V4 Runtime Carrier** GitHub Actions workflow now offers
`Run workflow → mode: control-go` as the default native owner start.
It invokes the unchanged guarded V4 carrier exactly once, then publishes a
`CONTROL_INTERACTIVE_HANDOVER_V1` receipt on Control Engine issue #106.
ChatGPT Control can read that receipt in the active chat and continue work,
using the existing governed project PR and Codex review.

This is a **human-started** flow: a GitHub Actions event cannot wake an
inactive ChatGPT conversation. The receipt is transport, not a semantic
review verdict, a permanent claim, or authority to bypass a current lease.
An accepted Control EVENT still requires the existing live holder,
candidate and private CAS checks. The job attempts a guarded YIELD if
handover publication fails. `mode: legacy-work` retains the historical
optional Work pilot, but is not the default.

Do not mark this mode SEMI_AUTONOMOUS_LIVE until exact-head CI,
independent review, merge, an actual owner-dispatch/receipt readback,
and a real guarded task transition are proven.

Project-specific stack failures (such as Agent's Hermes/FreeLLMAPI live model check) are not outages of Control infrastructure. A required failing test still blocks **that project's** acceptance; it never justifies a fabricated PASS.

## V4 runtime security boundary — still binding

`market-predictions/control-engine` owns **no semantic Control authority** and persists **no private queue**. Mission, repository and runtime authority remain in `market-predictions/control-plane@main`; the only mutable runtime queue is `control-runtime-state:control/DISPATCH_QUEUE.json`.

Existing V4 guarded transitions enforce exact task/holder, nonrenewable lease, fresh public TICK, authenticated command/result correlation, exact PR/head/base, atomic private-main no-op + runtime-ref GraphQL compare-and-swap and atomic EVENT holder release. `integration_enabled=false` remains a protected merge hold; owner-authorized integration is a separate action. Public issue #106 is transport/audit **only**.

The legacy Scheduled Runner uses typed TICK/EVENT messages when enabled; the currently suspended `workflow_dispatch` interactive-resume job contains an owner-start + Work WAKE/READY/WORK handoff. These are technical capabilities/historical references, **not** instructions to make Work or the Scheduled Runner a required dependency of the adopted interactive operating policy. Their existence does not prove that the unimplemented ChatGPT interactive authority handoff works.

V4 replenishment remains bounded by current Mission, repo authority, dependency and exact owner-authored candidate PR eligibility. No phantom BUILD task or synthetic PR is allowed. Never invent a new Mission, bypass an approval or fabricate a queue status for a dashboard.

No parallel Runner/queue/broker/Guardian/retry ledger or duplicate state plane. Existing carrier code remains subject to current V4 protocol validations and tests.

## Documentation

- [Private canonical Control System Index](https://github.com/market-predictions/control-plane/blob/main/control/SYSTEM_INDEX.md) and [Operating Model](https://github.com/market-predictions/control-plane/blob/main/control/CONTROL_OPERATING_MODEL.md): actual user interaction and authority hierarchy.
- [Public/private boundary](docs/PUBLIC_PRIVATE_BOUNDARY_V4.md): enforced technical trust and CAS controls.
- [Interactive PULSE pilot](control/CONTROL_V41_INTERACTIVE_PULSE_PILOT.md): **historical, non-adopted pilot**, not the current command.
- [Replenishment history](docs/CONTROL_V4_REPLENISHMENT_DISCOVERY.md) and [stabilization record](docs/CONTROL_V4_STABILIZATION_2026_09_09.md): technical background; current queue/authority always need live readback.
