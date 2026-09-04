# Control Engine

Public deterministic Control library and validation surface.

## V4 boundary

Under Control V4 this repository owns **no active Control runtime writer** and persists no private Control runtime state.

Canonical Mission authority and runtime state remain in the private `market-predictions/control-plane` repository. After V4 cutover, the one recurring ChatGPT Control Runner operates that state through connected GitHub exact blob-SHA compare-and-swap.

The former V3.1 runtime workflow is retired at the V4 activation fence before V4 cutover. Retained V3.1 kernel, migration and validation code remains required deterministic rollback/migration/validation material while that concrete dependency exists; its presence does not make it an active runtime authority.

Normal CI and the existing read-only private validation carrier may remain active because neither can mutate canonical Control runtime state.

There is no replacement V4 runtime workflow, second queue, provider fallback or semantic worker infrastructure in this repository.

See `docs/PUBLIC_PRIVATE_BOUNDARY_V4.md` for the V4 public/private boundary.
