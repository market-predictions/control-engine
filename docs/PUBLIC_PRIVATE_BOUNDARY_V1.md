# Control Engine Public/Private Boundary V1

## Purpose

`market-predictions/control-engine` is the public deterministic execution and CI layer for the private `market-predictions/control-plane`.

The separation exists for two reasons:

1. deterministic validation can execute on public GitHub-hosted runners without consuming private-repository Actions minutes; and
2. Control runtime state, project evidence and credentials remain private.

## Core rule

```text
PUBLIC CODE != PRIVATE STATE
```

The public engine may validate **contracts and sanitized/synthetic inputs**. It must never become a mirror of private Control state.

## Public engine — allowed

- deterministic compilers and validators;
- generic schemas;
- generic rendering models;
- tests;
- synthetic fixtures;
- public-safe documentation;
- CI workflows that require no private secret or private-repository read access;
- version/manifest metadata.

## Public engine — forbidden

- `control-runtime-state` or copies of that branch;
- dispatch queues, work claims or live run state;
- handovers or worker-result ledgers from private Control;
- private mission/project intake payloads;
- private project registries copied from Control;
- customer, client, patient, employee or other real-person data;
- raw private-repository source/evidence bundles;
- API tokens, private keys, credentials or secret values;
- provider/account bindings that require secrecy;
- mutable authority to act on private Control state.

## Private Control responsibilities

The private `control-plane` remains authoritative for:

- project scope and registry;
- runtime queues and claims;
- worker/assurance state;
- handovers and worker results;
- mission contracts and private evidence;
- provider bindings and credentials;
- merge/release/deploy/delivery/financial authority;
- mapping private evidence into a sanitized engine input.

## Consumption model

Private Control must consume the public engine by an **exact immutable Git commit SHA**.

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
4. the private pin records the engine manifest version;
5. changing the pin is an explicit governed Control change.

## Data-flow rule

The default public CI path uses only code and synthetic fixtures stored in this public repository.

Private Control data is **not uploaded to public Actions**. If a future use case requires public execution over derived data, a separate sanitization/export contract and leakage review are mandatory before that capability exists.

## Dashboard V1 placement

The deterministic retained-progress compiler and event schema live in the public engine. The real project registry and canonical retained-progress event ledger remain private Control data.

Thus:

```text
public engine = scoring/validation/render-model semantics
private Control = project identity + evidence + canonical event ledger
```

## Authority boundary

The public engine is computational authority only. A successful engine run cannot itself:

- claim work;
- start a Control worker;
- issue assurance PASS/FAIL;
- merge a private PR;
- declare a mission satisfied;
- release/deploy/deliver;
- select a paid provider;
- spend funds;
- mutate private runtime state.
