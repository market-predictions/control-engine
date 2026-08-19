# Control Engine

Public deterministic execution and CI engine for Control.

This repository intentionally contains **no private Control runtime state**. Its purpose is to host generic deterministic compilers, validators, schemas, synthetic fixtures, and public GitHub Actions CI that can be consumed by the private `market-predictions/control-plane` through immutable commit-SHA pinning.

See `docs/PUBLIC_PRIVATE_BOUNDARY_V1.md` for the trust boundary.
