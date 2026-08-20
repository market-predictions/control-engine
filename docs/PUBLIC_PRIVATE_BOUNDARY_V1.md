# Control Engine Public/Private Boundary V1

## Purpose

`market-predictions/control-engine` is the public deterministic execution and CI layer for the private `market-predictions/control-plane`.

The separation exists for two reasons:

1. deterministic validation and bounded orchestration compute can execute on public GitHub-hosted runners without consuming private-repository Actions minutes; and
2. Control runtime state, project evidence and governance authority remain private.

## Core rule

```text
PUBLIC CODE != PUBLIC STATE
PUBLIC RUNNER != SECOND CONTROL AUTHORITY
```

The public repository may contain only public-safe executable code, schemas, synthetic fixtures, tests and documentation. It must never become a durable mirror of private Control state.

A trusted default-branch actuator may, however, **transiently process private Control state in an ephemeral runner** when all requirements in `PRIVATE_RUNTIME_ACTUATOR_V1.md` are satisfied. This distinction is essential: repository visibility governs stored code/data, not whether a trusted compute process may use a secret credential to operate an authoritative private system.

## Public engine — allowed

- deterministic compilers and validators;
- generic schemas and state-transition helpers;
- generic rendering and orchestration models;
- tests and synthetic fixtures;
- public-safe documentation;
- CI workflows that require no private state;
- trusted `main` scheduled/manual actuator workflows that transiently access private state using least-privilege Actions secrets;
- bounded private-state reads and writes only when the private repository remains the sole authoritative state plane and exact CAS/postcondition rules are enforced;
- version/manifest metadata.

## Public engine — forbidden durable content

The following may never be committed, mirrored, cached, artifacted or intentionally logged in this public repository/execution plane:

- `control-runtime-state` or copies of that branch;
- dispatch queues, work claims or live run state;
- handovers or worker-result ledgers from private Control;
- private mission/project intake payloads;
- private project registries copied from Control;
- customer, client, patient, employee or other real-person data;
- raw private-repository source/evidence bundles;
- API tokens, private keys, credentials or secret values;
- provider/account bindings that require secrecy.

The public repository's own `GITHUB_TOKEN` must never become private Control authority.

## Trusted transient actuator exception

`NO_PRIVATE_RUNTIME_STATE` means **no private runtime state is persisted or exposed in the public plane**. It does not prohibit a trusted, ephemeral `main` Actions job from reading and updating the private authoritative repository through a separately provisioned least-privilege secret credential.

Such a workflow is valid only when it:

1. is executable solely from trusted `main`; PR/fork execution cannot reach private state;
2. keeps the repository-level `GITHUB_TOKEN` read-only;
3. receives private access through a separately provisioned secret credential;
4. stores private inputs/output only under ephemeral runner storage with restrictive permissions;
5. sends no private state to public logs, artifacts or caches;
6. verifies exact immutable Control code identity before processing private state;
7. computes transitions against an exact observed private runtime ref + exact queue blob;
8. discards/recomputes on any state movement and uses ordinary non-force persistence only;
9. enforces bounded private write scopes and canonical postcondition readback;
10. treats public-run success as non-authoritative unless the exact intended state is durably visible in private Control.

The current contract is `docs/PRIVATE_RUNTIME_ACTUATOR_V1.md`.

## Private Control responsibilities

The private `control-plane` remains authoritative for:

- project scope and registry;
- runtime queues and claims;
- worker/assurance state;
- handovers and worker results;
- mission contracts and private evidence;
- provider bindings and credential authorization;
- merge/release/deploy/delivery/financial authority;
- all canonical state against which an actuator must prove its transition.

Running the actuator in the public repository does not transfer any of these authorities to public repository state.

## Consumption model

Private Control may consume deterministic public-engine modules by an **exact immutable Git commit SHA**.

Forbidden authority references:

```text
main
latest
HEAD
floating tag
unverified branch name
```

A Control engine pin is eligible only when:

1. repository is exactly `market-predictions/control-engine`;
2. commit is a full 40-character SHA;
3. the public commit has successful engine CI;
4. the private pin records the engine manifest version where bundle consumption is used; and
5. changing a private engine pin is an explicit governed Control change.

This bundle-consumption rule is separate from Scheduled Worker A V2: the scheduled actuator itself executes only when its workflow is integrated into trusted public `main`, while it independently pins the private Control state-machine implementation it invokes by exact 40-character SHA.

## Data-flow rule

Ordinary public CI uses only code and synthetic fixtures stored in this repository.

Private Control data is not uploaded into ordinary CI. The only permitted private-data path is a specifically authorized trusted actuator governed by the transient rules above. Private payloads remain ephemeral and non-exportable.

## Dashboard placement

The deterministic retained-progress compiler and event schema live in the public engine. The real project registry and canonical retained-progress event ledger remain private Control data.

Thus:

```text
public engine = scoring/validation/render-model semantics + bounded trusted compute
private Control = project identity + evidence + canonical state + authority
```

## Authority boundary

The public repository is computational infrastructure. A public CI result by itself cannot:

- fabricate a Control claim;
- issue assurance PASS/FAIL;
- merge a private PR;
- declare a mission satisfied;
- release/deploy/deliver;
- select a paid provider;
- spend funds.

A trusted Scheduled Worker A actuator may create a real A1 claim only by successfully writing and reading it back from the private canonical Control queue under the existing claim contract. Its authority is therefore derived from, bounded by and evidenced in private state; never from the public run record alone.
