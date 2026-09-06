# Control Engine

Public deterministic Control library, validation surface and bounded private-state carrier.

## V4 boundary

`market-predictions/control-engine` owns **no semantic Control runtime authority** and persists no private Control runtime state. Canonical Mission authority and mutable runtime state remain solely in private `market-predictions/control-plane`.

The recurring ChatGPT Control Runner remains the one semantic Runner. Because Scheduled invocations cannot reliably perform direct private-repository mutation, V4 runtime state changes are transported through the owner-bound public issue-command surface and executed by the reviewed deterministic `control-v4-runtime-carrier.yml` carrier. The carrier accepts only typed runtime commands/events, validates current private V4 authority and the one canonical queue, and writes only `control-runtime-state:control/DISPATCH_QUEUE.json` through exact-old-ref compare-and-swap with mandatory readback.

Public issue comments are transport/audit evidence only. They are never a queue, Mission, status plane or authority source. Runtime responses contain only a bounded public-safe projection and opaque task token; raw private queue, Mission, acceptance, authority and review-state content is never mirrored into this repository or public issue transport.

The former V3.1 runtime workflow remains retired. Retained V3.1 kernel, migration and validation code exists only while concrete rollback/migration/validation dependencies remain.

The V4 runtime carrier is intentionally activation-bounded to `integration_enabled=false`; target integration remains fail-closed until a separate reviewed carrier extension is justified. V1 also acts only on publicly readable target repositories; unsupported/private targets fail closed instead of receiving a second credential path.

There is still one private queue, one Scheduled semantic Runner and no provider fallback, broker, database, second scheduler or second state plane.

See `docs/PUBLIC_PRIVATE_BOUNDARY_V4.md` for the complete V4 public/private boundary.