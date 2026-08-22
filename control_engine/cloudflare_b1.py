from __future__ import annotations

import hashlib
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

_CONTROL_PLANE_SENSITIVE_PREFIXES = (
    "control/",
    "dispatcher/",
    "schemas/",
    "tools/control_",
)
_CONTROL_ENGINE_SENSITIVE_PREFIXES = (
    "control_engine/scheduled_worker_b.py",
    "control_engine/cloudflare_b1.py",
    "scripts/scheduled_worker_b",
    "scripts/cloudflare_b1",
    ".github/workflows/scheduled-worker-b",
    ".github/workflows/cloudflare-b1",
)


class CloudflareB1Error(ValueError):
    pass


class CloudflareB1ExecutionUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ExecutionSurfaceDecision:
    work_required: bool
    reasons: tuple[str, ...]

    @property
    def cloudflare_eligible(self) -> bool:
        return not self.work_required


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _valid_sha(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}", value))


def lineage_id(*, task_id: str, handover_id: str, candidate_sha: str) -> str:
    if not task_id or not handover_id or not _valid_sha(candidate_sha):
        raise CloudflareB1Error("lineage identity is incomplete or invalid")
    raw = f"{task_id}\n{handover_id}\n{candidate_sha}\n".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def classify_execution_surface(
    *,
    repository: str,
    changed_files: list[str],
    diff_bytes: int,
    explicit_work_required: bool = False,
    max_diff_bytes: int = MAX_DIFF_BYTES,
) -> ExecutionSurfaceDecision:
    if not isinstance(diff_bytes, int) or diff_bytes < 0:
        raise CloudflareB1Error("diff_bytes must be a non-negative integer")
    if not repository:
        raise CloudflareB1Error("repository is required")
    if any(not isinstance(path, str) or not path for path in changed_files):
        raise CloudflareB1Error("changed_files must contain non-empty paths")

    reasons: list[str] = []
    if explicit_work_required:
        reasons.append("EXPLICIT_WORK_REQUIRED")
    if diff_bytes > max_diff_bytes:
        reasons.append("DIFF_BUDGET_EXCEEDED")

    prefixes: tuple[str, ...] = ()
    if repository == CONTROL_PLANE_REPOSITORY:
        prefixes = _CONTROL_PLANE_SENSITIVE_PREFIXES
    elif repository == CONTROL_ENGINE_REPOSITORY:
        prefixes = _CONTROL_ENGINE_SENSITIVE_PREFIXES

    for path in sorted(set(changed_files)):
        if any(path.startswith(prefix) for prefix in prefixes):
            reasons.append(f"CONTROL_AUTHORITY_PATH:{path}")

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
    if len(assurance_contract.encode("utf-8")) > MAX_CONTRACT_BYTES:
        raise CloudflareB1Error("assurance contract exceeds bounded budget")
    if not isinstance(acceptance_criteria, list) or not acceptance_criteria:
        raise CloudflareB1Error("acceptance_criteria must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in acceptance_criteria):
        raise CloudflareB1Error("acceptance_criteria contains an invalid item")
    if not isinstance(capsule, dict):
        raise CloudflareB1Error("capsule must be an object")
    if capsule.get("authority", {}).get("semantic_verdict_present") is not False:
        raise CloudflareB1Error("capsule must be verdict-free")
    if capsule.get("task", {}).get("candidate_sha") != candidate_sha:
        raise CloudflareB1Error("capsule candidate does not match frozen candidate")
    if capsule.get("claim", {}).get("start_proven") is not True:
        raise CloudflareB1Error("START_PROVEN is required before semantic review")
    if capsule.get("deterministic_contradictions"):
        raise CloudflareB1Error("semantic Cloudflare path is forbidden with deterministic contradictions")
    if not isinstance(diff, str):
        raise CloudflareB1Error("diff must be text")
    if len(diff.encode("utf-8")) > MAX_DIFF_BYTES:
        raise CloudflareB1Error("diff exceeds bounded Cloudflare budget")
    evidence_bytes = _json_bytes(bounded_evidence)
    if len(evidence_bytes) > MAX_BOUNDED_EVIDENCE_BYTES:
        raise CloudflareB1Error("bounded evidence exceeds budget")

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
    if len(_json_bytes(pack)) > MAX_PACK_BYTES:
        raise CloudflareB1Error("semantic pack exceeds total bounded budget")
    return pack


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
        "PASS only when every acceptance criterion is supported. "
        "FAIL when supplied evidence proves a criterion is violated. "
        "INDETERMINATE when required evidence is missing or conflicting."
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
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")
    response = message.get("content")
    if not isinstance(response, str) or not response.strip():
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")

    raw = response.strip()
    if raw.startswith("```") or raw.endswith("```"):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT") from exc
    if not isinstance(payload, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")

    required = {"candidate_sha", "verdict", "summary", "findings"}
    if set(payload) != required:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")
    if payload["candidate_sha"] != candidate_sha:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_CANDIDATE_MISMATCH")
    verdict = payload["verdict"]
    if verdict not in VERDICTS:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")
    summary = payload["summary"]
    findings = payload["findings"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 2000:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")
    if not isinstance(findings, list) or len(findings) > 20:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")
    if any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in findings):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")
    if verdict in {"FAIL", "INDETERMINATE"} and not findings:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_MALFORMED_VERDICT")

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
    except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_TRANSPORT") from exc

    if len(raw) > 1_000_000:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_TOO_LARGE")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_UNPARSEABLE") from exc
    if not isinstance(payload, dict):
        raise CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT")
    return payload
