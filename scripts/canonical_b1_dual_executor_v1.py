#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.request

from control_engine.cloudflare_b1 import (
    B0_PROTOCOL_ID,
    B0_VERSION,
    MODEL_ID,
    CloudflareB1Error,
    CloudflareB1ExecutionUnavailable,
    build_messages,
    build_semantic_pack,
    classify_execution_surface,
    measure_semantic_budget,
    parse_verdict_response,
    run_workers_ai_once,
)
from control_engine.codex_b1 import CodexB1Error, build_review_request
from control_engine.codex_b1_strict import classify_trusted_review_snapshot

PROFILE_ID = "CONTROL_ASSURANCE_EXECUTION_PROFILE_V1"
ROLE = "governance_release_assurance"
WORKER = "B1"
PROVENANCE_ID = "CONTROL_STANDARD_EXECUTOR_PROVENANCE_V1"


class CanonicalB1Error(RuntimeError):
    pass


def _load(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise CanonicalB1Error("timestamp missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise CanonicalB1Error("timestamp lacks timezone")
    return parsed.astimezone(timezone.utc)


def _task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise CanonicalB1Error("expected exactly one canonical task")
    return matches[0]


def _profile(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("protocol_id") != PROFILE_ID or profile.get("version") != "1.0":
        raise CanonicalB1Error("unsupported assurance execution profile")
    if profile.get("status") != "ACTIVE":
        raise CanonicalB1Error("assurance execution profile is not ACTIVE")
    authority = profile.get("lifecycle_authority")
    if not isinstance(authority, dict):
        raise CanonicalB1Error("profile lifecycle authority missing")
    if authority.get("role") != ROLE or authority.get("worker_instance") != WORKER or authority.get("capacity") != 1:
        raise CanonicalB1Error("profile B1 authority mismatch")
    standard = profile.get("standard")
    deep = profile.get("deep")
    if not isinstance(standard, dict) or not isinstance(deep, dict):
        raise CanonicalB1Error("profile executors missing")
    if standard.get("model") != MODEL_ID or standard.get("semantic_calls_per_run") != 1:
        raise CanonicalB1Error("profile STANDARD model/call contract mismatch")
    if any(standard.get(key) is not False for key in ("tools_enabled", "automatic_retry", "provider_fallback", "model_fallback", "paid_fallback")):
        raise CanonicalB1Error("profile STANDARD forbidden fallback/tool setting")
    max_tokens = standard.get("max_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not (1 <= max_tokens <= 2048):
        raise CanonicalB1Error("profile STANDARD max_tokens invalid")
    trusted = deep.get("trusted_connector_logins")
    if not isinstance(trusted, list) or sorted(trusted) != sorted(["chatgpt-codex-connector", "chatgpt-codex-connector[bot]"]):
        raise CanonicalB1Error("profile DEEP trusted connector set mismatch")
    if deep.get("review_only") is not True or deep.get("exact_head_required") is not True:
        raise CanonicalB1Error("profile DEEP review boundary mismatch")
    if profile.get("principal_manual_relay_count") != 0:
        raise CanonicalB1Error("profile principal relay invariant violated")
    return profile


def _validate_claim(queue: dict[str, Any], task_id: str, run_id: str, candidate_sha: str) -> dict[str, Any]:
    task = _task(queue, task_id)
    if task.get("state") != "ASSURANCE_EXECUTING":
        raise CanonicalB1Error("START_PROVEN state mismatch")
    if task.get("active_role") != ROLE or task.get("active_worker_instance") != WORKER:
        raise CanonicalB1Error("START_PROVEN role/worker mismatch")
    if task.get("active_run_id") != run_id:
        raise CanonicalB1Error("START_PROVEN run mismatch")
    if task.get("candidate_sha") != candidate_sha:
        raise CanonicalB1Error("START_PROVEN candidate mismatch")
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise CanonicalB1Error("principal relay invariant violated")
    started = _parse_ts(task.get("claim_started_at"))
    expires = _parse_ts(task.get("claim_expires_at"))
    now = datetime.now(timezone.utc)
    if not (started <= now < expires):
        raise CanonicalB1Error("START_PROVEN lease is not current")
    if not isinstance(task.get("handover_id"), str) or not task.get("handover_id"):
        raise CanonicalB1Error("handover identity missing")
    criteria = task.get("acceptance_criteria")
    if not isinstance(criteria, list) or not criteria or any(not isinstance(item, str) or not item.strip() for item in criteria):
        raise CanonicalB1Error("acceptance criteria invalid")
    return task


def _pr_binding(pr: dict[str, Any], task: dict[str, Any], candidate_sha: str) -> tuple[int, str]:
    number = task.get("candidate_pr")
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise CanonicalB1Error("canonical dual executor requires candidate_pr")
    if pr.get("number") != number:
        raise CanonicalB1Error("PR number mismatch")
    head = pr.get("head")
    base = pr.get("base")
    if not isinstance(head, dict) or head.get("sha") != candidate_sha:
        raise CanonicalB1Error("PR head moved from frozen candidate")
    if not isinstance(base, dict) or not isinstance(base.get("sha"), str):
        raise CanonicalB1Error("PR base evidence missing")
    if pr.get("state") != "open" or pr.get("merged") is True:
        raise CanonicalB1Error("PR is not open/unmerged")
    return number, base["sha"]


def _changed_files(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise CanonicalB1Error("changed-file evidence must be a list")
    paths: list[str] = []
    for item in value:
        if isinstance(item, str):
            path = item
        elif isinstance(item, dict):
            path = item.get("filename")
        else:
            path = None
        if not isinstance(path, str) or not path:
            raise CanonicalB1Error("changed-file path invalid")
        paths.append(path)
    normalized = sorted(set(paths))
    if len(normalized) != len(paths):
        raise CanonicalB1Error("changed-file evidence contains duplicates")
    return normalized


def _workflow_summary(value: Any, candidate_sha: str) -> list[dict[str, Any]]:
    runs = value.get("workflow_runs") if isinstance(value, dict) else None
    if not isinstance(runs, list):
        return []
    result: list[dict[str, Any]] = []
    for item in runs[:20]:
        if not isinstance(item, dict) or item.get("head_sha") != candidate_sha:
            continue
        result.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "event": item.get("event"),
            "status": item.get("status"),
            "conclusion": item.get("conclusion"),
            "head_sha": item.get("head_sha"),
        })
    return result


def _b0(
    *,
    queue: dict[str, Any],
    task: dict[str, Any],
    run_id: str,
    candidate_sha: str,
    changed_files: list[str],
    diff: str,
) -> dict[str, Any]:
    criteria = task["acceptance_criteria"]
    diff_raw = diff.encode("utf-8")
    acceptance_digest = _sha256_bytes(_json_bytes(criteria))
    diff_digest = _sha256_bytes(diff_raw)
    return {
        "protocol_id": B0_PROTOCOL_ID,
        "version": B0_VERSION,
        "authority": {
            "logical_role": ROLE,
            "worker_instance": WORKER,
            "semantic_verdict_present": False,
            "merge_authority": False,
            "release_authority": False,
        },
        "task": {
            "task_id": task["task_id"],
            "handover_id": task["handover_id"],
            "candidate_sha": candidate_sha,
            "repository": task["repository"],
            "acceptance_criteria_sha256": acceptance_digest,
        },
        "claim": {
            "state": task["state"],
            "active_run_id": run_id,
            "active_role": task["active_role"],
            "active_worker_instance": task["active_worker_instance"],
            "claim_started_at": task["claim_started_at"],
            "claim_expires_at": task["claim_expires_at"],
            "lease_current_at_observation": True,
            "start_proven": True,
        },
        "changed_files": changed_files,
        "diff": {
            "sha256": diff_digest,
            "bytes": len(diff_raw),
            "content_embedded": False,
        },
        "source_digests": {
            "diff_sha256": diff_digest,
            "acceptance_criteria_sha256": acceptance_digest,
        },
        "deterministic_contradictions": [],
    }


def _bounded_evidence(
    *,
    pr: dict[str, Any],
    task: dict[str, Any],
    candidate_sha: str,
    base_sha: str,
    changed_files: list[str],
    workflows: Any,
    profile: dict[str, Any],
) -> dict[str, Any]:
    standard = profile["standard"]
    return {
        "pr": {
            "number": task["candidate_pr"],
            "state": pr.get("state"),
            "merged": pr.get("merged"),
            "draft": pr.get("draft"),
            "head_sha": candidate_sha,
            "base_sha": base_sha,
        },
        "changed_files": changed_files,
        "workflow_runs": _workflow_summary(workflows, candidate_sha),
        "canonical_task_policy": {
            "merge_policy": task.get("merge_policy"),
            "project_integration_authorized": task.get("project_integration_authorized"),
            "principal_manual_relay_count": task.get("principal_manual_relay_count"),
        },
        "standard_execution_contract": {
            "executor": standard["executor"],
            "model": standard["model"],
            "endpoint_class": standard["endpoint_class"],
            "max_tokens": standard["max_tokens"],
            "tools_enabled": standard["tools_enabled"],
            "semantic_calls_per_run": standard["semantic_calls_per_run"],
            "automatic_retry": standard["automatic_retry"],
            "provider_fallback": standard["provider_fallback"],
            "model_fallback": standard["model_fallback"],
            "paid_fallback": standard["paid_fallback"],
        },
    }


def _result(
    *,
    task_id: str,
    run_id: str,
    candidate_sha: str,
    outcome: str,
    summary: str,
    findings: list[str],
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "version": "1.0",
        "task_id": task_id,
        "run_id": run_id,
        "role": ROLE,
        "outcome": outcome,
        "summary": summary,
        "candidate_sha": candidate_sha,
        "findings": findings,
        "evidence": evidence,
    }


def _unavailable(task_id: str, run_id: str, candidate_sha: str, code: str) -> dict[str, Any]:
    return _result(
        task_id=task_id,
        run_id=run_id,
        candidate_sha=candidate_sha,
        outcome="EXECUTION_UNAVAILABLE",
        summary="Canonical B1 execution failed closed before an authoritative semantic verdict could be persisted.",
        findings=[code],
        evidence=["Infrastructure, binding or executor evidence was unavailable or invalid; no semantic verdict was fabricated."],
    )


def _gh_json(token: str, method: str, path: str, payload: dict[str, Any] | None = None, accept: str | None = None) -> Any:
    url = f"https://api.github.com{path}"
    data = None if payload is None else _json_bytes(payload)
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "market-predictions-control-engine/canonical-b1-dual-executor-v1",
        "Accept": accept or "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2_000_001)
    except urllib.error.HTTPError as exc:
        raise CanonicalB1Error(f"GitHub API HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CanonicalB1Error("GitHub API transport failure") from exc
    if len(raw) > 2_000_000:
        raise CanonicalB1Error("GitHub API response too large")
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _standard(
    *,
    task: dict[str, Any],
    run_id: str,
    candidate_sha: str,
    capsule: dict[str, Any],
    diff: str,
    evidence: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    pack = build_semantic_pack(
        task_id=task["task_id"],
        handover_id=task["handover_id"],
        candidate_sha=candidate_sha,
        assurance_contract=task["instruction"],
        acceptance_criteria=task["acceptance_criteria"],
        capsule=capsule,
        diff=diff,
        bounded_evidence=evidence,
    )
    call_count = 0
    call_count += 1
    if call_count != 1:
        raise CanonicalB1Error("STANDARD call count invariant violated")
    response = run_workers_ai_once(
        account_id=os.environ.get("CONTROL_CLOUDFLARE_ACCOUNT_ID", ""),
        api_token=os.environ.get("CONTROL_CLOUDFLARE_API_TOKEN", ""),
        messages=build_messages(pack),
        max_tokens=profile["standard"]["max_tokens"],
    )
    verdict = parse_verdict_response(response, candidate_sha=candidate_sha)
    provenance = {
        "protocol_id": PROVENANCE_ID,
        "call_count": call_count,
        "executor": MODEL_ID,
        "max_tokens": profile["standard"]["max_tokens"],
        "tools_enabled": False,
        "retry_count": 0,
        "provider_switches": 0,
        "model_switches": 0,
        "paid_fallback": False,
        "response_received": True,
    }
    response_id = response.get("id") if isinstance(response, dict) else None
    if isinstance(response_id, str) and response_id:
        provenance["response_id"] = response_id
    return _result(
        task_id=task["task_id"],
        run_id=run_id,
        candidate_sha=candidate_sha,
        outcome=verdict["verdict"],
        summary=verdict["summary"],
        findings=list(verdict["findings"]),
        evidence=[
            "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1: START_PROVEN=true; deterministic_contradictions=[]",
            f"route=STANDARD; model={MODEL_ID}; one bounded no-tools call",
            f"{PROVENANCE_ID}:{json.dumps(provenance, sort_keys=True, separators=(',', ':'))}",
        ],
    )


def _deep(
    *,
    task: dict[str, Any],
    run_id: str,
    candidate_sha: str,
    repository: str,
    pr_number: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        raise CanonicalB1Error("DEEP GitHub actuator credential missing")
    body = build_review_request(
        task_id=task["task_id"],
        handover_id=task["handover_id"],
        candidate_sha=candidate_sha,
        acceptance_criteria=task["acceptance_criteria"],
    )
    created = _gh_json(token, "POST", f"/repos/{repository}/issues/{pr_number}/comments", {"body": body})
    if not isinstance(created, dict) or not isinstance(created.get("id"), int):
        raise CanonicalB1Error("DEEP request comment creation failed")
    comment_id = created["id"]
    user = created.get("user")
    actuator_login = user.get("login") if isinstance(user, dict) else None
    if not isinstance(actuator_login, str) or not actuator_login:
        raise CanonicalB1Error("DEEP trusted actuator login missing")

    deadline = time.monotonic() + timeout_seconds
    last_summary = "No terminal Codex review evidence is present yet for the current request."
    while time.monotonic() < deadline:
        reviews = _gh_json(token, "GET", f"/repos/{repository}/pulls/{pr_number}/reviews?per_page=100")
        review_comments = _gh_json(token, "GET", f"/repos/{repository}/pulls/{pr_number}/comments?per_page=100")
        reactions = _gh_json(
            token,
            "GET",
            f"/repos/{repository}/issues/comments/{comment_id}/reactions?per_page=100",
            accept="application/vnd.github+json",
        )
        issue_comments = _gh_json(token, "GET", f"/repos/{repository}/issues/{pr_number}/comments?per_page=100")
        decision = classify_trusted_review_snapshot(
            task_id=task["task_id"],
            handover_id=task["handover_id"],
            candidate_sha=candidate_sha,
            request_comment_id=comment_id,
            acceptance_criteria=task["acceptance_criteria"],
            trusted_actuator_login=actuator_login,
            reviews=reviews if isinstance(reviews, list) else [],
            review_comments=review_comments if isinstance(review_comments, list) else [],
            trigger_reactions=reactions if isinstance(reactions, list) else [],
            issue_comments=issue_comments if isinstance(issue_comments, list) else [],
        )
        last_summary = decision.summary
        if decision.status == "COMPLETE" and decision.verdict is not None:
            return _result(
                task_id=task["task_id"],
                run_id=run_id,
                candidate_sha=candidate_sha,
                outcome=decision.verdict,
                summary=decision.summary,
                findings=list(decision.findings),
                evidence=[
                    "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1: START_PROVEN=true; deterministic_contradictions=[]",
                    f"route=DEEP; request_comment_id={comment_id}; trusted_actuator_login={actuator_login}",
                    f"reviewed_commit={decision.reviewed_commit or ''}",
                ],
            )
        if decision.status == "EXECUTION_UNAVAILABLE":
            raise CanonicalB1Error(decision.summary)
        time.sleep(15)
    raise CanonicalB1Error(f"DEEP terminal evidence timeout: {last_summary}")


def run(args: argparse.Namespace) -> dict[str, Any]:
    profile = _profile(_load(args.profile))
    queue = _load(args.queue)
    task = _validate_claim(queue, args.task_id, args.run_id, args.candidate_sha)
    if task.get("repository") != args.repository:
        raise CanonicalB1Error("repository differs from canonical task")
    pr = _load(args.pr_json)
    pr_number, base_sha = _pr_binding(pr, task, args.candidate_sha)
    changed_files = _changed_files(_load(args.changed_files_json))
    diff = Path(args.diff).read_text(encoding="utf-8")
    workflows = _load(args.workflow_runs)
    capsule = _b0(
        queue=queue,
        task=task,
        run_id=args.run_id,
        candidate_sha=args.candidate_sha,
        changed_files=changed_files,
        diff=diff,
    )
    bounded = _bounded_evidence(
        pr=pr,
        task=task,
        candidate_sha=args.candidate_sha,
        base_sha=base_sha,
        changed_files=changed_files,
        workflows=workflows,
        profile=profile,
    )
    budget = measure_semantic_budget(
        task_id=task["task_id"],
        handover_id=task["handover_id"],
        candidate_sha=args.candidate_sha,
        assurance_contract=task["instruction"],
        acceptance_criteria=task["acceptance_criteria"],
        capsule=capsule,
        diff=diff,
        bounded_evidence=bounded,
    )
    explicit_deep = "CONTROL_ASSURANCE_CLASS=DEEP" in task.get("instruction", "")
    route = classify_execution_surface(
        repository=args.repository,
        changed_files=changed_files,
        budget=budget,
        capsule=capsule,
        explicit_work_required=explicit_deep,
    )
    if route.cloudflare_eligible:
        return _standard(
            task=task,
            run_id=args.run_id,
            candidate_sha=args.candidate_sha,
            capsule=capsule,
            diff=diff,
            evidence=bounded,
            profile=profile,
        )
    return _deep(
        task=task,
        run_id=args.run_id,
        candidate_sha=args.candidate_sha,
        repository=args.repository,
        pr_number=pr_number,
        timeout_seconds=args.deep_timeout_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Canonical GitHub-owned single-role dual-executor B1 semantic runner")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--queue", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--pr-json", required=True)
    parser.add_argument("--changed-files-json", required=True)
    parser.add_argument("--workflow-runs", required=True)
    parser.add_argument("--diff", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--deep-timeout-seconds", type=int, default=480)
    args = parser.parse_args()
    try:
        result = run(args)
    except (CanonicalB1Error, CloudflareB1Error, CloudflareB1ExecutionUnavailable, CodexB1Error, ValueError, OSError, json.JSONDecodeError) as exc:
        code = getattr(exc, "code", None) or f"EXECUTION_UNAVAILABLE_{type(exc).__name__.upper()}"
        result = _unavailable(args.task_id, args.run_id, args.candidate_sha, str(code))
    _write(args.output, result)
    print(f"CANONICAL_B1_OUTCOME={result['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
