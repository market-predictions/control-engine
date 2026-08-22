# Cloudflare Lightweight B1 V1

Status: **shadow implementation only**

Related Control issue: `market-predictions/control-plane#199`

## Purpose

Provide a fast, bounded semantic assurance execution surface without changing the Control authority model.

This implementation is deliberately smaller than the historical provider-B path.

```text
A1 = ChatGPT heavy engineering
B0 = deterministic GitHub evidence
B1 = one logical governance_release_assurance slot
GitHub = only queue/claim/result authority
Cloudflare = optional lightweight semantic executor
Work = independent deep/recovery executor
```

## First-principles boundaries

Cloudflare does not own or store canonical Control state. It receives no GitHub token and no repository tools. The GitHub runner prepares the bounded semantic package and performs all lifecycle writes.

The model is pinned to:

```text
@cf/openai/gpt-oss-120b
```

One exact task lineage may receive at most one Cloudflare infrastructure attempt once the live path is activated. There is no model fallback, provider fallback, retry/backoff framework or paid-route escalation.

## Bounded semantic package

The implementation enforces byte budgets rather than adding token-estimation infrastructure:

```text
exact diff             <= 32,000 bytes
assurance contract     <=  8,000 bytes
bounded extra evidence <=  8,000 bytes
total semantic pack    <= 52,000 bytes
```

If the package does not fit, the deterministic routing decision is `WORK_REQUIRED`.

## Minimal routing

`classify_execution_surface()` emits only a hard decision:

```text
work_required=true|false
```

Work is required when:

- explicitly required by the caller/project contract;
- the exact diff exceeds the bounded Cloudflare budget;
- the change touches defined Control authority/executor paths.

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

Extra fields, Markdown fences, wrong candidate identity, invalid enums, missing findings for FAIL/INDETERMINATE or otherwise malformed output are rejected locally.

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

The future live integration must release/resume the exact B1 claim and leave the lineage for the ChatGPT Work backstop after one Cloudflare infrastructure attempt.

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

Do not activate the fast path until all of the following are proven in order:

1. unit/contract regressions pass;
2. shadow calibration has no unexplained false PASS;
3. a harmless exact-head live canary proves shared B1 CAS claim/readback/`START_PROVEN`/result/finalization with no candidate mutation;
4. one consequential standard-risk production assurance succeeds;
5. only then may private canonical Control doctrine be promoted from Work-only to dual-executor/single-role B1.

Until those gates pass, the existing ChatGPT Work B1 profile remains canonical.
