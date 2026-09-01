#!/usr/bin/env python3
"""Native Codex GitHub review binding for Control Autonomy V3.1.

This helper never writes canonical runtime/results itself. Canonical CLAIM, RECORD
and RELEASE remain delegated to scripts/control_kernel_v31.py, the single writer.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_engine import codex_v31
from control_engine import kernel_v31 as core
import scripts.control_kernel_v31 as kernel


class CodexBridgeError(RuntimeError):
    pass


def _runtime_queue(token: str) -> dict[str, Any]:
    path = urllib.parse.quote(kernel.QUEUE_REL, safe="/")
    doc = kernel._api(token, "GET", f"repos/{kernel.CONTROL_REPOSITORY}/contents/{path}?ref={kernel.RUNTIME_REF}")
    encoded = doc.get("content")
    if not isinstance(encoded, str):
        raise CodexBridgeError("canonical runtime queue content is unavailable")
    try:
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except Exception as exc:
        raise CodexBridgeError("canonical runtime queue content is invalid") from exc
    if payload.get("version") != "3.1":
        raise CodexBridgeError("canonical runtime queue is not V3.1")
    core.validate(payload)
    return payload


def _task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise CodexBridgeError("exact B1 task identity is absent or ambiguous")
    return matches[0]


def _queued_assurance(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    task = _task(queue, task_id)
    if task.get("operation") != "ASSURANCE" or task.get("role") != core.ROLE_B or task.get("status") != core.STATUS_QUEUED:
        raise CodexBridgeError("task is not a queued V3.1 B1 assurance")
    core._candidate(task.get("candidate"))
    return task


def _next_queued_b1(queue: dict[str, Any]) -> dict[str, Any] | None:
    selected = core.select_task(queue, core.ROLE_B)
    if selected is None:
        return None
    return _queued_assurance(queue, selected["task_id"])


def _active_b1(queue: dict[str, Any], task_id: str | None = None) -> dict[str, Any] | None:
    matches = [
        item
        for item in queue.get("tasks", [])
        if item.get("lifecycle_model") == core.PROTOCOL_ID
        and item.get("operation") == "ASSURANCE"
        and item.get("role") == core.ROLE_B
        and item.get("status") == core.STATUS_EXECUTING
        and isinstance(item.get("claim"), dict)
        and item["claim"].get("worker_instance") == core.INSTANCE_B1
        and (task_id is None or item.get("task_id") == task_id)
    ]
    if len(matches) > 1:
        raise CodexBridgeError("more than one active B1 run exists")
    return matches[0] if matches else None


def _verify_candidate(token: str, task: dict[str, Any]) -> dict[str, Any]:
    candidate = core._candidate(task.get("candidate"))
    repository = task["repository"]
    pr = kernel._api(token, "GET", f"repos/{repository}/pulls/{candidate['candidate_pr_number']}")
    head = pr.get("head", {})
    base = pr.get("base", {})
    if (
        pr.get("state") != "open"
        or head.get("sha") != candidate["candidate_sha"]
        or head.get("ref") != candidate["candidate_head_branch"]
        or base.get("ref") != candidate["expected_base_branch"]
        or base.get("sha") != candidate["expected_base_sha"]
    ):
        raise CodexBridgeError("live PR no longer matches the frozen candidate envelope")
    return candidate


def _paged(token: str, path: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for page in range(1, 11):
        separator = "&" if "?" in path else "?"
        batch = kernel._api(token, "GET", f"{path}{separator}per_page=100&page={page}")
        if not isinstance(batch, list):
            raise CodexBridgeError("GitHub evidence collection is malformed")
        output.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < 100:
            return output
    raise CodexBridgeError("GitHub evidence collection exceeds bounded pagination")


def _request_matches(item: dict[str, Any], *, task_id: str, run_id: str, candidate_sha: str) -> bool:
    parsed = codex_v31.parse_request(item.get("body"))
    if parsed is None:
        return False
    return parsed == (
        codex_v31.request_id(task_id=task_id, run_id=run_id, candidate_sha=candidate_sha),
        task_id,
        run_id,
        candidate_sha,
    )


def command_plan_next(runtime_token: str) -> int:
    task = _next_queued_b1(_runtime_queue(runtime_token))
    if task is None:
        print("CONTROL_CODEX_NEXT=NONE")
        print("CONTROL_CODEX_TASK_ID=")
        print("CONTROL_CODEX_TARGET_REPOSITORY=")
        return 0
    print("CONTROL_CODEX_NEXT=QUEUED_ASSURANCE")
    print(f"CONTROL_CODEX_TASK_ID={task['task_id']}")
    print(f"CONTROL_CODEX_TARGET_REPOSITORY={task['repository']}")
    return 0


def command_plan_active(runtime_token: str) -> int:
    task = _active_b1(_runtime_queue(runtime_token))
    if task is None:
        print("CONTROL_CODEX_ACTIVE=NONE")
        print("CONTROL_CODEX_TASK_ID=")
        print("CONTROL_CODEX_TARGET_REPOSITORY=")
        return 0
    print("CONTROL_CODEX_ACTIVE=FOUND")
    print(f"CONTROL_CODEX_TASK_ID={task['task_id']}")
    print(f"CONTROL_CODEX_TARGET_REPOSITORY={task['repository']}")
    return 0


def command_start(runtime_token: str, target_token: str, *, task_id: str) -> int:
    _queued_assurance(_runtime_queue(runtime_token), task_id)
    kernel.command_claim(
        runtime_token,
        role=core.ROLE_B,
        worker=core.INSTANCE_B1,
        task_id=task_id,
    )
    queue = _runtime_queue(runtime_token)
    task = _active_b1(queue, task_id)
    if task is None:
        raise CodexBridgeError("B1 START_PROVEN readback failed")
    claim = task["claim"]
    run_id = claim["run_id"]
    try:
        candidate = _verify_candidate(target_token, task)
        body = codex_v31.build_request(
            task_id=task_id,
            run_id=run_id,
            candidate_sha=candidate["candidate_sha"],
            acceptance=task.get("acceptance", []),
        )
        response = kernel._api(
            target_token,
            "POST",
            f"repos/{task['repository']}/issues/{candidate['candidate_pr_number']}/comments",
            {"body": body},
        )
        comment_id = response.get("id")
        if not isinstance(comment_id, int):
            raise CodexBridgeError("Codex request comment was not durably created")
    except Exception:
        kernel.command_release(
            runtime_token,
            role=core.ROLE_B,
            worker=core.INSTANCE_B1,
            task_id=task_id,
            run_id=run_id,
            reason="EXECUTION_UNAVAILABLE",
        )
        raise
    print("CONTROL_CODEX_START=START_PROVEN")
    print(f"CONTROL_CODEX_TASK_ID={task_id}")
    print(f"CONTROL_CODEX_RUN_ID={run_id}")
    print(f"CONTROL_CODEX_REQUEST_COMMENT_ID={comment_id}")
    return 0


def command_reconcile(runtime_token: str, target_token: str, *, task_id: str) -> int:
    queue = _runtime_queue(runtime_token)
    task = _active_b1(queue, task_id)
    if task is None:
        print("CONTROL_CODEX_RECONCILE=NO_ACTIVE_B1")
        return 0
    claim = task["claim"]
    run_id = claim["run_id"]
    expires_at = datetime.fromisoformat(claim["expires_at"].replace("Z", "+00:00")).astimezone(timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        print("CONTROL_CODEX_RECONCILE=LEASE_EXPIRED_PENDING_TICK")
        return 0

    try:
        candidate = _verify_candidate(target_token, task)
        repository = task["repository"]
        pr_number = candidate["candidate_pr_number"]
        issue_comments = _paged(target_token, f"repos/{repository}/issues/{pr_number}/comments")
        requests = [
            item
            for item in issue_comments
            if _request_matches(item, task_id=task_id, run_id=run_id, candidate_sha=candidate["candidate_sha"])
        ]
        if len(requests) != 1:
            raise CodexBridgeError("exact Codex request is absent or ambiguous")
        reviews = _paged(target_token, f"repos/{repository}/pulls/{pr_number}/reviews")
        review_comments = _paged(target_token, f"repos/{repository}/pulls/{pr_number}/comments")
        decision = codex_v31.classify(
            task_id=task_id,
            run_id=run_id,
            candidate_sha=candidate["candidate_sha"],
            request=requests[0],
            issue_comments=issue_comments,
            reviews=reviews,
            review_comments=review_comments,
        )
    except Exception:
        kernel.command_release(
            runtime_token,
            role=core.ROLE_B,
            worker=core.INSTANCE_B1,
            task_id=task_id,
            run_id=run_id,
            reason="EXECUTION_UNAVAILABLE",
        )
        raise

    if decision.status == "PENDING":
        print("CONTROL_CODEX_RECONCILE=PENDING")
        return 0
    if decision.status == "EXECUTION_UNAVAILABLE":
        kernel.command_release(
            runtime_token,
            role=core.ROLE_B,
            worker=core.INSTANCE_B1,
            task_id=task_id,
            run_id=run_id,
            reason="EXECUTION_UNAVAILABLE",
        )
        print("CONTROL_CODEX_RECONCILE=RELEASED")
        return 0
    if decision.status != "COMPLETE" or decision.verdict not in {"PASS", "FAIL", "INDETERMINATE"}:
        raise CodexBridgeError("Codex decision is not terminal and valid")

    payload = {
        "outcome": decision.verdict,
        "role": core.ROLE_B,
        "task_id": task_id,
        "run_id": run_id,
        "candidate": candidate,
        "executor": "CODEX_GITHUB_REVIEW",
        "summary": decision.summary,
        "findings": list(decision.findings),
    }
    kernel.command_record(
        runtime_token,
        role=core.ROLE_B,
        worker=core.INSTANCE_B1,
        task_id=task_id,
        run_id=run_id,
        payload=payload,
    )
    print(f"CONTROL_CODEX_RECONCILE={decision.verdict}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control V3.1 native Codex B1 binding")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan-next")
    sub.add_parser("plan-active")
    start = sub.add_parser("start")
    start.add_argument("--task-id", required=True)
    reconcile = sub.add_parser("reconcile")
    reconcile.add_argument("--task-id", required=True)
    return parser


def main() -> int:
    runtime_token = __import__("os").environ.get("CONTROL_RUNTIME_TOKEN", "")
    target_token = __import__("os").environ.get("CONTROL_TARGET_TOKEN", "")
    if not runtime_token:
        print("CONTROL_CODEX=NO_RUNTIME_TOKEN")
        return 78
    args = build_parser().parse_args()
    try:
        if args.command == "plan-next":
            return command_plan_next(runtime_token)
        if args.command == "plan-active":
            return command_plan_active(runtime_token)
        if not target_token:
            raise CodexBridgeError("target repository token is required")
        if args.command == "start":
            return command_start(runtime_token, target_token, task_id=args.task_id)
        if args.command == "reconcile":
            return command_reconcile(runtime_token, target_token, task_id=args.task_id)
        raise CodexBridgeError("unsupported Codex command")
    except Exception as exc:
        print(f"CONTROL_CODEX=FAILED:{type(exc).__name__}:{str(exc)[-800:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
