# Control Engine

Public deterministic execution kernel for Control Autonomy V3.1.

## Canonical runtime model

Control Engine contains no persisted private Control runtime state. The private `market-predictions/control-plane` remains the sole planning/authority and runtime-state plane.

Exactly one public workflow owns canonical Control runtime mutation:

`/.github/workflows/control-kernel-v3-1.yml`

Its deterministic implementation is:

`/scripts/control_kernel_v31.py`

The kernel supports only `TICK`, `CLAIM`, atomic `RECORD`, and `RELEASE`. `TICK` performs `RECONCILE -> INTEGRATE -> FEED`. It performs no semantic inference.

Semantic lanes are exactly:

- A1: `IMPLEMENTATION`, `REPAIR`;
- B1: `ASSURANCE`.

There is no baseline A2, provider fallback, semantic `PROJECT_INTEGRATION` task, worker-direct runtime write, project-intake routing plane, mandatory handover projection, or second queue.

See `docs/PUBLIC_PRIVATE_BOUNDARY_V3_1.md` for the V3.1 trust boundary. Historical implementations remain available through Git history, not the active source surface.
