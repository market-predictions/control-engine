# Public / Private Boundary — Control Autonomy V3.1

## Authority

The private repository `market-predictions/control-plane` is the sole Control planning/authority and runtime-state plane.

The public repository `market-predictions/control-engine` contains deterministic code and the single trusted runtime-mutating workflow. It must not persist private Control runtime state.

## Runtime writer

Exactly one normal GitHub Actions workflow may mutate canonical Control runtime state:

`/.github/workflows/control-kernel-v3-1.yml`

The workflow may transiently clone private Control state into an ephemeral runner and may persist only bounded V3.1 mutations to `control-runtime-state` using the trusted Control Kernel capability.

Semantic workers A1 and B1 never receive canonical runtime write credentials. They request `CLAIM`, `RECORD`, or `RELEASE`; the kernel authenticates caller capability, validates the current claim and live authority, and performs any canonical mutation itself.

## Private state

Canonical runtime state is limited to:

- `control/DISPATCH_QUEUE.json`;
- `control/worker-results/<task-id>--<run-id>.json`.

Git history is the mutation audit trail.

## Semantic boundary

A1 owns only `IMPLEMENTATION` and `REPAIR` semantic execution. B1 owns only `ASSURANCE` semantic judgment. The kernel performs no semantic inference.

B1 is candidate-read-only and has no merge or candidate mutation authority. The authenticated caller capability, not a supplied role string, determines whether a caller may operate as A1 or B1.

## Deterministic integration

`TICK` performs `RECONCILE -> INTEGRATE -> FEED`. Integration is deterministic GitHub mutation, not semantic worker work. It is permitted only when frozen candidate authority and current live restrictions both allow it and exact GitHub facts still match.

## Removed architecture

V3.1 has no normal provider fallback, no A2 baseline, no semantic integration task, no project-intake routing database, no mandatory handover projection, no worker-direct result write, no secondary queue and no private runtime-mutating workflow.

Historical implementations are provenance in Git history and are not part of the active source or authority surface.
