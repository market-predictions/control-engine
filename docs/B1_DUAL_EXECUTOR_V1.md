# CONTROL B1 Dual Executor V1

Status: **GATE-8 ACTIVATION CANDIDATE / NOT YET CANONICAL-ACTIVE**  
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
- transport/provider/malformed output is execution unavailable, never semantic INDETERMINATE;
- configured STANDARD contract is included in bounded pre-call evidence;
- actual call-count/model/max-token/no-fallback provenance is validated after the call before canonical semantic persistence.

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
- a `+1` reaction from the trusted Codex bot on the exact request comment with a terminal exact-head review -> clean `PASS`;
- historical clean issue comments are never PASS evidence;
- wrong-head/stale review -> execution unavailable;
- no terminal evidence yet -> pending;
- connector error/timeout/unparseable evidence -> execution unavailable.

A processing acknowledgement such as an eyes reaction is never a verdict and never `START_PROVEN`.

Codex is review-only in this path. It receives no queue, claim, merge, release or canonical-result authority.

## Non-authoritative pre-merge handshake

A workflow introduced by the candidate itself is deliberately **not** used to trigger the pre-merge Codex handshake. `workflow_dispatch` would not exist on the default branch yet, while PR-event workflow tokens can be restricted from writing the trigger comment. The smallest reliable pre-merge proof is therefore a trusted external GitHub actuator posting one exact candidate-bound `@codex review` request.

The pre-merge handshake:

- fresh-reads the live PR head before posting the request;
- embeds the exact candidate SHA and bounded review contract;
- observes only trusted Codex bot evidence;
- treats findings as review evidence and a `+1` reaction on the exact request comment as clean completion only with terminal exact-head review evidence;
- remains `semantic_authority=false`;
- never reads or mutates private Control queue/result state.

This is transport/executor evidence only and never establishes canonical `START_PROVEN` or a canonical B1 verdict.

## Gate-8 canonical activation candidate

The Gate-8 activation candidate adds the normal public execution surface:

```text
.github/workflows/canonical-b1-dual-executor-v1.yml
scripts/canonical_b1_dual_executor_v1.py
```

The workflow is hourly plus manual dispatch and has no push trigger. Before any reconcile, selection or claim it reads the private `CONTROL_ASSURANCE_EXECUTION_PROFILE_V1` and exits successfully without lifecycle mutation unless the profile is exactly `ACTIVE`.

Once activated, the normal path:

1. reconciles canonical private lifecycle/intake state without auto-resuming an `EXECUTION_UNAVAILABLE` semantic run;
2. deterministically selects exactly one preferred B1 task;
3. takes and exact-readbacks one canonical B1 claim;
4. reconstructs exact PR/head/diff/changed-file/workflow evidence;
5. builds verdict-free B0 evidence with current lease and exact lineage bindings;
6. routes deterministically to STANDARD or DEEP using the integrated classifier;
7. validates executor output and STANDARD post-call provenance or trusted DEEP exact-head review evidence;
8. revalidates the unchanged PR head/current claim;
9. persists result, `CONTROL_TERMINAL_COMPLETION_V1` and ghost-free finalization using the existing connected-runtime primitive.

The private execution profile remains `CANDIDATE_GATE8` until this activation candidate receives fresh independent exact-head DEEP assurance and is integrated. The candidate workflow therefore cannot claim work merely by existing on a branch or by being merged before the profile promotion transaction is complete.

## Legacy recovery path

`.github/workflows/scheduled-worker-b-v2.yml` and `worker-b-wake-bridge-v1.yml` remain manual-only legacy recovery surfaces. They have no schedule and are not the normal B1 path. Their old comments naming ChatGPT Work as the normal target are retired by this activation candidate.

Legacy recovery does not gain automatic retry/fallback authority and must not race the canonical B1 workflow.

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

All are `EXECUTION_UNAVAILABLE` / no semantic verdict. They do not fabricate `INDETERMINATE`.

## Scheduled Tasks

ChatGPT/Work Scheduled Tasks are removed from the B1 critical execution path. Existing historical tasks may remain disabled as evidence. They may be used only for observability/reminders and never as canonical claim/result authority.

## Promotion gates

Required sequence:

1. deterministic unit tests for both executor adapters;
2. existing Cloudflare shadow calibration green;
3. trusted-external non-authoritative Codex GitHub handshake proves request -> exact Codex completion -> deterministic classification with `semantic_authority=false`;
4. independent exact-head assurance of the complete #199 foundation by an executor that is not certifying its own activation path;
5. merge exact assured foundation;
6. one harmless shared-B1 canonical claim canary;
7. one consequential standard-risk production assurance;
8. independently assure and integrate this minimal activation delta, then promote the private canonical execution profile to `ACTIVE` and retire legacy Work/provider assumptions from the normal path.

Gate 8 is not green merely because the activation code exists. The activation candidate itself changes the executor boundary and therefore requires fresh DEEP assurance before integration/profile promotion.

## Forbidden complexity

Do not add a Cloudflare Worker runtime, Cloudflare Cron, D1, KV, R2, Durable Objects, Queues, Agents SDK, AI Gateway, model router, multiple models, retries, automatic provider fallback, B2/B3, second queue, second state store, confidence scoring or consensus voting.

`principal_manual_relay_count=0` remains the target acceptance invariant for the canonical live path.
