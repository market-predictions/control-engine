# CONTROL B1 Dual Executor V1

Status: **DESIGNED / IMPLEMENTED FOUNDATION / NOT YET CANONICAL-ACTIVE**  
Related Control issue: `market-predictions/control-plane#199`

## Purpose

Preserve one logical independent `governance_release_assurance/B1` role while using two semantic execution surfaces:

- `STANDARD` -> Cloudflare Workers AI (`@cf/openai/gpt-oss-120b`)
- `DEEP` -> native OpenAI Codex GitHub code review

GitHub Control remains the only authority for queue selection, claims, leases, `START_PROVEN`, canonical results, terminal completion, integration routing and release of capacity.

## First-principles correction

The previous design assumed a Scheduled ChatGPT/Work session could both reason and mutate private canonical GitHub state. Live tests on 2026-08-22 proved scheduler invocation but repeatedly produced no canonical B1 claim and auto-paused the scheduled task. The corrected architecture separates intelligence from actuation:

```text
semantic model != lifecycle authority
```

A semantic executor never creates its own authority. The GitHub Control Pump owns the lifecycle before and after semantic execution.

## Target topology

```text
ChatGPT A1 -> frozen candidate + ASSURANCE_REQUEST
                         |
                         v
               private GitHub Control
              queue / claim / authority
                         |
                         v
                GitHub Control Pump + B0
                         |
                   deterministic class
                    /             \
               STANDARD           DEEP
                  |                 |
                  v                 v
          Cloudflare Workers AI   Codex GitHub review
          one bounded call        native @codex review
          no tools/token          read-only reviewer
                    \             /
                     \           /
                      v         v
                  deterministic adapter
                         |
                         v
                  private GitHub Control
             result / completion / finalization
```

## Stable identity

There is still exactly one logical assurance worker:

```text
role=governance_release_assurance
worker_instance=B1
capacity=1
```

`cloudflare` and `codex` are executor metadata only. They are not B2/B3 roles and do not create a second queue or state plane.

## Deterministic routing

The conceptual classification is:

```text
assurance_class=STANDARD | DEEP
```

For compatibility with the initial Cloudflare shadow candidate, the existing `work_required` Boolean is temporarily retained as a wire-level alias:

```text
work_required=false -> STANDARD
work_required=true  -> DEEP
```

No ChatGPT Work dependency is implied by the compatibility field name. A later cleanup may rename it only after live proof; no migration framework is required.

`DEEP` is reserved for deterministic conditions such as:

- bounded Cloudflare evidence budget exceeded;
- project-local contract explicitly requires deep review;
- candidate changes canonical Control authority, claim/lease semantics, assurance semantics, merge/release authority, either semantic executor, or a core security boundary.

No percentage routing, learned risk score, consensus layer or model voting.

## Authority sequence

The production sequence MUST be:

1. GitHub Control fresh-reads canonical private state.
2. GitHub deterministically selects one eligible B1 task.
3. GitHub takes the canonical B1 claim and persists a bounded lease.
4. GitHub exact-readback proves the same task/role/B1/run/handover/candidate/lease: `START_PROVEN=true`.
5. B0 produces verdict-free exact-head evidence.
6. GitHub invokes exactly one semantic executor selected by the deterministic class.
7. Executor output is locally validated and exact-candidate bound.
8. GitHub revalidates the same current claim and unchanged candidate.
9. GitHub alone persists `PASS | FAIL | INDETERMINATE`, terminal completion and exact-claim finalization.

The model never writes canonical queue/result state directly.

## Cloudflare STANDARD executor

Existing `CONTROL_CLOUDFLARE_LIGHTWEIGHT_B1_V1` invariants remain:

- pinned `@cf/openai/gpt-oss-120b`;
- exactly one bounded request;
- no GitHub tools or credentials exposed to the model;
- no retry/model/provider/paid fallback;
- strict local verdict validation;
- transport/provider/malformed output is execution unavailable, never semantic INDETERMINATE.

## Codex DEEP executor

Codex is invoked through the native GitHub code-review integration using `@codex review` and bounded extra guidance.

Control treats only the documented Codex GitHub bot identities as executor evidence:

```text
chatgpt-codex-connector
chatgpt-codex-connector[bot]
```

The adapter binds the exact candidate SHA and recognizes:

- native exact-head Codex review findings -> `FAIL`;
- a finding explicitly tagged `CONTROL_B1_INDETERMINATE:` -> `INDETERMINATE` when no definite violation exists;
- a `+1` reaction from the trusted Codex bot on the exact request comment -> clean `PASS`;
- historical clean issue comments are never PASS evidence;
- wrong-head/stale review -> execution unavailable;
- no terminal evidence yet -> pending;
- connector error/timeout/unparseable evidence -> execution unavailable.

A processing acknowledgement such as an eyes reaction is never a verdict and never `START_PROVEN`.

Codex is review-only in this path. It receives no queue, claim, merge, release or canonical-result authority.

## Non-authoritative pre-merge handshake

The repository handshake canary is PR-head triggered on `pull_request:synchronize` for PR #69 rather than `workflow_dispatch`, because a workflow introduced by the PR itself cannot be manually dispatched until that workflow already exists on the default branch.

The canary:

- checks out and revalidates the exact live PR head;
- has only the bounded repository permissions it needs, including `statuses: write` for its non-authoritative commit status;
- posts one exact candidate-bound `@codex review` request;
- observes reactions only on that exact request plus exact-head Codex reviews/comments;
- publishes `semantic_authority=false`;
- never reads or mutates private Control queue/result state.

It is transport/executor evidence only and never establishes canonical `START_PROVEN` or a canonical B1 verdict.

## Failure semantics

Infrastructure failures remain distinct from semantic verdicts.

Examples:

```text
Codex not configured
Codex quota exhausted
Codex connector error
review never completes
review binds wrong commit
Cloudflare 429/timeout/capacity
malformed executor output
claim expires or is lost
candidate moves
```

All are `EXECUTION_UNAVAILABLE` / no verdict. They do not fabricate `INDETERMINATE`.

## Scheduled Tasks

ChatGPT/Work Scheduled Tasks are removed from the B1 critical execution path. Existing historical tasks may remain disabled as evidence. They may be used only for observability/reminders and never as canonical claim/result authority.

## Promotion gates

This document does not itself activate the dual-executor profile.

Required sequence:

1. deterministic unit tests for both executor adapters;
2. existing Cloudflare shadow calibration remains green;
3. PR-head-triggered non-authoritative Codex GitHub handshake proves request -> exact Codex completion -> deterministic classification with `semantic_authority=false`;
4. independent exact-head assurance of the complete #199 foundation by an executor that is not certifying its own activation path;
5. merge exact assured foundation;
6. one harmless shared-B1 canonical claim canary;
7. one consequential standard-risk production assurance;
8. only then promote private canonical execution profile and retire legacy Work/provider assumptions.

## Forbidden complexity

Do not add a Cloudflare Worker runtime, Cloudflare Cron, D1, KV, R2, Durable Objects, Queues, Agents SDK, AI Gateway, model router, multiple models, retries, automatic provider fallback, B2/B3, second queue, second state store, confidence scoring or consensus voting.

`principal_manual_relay_count=0` remains the target acceptance invariant for the canonical live path.
