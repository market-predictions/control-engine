# Control Engine

Public deterministic execution and CI engine for Control.

This repository intentionally contains **no persisted private Control runtime state**. It hosts generic deterministic compilers, validators, schemas, synthetic fixtures and public GitHub Actions compute. The private `market-predictions/control-plane` remains the sole authoritative governance/state plane.

Two governed execution modes exist:

1. deterministic public modules consumed through immutable commit-SHA pinning; and
2. trusted default-branch actuator workflows that may transiently process private Control state in an ephemeral runner using least-privilege secrets, while persisting every authoritative transition only in the private Control state plane.

Scheduled Worker A V2 is the implementation/repair actuator. Scheduled Worker B V2 is the independent assurance actuator. Both use the same public-compute/private-state boundary and short-lived Control GitHub App transport; neither stores private runtime state in this repository, public logs, artifacts or caches.

See `docs/PUBLIC_PRIVATE_BOUNDARY_V1.md`, `docs/PRIVATE_RUNTIME_ACTUATOR_V1.md` and `docs/PRIVATE_RUNTIME_ASSURANCE_ACTUATOR_V1.md` for the trust and actuator contracts.
