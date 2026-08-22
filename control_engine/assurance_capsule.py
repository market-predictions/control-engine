from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

PROTOCOL_ID = "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1"
VERSION = "1.0"
ASSURANCE_ROLE = "governance_release_assurance"
ASSURANCE_WORKER = "B1"


class CapsuleError(ValueError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in queue.get("tasks", []) if isinstance(item, dict) and item.get("task_id") == task_id]
    if len(matches) != 1:
        raise CapsuleError(f"expected exactly one task {task_id!r}, found {len(matches)}")
    return matches[0]


def _digest_json(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(raw)


def _claim(task: dict[str, Any], observed_at: datetime | None) -> dict[str, Any]:
    started = _parse_ts(task.get("claim_started_at"))
    expires = _parse_ts(task.get("claim_expires_at"))
    identity_ok = (
        task.get("state") == "ASSURANCE_EXECUTING"
        and task.get("active_role") == ASSURANCE_ROLE
        and task.get("active_worker_instance") == ASSURANCE_WORKER
        and isinstance(task.get("active_run_id"), str)
        and bool(task.get("active_run_id"))
        and task.get("resume_state") == "ASSURANCE_QUEUED"
        and started is not None
        and expires is not None
        and started < expires
    )
    lease_current = None
    if observed_at is not None and started is not None and expires is not None:
        lease_current = started <= observed_at < expires
    return {
        "state": task.get("state"),
        "active_run_id": task.get("active_run_id"),
        "active_role": task.get("active_role"),
        "active_worker_instance": task.get("active_worker_instance"),
        "claim_started_at": task.get("claim_started_at"),
        "claim_expires_at": task.get("claim_expires_at"),
        "lease_current_at_observation": lease_current,
        "start_proven": bool(identity_ok and lease_current is not False),
    }


def _pr(pr: dict[str, Any] | None) -> dict[str, Any] | None:
    if pr is None:
        return None
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
    return {
        "number": pr.get("number"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "merged": pr.get("merged"),
        "head_sha": head.get("sha"),
        "base_ref": base.get("ref"),
        "base_sha": base.get("sha"),
    }


def _runs(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    raw = payload.get("workflow_runs", []) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise CapsuleError("workflow runs must be an array")
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        result.append({key: item.get(key) for key in ("id", "name", "status", "conclusion", "head_sha", "event", "path")})
    return sorted(result, key=lambda item: (str(item.get("name") or ""), int(item.get("id") or 0)))


def build_capsule(
    *,
    queue_raw: bytes,
    task_id: str,
    pr_raw: bytes = b"",
    workflow_runs_raw: bytes = b"",
    changed_files_raw: bytes = b"",
    diff_raw: bytes = b"",
    observed_at: str | None = None,
) -> dict[str, Any]:
    try:
        queue = json.loads(queue_raw)
    except Exception as exc:
        raise CapsuleError("queue is not valid JSON") from exc
    if not isinstance(queue, dict):
        raise CapsuleError("queue must be an object")
    task = _task(queue, task_id)

    observed = _parse_ts(observed_at) if observed_at else None
    if observed_at and observed is None:
        raise CapsuleError("observed_at must be timezone-aware ISO-8601")

    def load_optional(raw: bytes, label: str) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception as exc:
            raise CapsuleError(f"{label} is not valid JSON") from exc

    pr_summary = _pr(load_optional(pr_raw, "PR evidence"))
    runs = _runs(load_optional(workflow_runs_raw, "workflow evidence"))
    claim = _claim(task, observed)
    changed_files = sorted({line.strip() for line in changed_files_raw.decode().splitlines() if line.strip()})
    candidate = task.get("candidate_sha")

    contradictions: list[str] = []
    if task.get("operation") != "ASSURANCE":
        contradictions.append("TASK_OPERATION_NOT_ASSURANCE")
    if not isinstance(candidate, str) or len(candidate) != 40:
        contradictions.append("FROZEN_CANDIDATE_SHA_MISSING_OR_INVALID")
    if not claim["start_proven"]:
        contradictions.append("ASSURANCE_START_NOT_PROVEN")
    if task.get("candidate_pr") is not None:
        if pr_summary is None:
            contradictions.append("PR_EVIDENCE_MISSING")
        else:
            if pr_summary["number"] != task.get("candidate_pr"):
                contradictions.append("PR_NUMBER_MISMATCH")
            if pr_summary["state"] != "open" or pr_summary["merged"] is True:
                contradictions.append("PR_NOT_OPEN")
            if pr_summary["head_sha"] != candidate:
                contradictions.append("PR_HEAD_MOVED")
            if task.get("target_branch") and pr_summary["base_ref"] != task.get("target_branch"):
                contradictions.append("PR_BASE_BRANCH_MISMATCH")
    for run in runs:
        if run.get("head_sha") and candidate and run.get("head_sha") != candidate:
            contradictions.append(f"WORKFLOW_RUN_HEAD_MISMATCH:{run.get('id')}")

    exact_runs = [run for run in runs if run.get("head_sha") == candidate]
    raw_bytes = sum(len(raw) for raw in (queue_raw, pr_raw, workflow_runs_raw, changed_files_raw, diff_raw))
    capsule: dict[str, Any] = {
        "protocol_id": PROTOCOL_ID,
        "version": VERSION,
        "observed_at": observed_at,
        "authority": {
            "logical_role": ASSURANCE_ROLE,
            "worker_instance": ASSURANCE_WORKER,
            "semantic_verdict_present": False,
            "merge_authority": False,
            "release_authority": False,
        },
        "task": {
            "task_id": task.get("task_id"),
            "repository": task.get("repository"),
            "operation": task.get("operation"),
            "intake_revision": task.get("intake_revision"),
            "handover_id": task.get("handover_id"),
            "candidate_pr": task.get("candidate_pr"),
            "candidate_sha": candidate,
            "target_branch": task.get("target_branch"),
            "instruction_sha256": _digest_json(task.get("instruction")),
            "acceptance_criteria_sha256": _digest_json(task.get("acceptance_criteria")),
            "principal_manual_relay_count": task.get("principal_manual_relay_count"),
        },
        "claim": claim,
        "pull_request": pr_summary,
        "ci": {
            "runs": runs,
            "exact_candidate_run_count": len(exact_runs),
            "exact_candidate_success_count": sum(run.get("conclusion") == "success" for run in exact_runs),
        },
        "changed_files": changed_files,
        "diff": {"sha256": _sha256(diff_raw) if diff_raw else None, "bytes": len(diff_raw), "content_embedded": False},
        "deterministic_contradictions": sorted(set(contradictions)),
        "source_digests": {
            "queue_sha256": _sha256(queue_raw),
            "pr_json_sha256": _sha256(pr_raw) if pr_raw else None,
            "workflow_runs_json_sha256": _sha256(workflow_runs_raw) if workflow_runs_raw else None,
            "changed_files_sha256": _sha256(changed_files_raw) if changed_files_raw else None,
            "diff_sha256": _sha256(diff_raw) if diff_raw else None,
        },
        "evidence_metrics": {"raw_evidence_bytes": raw_bytes, "capsule_bytes": 0, "observed_byte_reduction_percent": 0.0},
    }
    for _ in range(8):
        rendered = (json.dumps(capsule, sort_keys=True, separators=(",", ":")) + "\n").encode()
        size = len(rendered)
        reduction = round(max(0.0, 100 * (1 - size / raw_bytes)), 1) if raw_bytes else 0.0
        old = capsule["evidence_metrics"]["capsule_bytes"]
        capsule["evidence_metrics"]["capsule_bytes"] = size
        capsule["evidence_metrics"]["observed_byte_reduction_percent"] = reduction
        if old == size:
            break
    return capsule
