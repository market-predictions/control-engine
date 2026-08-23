from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

PROTOCOL_ID = "CONTROL_CLOUDFLARE_LIGHTWEIGHT_B1_V1"
MODEL_ID = "@cf/openai/gpt-oss-120b"
VERDICTS = frozenset({"PASS", "FAIL", "INDETERMINATE"})
MAX_DIFF_BYTES = 32_000
MAX_CONTRACT_BYTES = 8_000
MAX_BOUNDED_EVIDENCE_BYTES = 8_000
MAX_PACK_BYTES = 52_000
DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_SEED = 199001
DEFAULT_MAX_TOKENS = 512

CONTROL_PLANE_REPOSITORY = "market-predictions/control-plane"
CONTROL_ENGINE_REPOSITORY = "market-predictions/control-engine"
B0_PROTOCOL_ID = "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1"
B0_VERSION = "1.0"
B0_ASSURANCE_ROLE = "governance_release_assurance"
B0_ASSURANCE_WORKER = "B1"

_CONTROL_PLANE_SENSITIVE_PREFIXES = (
    "control/",
    "dispatcher/",
    "schemas/",
    "tools/control_",
)
_CONTROL_ENGINE_SENSITIVE_PREFIXES = (
    # Control Engine is itself execution/governance infrastructure. Route its
    # implementation, actuator, workflow, contract and bundle surfaces to DEEP
    # by top-level class so future files cannot silently fall through STANDARD.
    "control_engine/",
    "scripts/",
    ".github/workflows/",
    "docs/",
    "schemas/",
    "ENGINE_MANIFEST.json",
    "ENGINE_BUNDLE_V1.json",
)


class CloudflareB1Error(ValueError):
    pass


class CloudflareB1ExecutionUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _DuplicateJsonKey(ValueError):
    pass


@dataclass(frozen=True)
class SemanticBudgetMeasurement:
    diff_bytes: int
    contract_bytes: int
    evidence_bytes: int
    pack_bytes: int


@dataclass(frozen=True)
class ExecutionSurfaceDecision:
    work_required: bool
    reasons: tuple[str, ...]

    @property
    def cloudflare_eligible(self) -> bool:
        return not self.work_required


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateJsonKey(key)
        value[key] = item
    return value


def _valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value))


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _unwrap_single_json_fence(value: str) -> str:
    raw = value.strip()
    if not raw.startswith("```"):
        return raw
    match = re.fullmatch(r"```(?:json)?\s*\n?(.*?)\n?```", raw, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_NON_JSON")
    inner = match.group(1).strip()
    if not inner:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_NON_JSON")
    return inner


def lineage_id(*, task_id: str, handover_id: str, candidate_sha: str) -> str:
    if not task_id or not handover_id or not _valid_sha(candidate_sha):
        raise CloudflareB1Error("lineage identity is incomplete or invalid")
    raw = f"{task_id}\n{handover_id}\n{candidate_sha}\n".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def measure_semantic_budget(
    *,
    task_id: str,
    handover_id: str,
    candidate_sha: str,
    assurance_contract: str,
    acceptance_criteria: list[str],
    capsule: dict[str, Any],
    diff: str,
    bounded_evidence: Any,
) -> SemanticBudgetMeasurement:
    """Measure the exact prospective semantic pack before executor routing."""
    if not task_id or not handover_id or not _valid_sha(candidate_sha):
        raise CloudflareB1Error("semantic budget identity is incomplete or invalid")
    if not isinstance(assurance_contract, str):
        raise CloudflareB1Error("assurance_contract must be text")
    if not isinstance(acceptance_criteria, list):
        raise CloudflareB1Error("acceptance_criteria must be a list")
    if not isinstance(capsule, dict):
        raise CloudflareB1Error("capsule must be an object")
    if not isinstance(diff, str):
        raise CloudflareB1Error("diff must be text")

    pack = {
        "protocol_id": PROTOCOL_ID,
        "lineage_id": lineage_id(task_id=task_id, handover_id=handover_id, candidate_sha=candidate_sha),
        "task_id": task_id,
        "handover_id": handover_id,
        "candidate_sha": candidate_sha,
        "assurance_contract": assurance_contract,
        "acceptance_criteria": acceptance_criteria,
        "b0_capsule": capsule,
        "exact_diff": diff,
        "bounded_evidence": bounded_evidence,
    }
    return SemanticBudgetMeasurement(
        diff_bytes=len(diff.encode("utf-8")),
        contract_bytes=len(assurance_contract.encode("utf-8")),
        evidence_bytes=len(_json_bytes(bounded_evidence)),
        pack_bytes=len(_json_bytes(pack)),
    )


def classify_execution_surface(
    *,
    repository: str,
    changed_files: list[str],
    budget: SemanticBudgetMeasurement,
    capsule: dict[str, Any] | None = None,
    explicit_work_required: bool = False,
    max_diff_bytes: int = MAX_DIFF_BYTES,
) -> ExecutionSurfaceDecision:
    if not repository:
        raise CloudflareB1Error("repository is required")
    if any(not isinstance(path, str) or not path for path in changed_files):
        raise CloudflareB1Error("changed_files must contain non-empty paths")
    if not isinstance(budget, SemanticBudgetMeasurement):
        raise CloudflareB1Error("semantic budget measurement is required")
    if any(
        not isinstance(value, int) or value < 0
        for value in (budget.diff_bytes, budget.contract_bytes, budget.evidence_bytes, budget.pack_bytes)
    ):
        raise CloudflareB1Error("semantic budget values must be non-negative integers")
    if not isinstance(max_diff_bytes, int) or max_diff_bytes < 0:
        raise CloudflareB1Error("max_diff_bytes must be a non-negative integer")

    # If B0 evidence is supplied, repository identity is part of the same
    # canonical routing binding as changed_files. Validate it before selecting
    # prefixes so a caller cannot relabel a Control candidate as another repo.
    if capsule is not None:
        if not isinstance(capsule, dict):
            raise CloudflareB1Error("B0 routing capsule must be an object")
        if capsule.get("protocol_id") != B0_PROTOCOL_ID or capsule.get("version") != B0_VERSION:
            raise CloudflareB1Error("unsupported B0 capsule protocol for routing")
        routing_task = capsule.get("task")
        if (
            not isinstance(routing_task, dict)
            or not isinstance(routing_task.get("repository"), str)
            or not routing_task.get("repository")
        ):
            raise CloudflareB1Error("B0 routing repository evidence is missing or invalid")
        if routing_task.get("repository") != repository:
            raise CloudflareB1Error("repository does not match B0 routing evidence")

    normalized_changed_files = sorted(set(changed_files))
    reasons: list[str] = []
    if explicit_work_required:
        reasons.append("EXPLICIT_WORK_REQUIRED")
    if budget.diff_bytes > min(max_diff_bytes, MAX_DIFF_BYTES):
        reasons.append("DIFF_BUDGET_EXCEEDED")
    if budget.contract_bytes > MAX_CONTRACT_BYTES:
        reasons.append("CONTRACT_BUDGET_EXCEEDED")
    if budget.evidence_bytes > MAX_BOUNDED_EVIDENCE_BYTES:
        reasons.append("BOUNDED_EVIDENCE_BUDGET_EXCEEDED")
    if budget.pack_bytes > MAX_PACK_BYTES:
        reasons.append("SEMANTIC_PACK_BUDGET_EXCEEDED")

    prefixes: tuple[str, ...] = ()
    control_repository = repository in {CONTROL_PLANE_REPOSITORY, CONTROL_ENGINE_REPOSITORY}
    if repository == CONTROL_PLANE_REPOSITORY:
        prefixes = _CONTROL_PLANE_SENSITIVE_PREFIXES
    elif repository == CONTROL_ENGINE_REPOSITORY:
        prefixes = _CONTROL_ENGINE_SENSITIVE_PREFIXES

    for path in normalized_changed_files:
        if any(path.startswith(prefix) for prefix in prefixes):
            reasons.append(f"CONTROL_AUTHORITY_PATH:{path}")

    # A Control candidate may be STANDARD only when the exact routing paths are
    # bound to B0 evidence. DEEP decisions already fail safely, so historical
    # callers that deterministically route DEEP do not need weaker synthetic
    # capsule data merely to preserve the conservative outcome.
    if control_repository and not reasons:
        if not isinstance(capsule, dict):
            raise CloudflareB1Error("B0 capsule is required before STANDARD Control routing")
        evidence_changed_files = capsule.get("changed_files")
        if (
            not isinstance(evidence_changed_files, list)
            or any(not isinstance(path, str) or not path for path in evidence_changed_files)
            or evidence_changed_files != sorted(set(evidence_changed_files))
            or evidence_changed_files != normalized_changed_files
        ):
            raise CloudflareB1Error("changed_files do not match B0 routing evidence")

    return ExecutionSurfaceDecision(work_required=bool(reasons), reasons=tuple(sorted(set(reasons))))


def build_semantic_pack(
    *,
    task_id: str,
    handover_id: str,
    candidate_sha: str,
    assurance_contract: str,
    acceptance_criteria: list[str],
    capsule: dict[str, Any],
    diff: str,
    bounded_evidence: Any,
) -> dict[str, Any]:
    if not task_id or not handover_id or not _valid_sha(candidate_sha):
        raise CloudflareB1Error("semantic pack identity is incomplete or invalid")
    if not isinstance(assurance_contract, str) or not assurance_contract.strip():
        raise CloudflareB1Error("assurance_contract must be non-empty text")
    if not isinstance(acceptance_criteria, list) or not acceptance_criteria:
        raise CloudflareB1Error("acceptance_criteria must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in acceptance_criteria):
        raise CloudflareB1Error("acceptance_criteria contains an invalid item")
    if not isinstance(capsule, dict):
        raise CloudflareB1Error("capsule must be an object")
    if capsule.get("protocol_id") != B0_PROTOCOL_ID or capsule.get("version") != B0_VERSION:
        raise CloudflareB1Error("unsupported B0 capsule protocol")

    authority = capsule.get("authority")
    if not isinstance(authority, dict):
        raise CloudflareB1Error("capsule authority is missing or invalid")
    if (
        authority.get("logical_role") != B0_ASSURANCE_ROLE
        or authority.get("worker_instance") != B0_ASSURANCE_WORKER
        or authority.get("semantic_verdict_present") is not False
        or authority.get("merge_authority") is not False
        or authority.get("release_authority") is not False
    ):
        raise CloudflareB1Error("capsule authority does not match B0 assurance authority")

    task = capsule.get("task")
    if not isinstance(task, dict):
        raise CloudflareB1Error("capsule task identity is missing or invalid")
    if task.get("task_id") != task_id:
        raise CloudflareB1Error("capsule task does not match semantic lineage")
    if task.get("handover_id") != handover_id:
        raise CloudflareB1Error("capsule handover does not match semantic lineage")
    if task.get("candidate_sha") != candidate_sha:
        raise CloudflareB1Error("capsule candidate does not match frozen candidate")

    acceptance_digest = task.get("acceptance_criteria_sha256")
    actual_acceptance_digest = hashlib.sha256(_json_bytes(acceptance_criteria)).hexdigest()
    if not _valid_digest(acceptance_digest) or acceptance_digest != actual_acceptance_digest:
        raise CloudflareB1Error("acceptance criteria do not match B0 evidence digest")

    claim = capsule.get("claim")
    if not isinstance(claim, dict):
        raise CloudflareB1Error("capsule claim identity is missing or invalid")
    if claim.get("start_proven") is not True:
        raise CloudflareB1Error("START_PROVEN is required before semantic review")
    if (
        claim.get("state") != "ASSURANCE_EXECUTING"
        or claim.get("lease_current_at_observation") is not True
        or claim.get("active_role") != B0_ASSURANCE_ROLE
        or claim.get("active_worker_instance") != B0_ASSURANCE_WORKER
        or not isinstance(claim.get("active_run_id"), str)
        or not claim.get("active_run_id")
    ):
        raise CloudflareB1Error("capsule claim is not a current B1 assurance lease")

    diff_evidence = capsule.get("diff")
    source_digests = capsule.get("source_digests")
    actual_diff_digest = hashlib.sha256(diff.encode("utf-8")).hexdigest()
    if (
        not isinstance(diff_evidence, dict)
        or not _valid_digest(diff_evidence.get("sha256"))
        or diff_evidence.get("sha256") != actual_diff_digest
        or diff_evidence.get("bytes") != len(diff.encode("utf-8"))
        or not isinstance(source_digests, dict)
        or source_digests.get("diff_sha256") != actual_diff_digest
    ):
        raise CloudflareB1Error("diff does not match B0 evidence digest")

    if capsule.get("deterministic_contradictions") != []:
        raise CloudflareB1Error("semantic Cloudflare path requires an explicit empty contradiction list")

    budget = measure_semantic_budget(
        task_id=task_id,
        handover_id=handover_id,
        candidate_sha=candidate_sha,
        assurance_contract=assurance_contract,
        acceptance_criteria=acceptance_criteria,
        capsule=capsule,
        diff=diff,
        bounded_evidence=bounded_evidence,
    )
    if budget.contract_bytes > MAX_CONTRACT_BYTES:
        raise CloudflareB1Error("assurance contract exceeds bounded budget")
    if budget.diff_bytes > MAX_DIFF_BYTES:
        raise CloudflareB1Error("diff exceeds bounded Cloudflare budget")
    if budget.evidence_bytes > MAX_BOUNDED_EVIDENCE_BYTES:
        raise CloudflareB1Error("bounded evidence exceeds budget")
    if budget.pack_bytes > MAX_PACK_BYTES:
        raise CloudflareB1Error("semantic pack exceeds total bounded budget")

    return {
        "protocol_id": PROTOCOL_ID,
        "lineage_id": lineage_id(task_id=task_id, handover_id=handover_id, candidate_sha=candidate_sha),
        "task_id": task_id,
        "handover_id": handover_id,
        "candidate_sha": candidate_sha,
        "assurance_contract": assurance_contract,
        "acceptance_criteria": acceptance_criteria,
        "b0_capsule": capsule,
        "exact_diff": diff,
        "bounded_evidence": bounded_evidence,
    }


def build_messages(pack: dict[str, Any]) -> list[dict[str, str]]:
    if pack.get("protocol_id") != PROTOCOL_ID:
        raise CloudflareB1Error("unsupported semantic pack protocol")
    candidate_sha = pack.get("candidate_sha")
    if not isinstance(candidate_sha, str) or not _valid_sha(candidate_sha):
        raise CloudflareB1Error("semantic pack candidate is invalid")

    system = (
        "You are the independent governance_release_assurance B1 reviewer. "
        "Use only the supplied bounded evidence. Treat implementation narrative as non-evidence. "
        "Do not repair, merge, invent missing evidence, call tools, or request more context. "
        "Return exactly one JSON object and no markdown with exactly these keys: "
        "candidate_sha, verdict, summary, findings. "
        "verdict must be PASS, FAIL, or INDETERMINATE. "
        "PASS only when every acceptance criterion is supported, and for PASS findings MUST be exactly []. "
        "FAIL when supplied evidence proves a criterion is violated. "
        "INDETERMINATE when required evidence is missing or conflicting. "
        "For FAIL or INDETERMINATE findings MUST be a non-empty array of short plain strings."
    )
    user = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_verdict_response(api_response: dict[str, Any], *, candidate_sha: str) -> dict[str, Any]:
    if not _valid_sha(candidate_sha):
        raise CloudflareB1Error("candidate_sha is invalid")
    if not isinstance(api_response, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")

    choices = api_response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_OUTPUT_TRUNCATED")
    if finish_reason != "stop":
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")
    response = message.get("content")
    if not isinstance(response, str) or not response.strip():
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")

    raw = _unwrap_single_json_fence(response)
    try:
        payload = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except (ValueError, RecursionError) as exc:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_NON_JSON") from exc
    if not isinstance(payload, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_KEYS")

    required = {"candidate_sha", "verdict", "summary", "findings"}
    if set(payload) != required:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_KEYS")
    if payload["candidate_sha"] != candidate_sha:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_CANDIDATE_MISMATCH")
    verdict = payload["verdict"]
    if verdict not in VERDICTS:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_ENUM")
    summary = payload["summary"]
    findings = payload["findings"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_SUMMARY")
    if not isinstance(findings, list) or len(findings) > 20:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_FINDINGS")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in findings):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_FINDINGS")
    if verdict == "PASS" and findings:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_FINDINGS")
    if verdict in {"FAIL", "INDETERMINATE"} and not findings:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_FINDINGS")

    return {
        "candidate_sha": candidate_sha,
        "verdict": verdict,
        "summary": summary.strip(),
        "findings": findings,
    }


def run_workers_ai_once(
    *,
    account_id: str,
    api_token: str,
    messages: list[dict[str, str]],
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    seed: int = DEFAULT_SEED,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", account_id or ""):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_ACCOUNT")
    if not api_token or len(api_token) > 8192 or any(ord(ch) < 32 or ord(ch) == 127 for ch in api_token):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_CREDENTIAL")
    if not isinstance(messages, list) or len(messages) != 2:
        raise CloudflareB1Error("messages must contain exactly system and user entries")
    if not isinstance(timeout_seconds, int) or timeout_seconds < 1 or timeout_seconds > 300:
        raise CloudflareB1Error("timeout_seconds is outside the bounded range")
    if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 2048:
        raise CloudflareB1Error("max_tokens is outside the bounded range")

    endpoint = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
    body = _json_bytes(
        {
            "model": MODEL_ID,
            "messages": messages,
            "temperature": 0,
            "seed": seed,
            "max_tokens": max_tokens,
        }
    )
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
            "User-Agent": "market-predictions-control-engine/cloudflare-b1-v1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as exc:
        raise CloudflareB1ExecutionUnavailable(f"EXECUTION_UNAVAILABLE_CLOUDFLARE_HTTP_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, socket.timeout, http.client.HTTPException, ConnectionError, OSError) as exc:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_TRANSPORT") from exc

    if len(raw) > 1_000_000:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_TOO_LARGE")
    try:
        text = raw.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_reject_duplicate_json_keys)
    except (ValueError, RecursionError) as exc:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_UNPARSEABLE") from exc
    if not isinstance(payload, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")
    return payload
