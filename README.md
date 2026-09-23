# Control Engine

Public deterministic Control library, validation surface and bounded private-state carrier.

## V4 boundary

`market-predictions/control-engine` owns **no semantic Control runtime authority** and persists no private Control runtime state. Canonical Mission authority and mutable runtime state remain solely in private `market-predictions/control-plane`.

The recurring ChatGPT Control Runner remains the one semantic Runner. Scheduled invocations transport typed TICK/EVENT commands through the owner-bound public issue-command surface; the reviewed deterministic `control-v4-runtime-carrier.yml` carrier applies only deterministic private queue transitions to `control-runtime-state:control/DISPATCH_QUEUE.json`.

Runtime writes use one exact atomic GraphQL `updateRefs` compare-and-swap. That mutation simultaneously fences private `main` at the expected authority SHA and advances `control-runtime-state` from the exact expected old SHA to one new commit. A successful mutation response is the definitive commit acknowledgement. Command freshness, authority, queue and old-ref checks occur before or inside that boundary. The carrier deliberately performs no fallible post-CAS readback that could convert a durable successful queue mutation into `ERROR`; each later command reloads and validates canonical private truth afresh.

TICK is deliberately small: recover an expired holder when required, select/acquire one eligible task, atomically persist ownership, and return the bounded public-safe `WORK` capsule. It performs no target-repository or pull-request network verification after ownership has been acquired. Target/candidate checks live at semantic EVENT boundaries where they can govern a state transition. EVENT transitions preserve exact holder identity and release accepted holders atomically with the semantic queue change.

Public issue comments are transport/audit evidence only. They are never a queue, Mission, status plane or authority source. Runtime responses contain only a bounded public-safe projection and opaque task token; raw private queue, Mission, acceptance, authority and review-state content is never mirrored into this repository or public issue transport.

The former V3.1 runtime workflow remains retired. Retained V3.1 kernel, migration and validation code exists only while concrete current dependencies remain. Obsolete V4-40 freeze helpers and the superseded post-CAS retry/readback mechanism are not current runtime code.

The V4 runtime carrier remains activation-bounded to `integration_enabled=false`; target integration remains fail-closed until a separate reviewed carrier extension is justified. There is still one private queue, one Scheduled semantic Runner and no provider fallback, broker, database, second scheduler, retry ledger or second state plane.

After a trusted `NO_WORK`, the existing carrier workflow may perform a **read-only advisory replenishment discovery** against current private Mission/queue truth. It reuses the existing governed project-replenishment eligibility and opaque approval-snapshot primitives and may expose only public-safe repository plus opaque authority/activation keys. Discovery never creates a candidate, task, approval, Mission revision or queue mutation; the existing project-level owner approval and `ACTIVATE_ROOT_CANDIDATE` path remain the only materialization boundary. Failure of this advisory step falls back to the original carrier result.

Generic new Mission/scope generation and candidate-less BUILD execution, including `[control] task overige: ...`, remain separate product decisions and are not implemented by replenishment discovery.

See `docs/PUBLIC_PRIVATE_BOUNDARY_V4.md` for the complete V4 public/private boundary, `docs/CONTROL_V4_REPLENISHMENT_DISCOVERY.md` for the reversible advisory discovery contract, and `docs/CONTROL_V4_STABILIZATION_2026_09_09.md` for the stabilization record.
