# Cloudflare Lightweight B1 V1

Status: **dual-executor foundation only; not yet canonical production authority**

Related Control issue: `market-predictions/control-plane#199`

## Purpose

Provide the bounded STANDARD semantic assurance executor inside one logical B1 role without changing the Control authority model.

```text
A1 = ChatGPT implementation_operations
B0 = deterministic GitHub evidence
B1 = one logical governance_release_assurance slot
GitHub = only queue/claim/result authority
Cloudflare = STANDARD bounded semantic executor
Codex = DEEP semantic review executor
```

Cloudflare and Codex are executor metadata only. They are not independent workers and do not own queue, claim, merge, release or canonical result authority.

## First-principles boundaries

Cloudflare does not own or store canonical Control state. It receives no GitHub token and no repository tools. GitHub Control prepares the bounded semantic package and owns all lifecycle transitions.

The model is pinned to:

```text
@cf/openai/gpt-oss-120b
```

One exact task lineage may receive at most one Cloudflare infrastructure attempt once the live path is activated. There is no model fallback, provider fallback, retry/backoff framework or paid-route escalation.

A Cloudflare infrastructure failure is `EXECUTION_UNAVAILABLE`; it does not automatically switch the same lineage to Codex or any historical Work backstop. Any later governed recovery requires a fresh deterministic Control decision under the canonical queue/claim contract.

## Bounded semantic package

The implementation enforces byte budgets rather than adding token-estimation infrastructure:

```text
exact diff             <= 32,000 bytes
assurance contract     <=  8,000 bytes
bounded extra evidence <=  8,000 bytes
total semantic pack    <= 52,000 bytes
```

Before executor selection, `measure_semantic_budget()` measures the prospective exact pack and `classify_execution_surface()` evaluates every hard builder budget. If **any** component or the complete serialized pack exceeds its bound, the deterministic routing result is `work_required=true`, which now means **DEEP review required**. A caller-supplied diff threshold may be stricter than 32,000 bytes but may never relax the builder's 32,000-byte hard maximum.

The `work_required` field name is retained temporarily as a compatibility wire alias; it no longer means ChatGPT Work.

## Minimal routing

`classify_execution_surface()` emits one hard decision:

```text
work_required=true|false
```

DEEP review is required when:

- explicitly required by the caller/project contract;
- the exact diff exceeds the effective Cloudflare diff budget;
- the assurance contract exceeds 8,000 bytes;
- bounded extra evidence exceeds 8,000 bytes;
- the complete prospective semantic pack exceeds 52,000 bytes;
- the change touches defined Control authority, executor or assurance-contract paths, including the Cloudflare and Codex adapters.

There is no score, confidence model, percentage router or round-robin state.

## Semantic execution contract

Cloudflare semantic review is forbidden unless the supplied B0 capsule proves:

```text
semantic_verdict_present=false
candidate_sha=<exact frozen candidate>
START_PROVEN=true
deterministic_contradictions=[]
```

The model receives exactly two messages: one system contract and one serialized bounded evidence package. No tools are supplied.

The expected model output has exactly four keys:

```json
{
  "candidate_sha": "<40-char frozen SHA>",
  "verdict": "PASS|FAIL|INDETERMINATE",
  "summary": "...",
  "findings": []
}
```

Extra fields, wrong candidate identity, invalid enums, missing findings for FAIL/INDETERMINATE or otherwise malformed output are rejected locally. A single JSON fence is normalized deterministically; arbitrary surrounding prose is rejected.

## Failure semantics

Transport/provider/output failures are not semantic assurance verdicts.

Examples:

```text
HTTP 429 / capacity
HTTP 5xx
network/timeout
invalid Cloudflare response envelope
malformed reviewer JSON
candidate mismatch
```

These are classified as `EXECUTION_UNAVAILABLE_*` and must never be converted into semantic `INDETERMINATE`.

A prospective semantic pack that does not fit the bounded STANDARD contract is different: it is deterministically classified **before** Cloudflare invocation as DEEP, so budget overflow is not discovered late as a STANDARD execution failure.

## Shadow calibration

`.github/workflows/cloudflare-b1-shadow-v1.yml` is intentionally non-authoritative:

- repository contents permission is read-only;
- no private Control state is fetched;
- no GitHub App token is created;
- no queue/claim/result writes occur;
- three synthetic known-outcome cases are evaluated: PASS, FAIL and INDETERMINATE;
- a false PASS fails the shadow check immediately;
- provider unavailability is reported as execution unavailable rather than a semantic result.

Shadow evidence cannot be used as B1 authority.

## Promotion gates

Do not activate the dual-executor production path until all of the following are proven in order:

1. unit/contract regressions pass;
2. Cloudflare shadow calibration has no unexplained false PASS;
3. a non-authoritative exact-head Codex handshake proves GitHub-to-Codex activation and deterministic result observation;
4. the complete foundation receives fresh independent exact-head assurance without self-certifying its own activation assumptions;
5. after assured integration, a harmless shared-B1 canary proves GitHub-owned claim/readback/`START_PROVEN`/semantic execution/result/finalization with no candidate mutation;
6. one consequential standard-risk production assurance succeeds;
7. only then may private canonical Control doctrine be promoted to the dual-executor/single-role B1 profile.

Until those gates pass, the new dual-executor profile remains foundation-only. Historical ChatGPT Work and Scheduled ChatGPT evidence is preserved as history but neither is part of the target B1 critical path.
