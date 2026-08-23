from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from control_engine.assurance_capsule import build_capsule
from control_engine.cloudflare_b1 import (
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

ROLE = "governance_release_assurance"


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True)
    parser.add_argument("--diff", required=True)
    parser.add_argument("--changed-files", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--candidate-branch", required=True)
    parser.add_argument("--active-run-id", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--actual-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    queue_raw = Path(args.queue).read_bytes()
    queue = json.loads(queue_raw)
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == args.task_id]
    if len(matches) != 1:
        raise SystemExit("canonical canary task identity mismatch")
    task = matches[0]
    if task.get("candidate_sha") != args.candidate_sha:
        raise SystemExit("canonical canary candidate mismatch")
    if task.get("active_run_id") != args.active_run_id:
        raise SystemExit("canonical canary run mismatch")
    if task.get("principal_manual_relay_count") != 0 or queue.get("principal_manual_relay_count") != 0:
        raise SystemExit("principal relay count changed")

    changed_files = [line for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines() if line]
    changed_raw = (("\n".join(changed_files) + "\n") if changed_files else "").encode("utf-8")
    diff_raw = Path(args.diff).read_bytes()
    actual_file = Path(args.actual_file).read_bytes()
    expected_file = b"CONTROL_B1_GATE6_CANARY=PASS\n"
    if actual_file != expected_file:
        raise SystemExit("canary file bytes mismatch")

    capsule = build_capsule(
        queue_raw=queue_raw,
        task_id=args.task_id,
        changed_files_raw=changed_raw,
        diff_raw=diff_raw,
        observed_at=args.observed_at,
    )
    if capsule.get("deterministic_contradictions") != []:
        raise SystemExit("B0 deterministic contradiction")
    if capsule.get("claim", {}).get("start_proven") is not True:
        raise SystemExit("START_PROVEN is not true in B0 capsule")

    acceptance = task.get("acceptance_criteria")
    instruction = task.get("instruction")
    if not isinstance(acceptance, list) or not acceptance or not isinstance(instruction, str) or not instruction:
        raise SystemExit("canary contract is incomplete")

    bounded_evidence = {
        "integrated_base_sha": args.base_sha,
        "candidate_branch": args.candidate_branch,
        "candidate_branch_head": args.candidate_sha,
        "changed_files": changed_files,
        "expected_file_content": expected_file.decode("utf-8"),
        "actual_file_sha256": hashlib.sha256(actual_file).hexdigest(),
        "principal_manual_relay_count": 0,
        "merge_authorized": False,
        "release_authorized": False,
    }
    diff = diff_raw.decode("utf-8")
    budget = measure_semantic_budget(
        task_id=args.task_id,
        handover_id=task["handover_id"],
        candidate_sha=args.candidate_sha,
        assurance_contract=instruction,
        acceptance_criteria=acceptance,
        capsule=capsule,
        diff=diff,
        bounded_evidence=bounded_evidence,
    )
    decision = classify_execution_surface(
        repository=task["repository"],
        changed_files=changed_files,
        budget=budget,
        capsule=capsule,
    )
    if decision.work_required or not decision.cloudflare_eligible or decision.reasons:
        raise SystemExit(f"canary did not route STANDARD: {decision.reasons}")

    result: dict
    try:
        pack = build_semantic_pack(
            task_id=args.task_id,
            handover_id=task["handover_id"],
            candidate_sha=args.candidate_sha,
            assurance_contract=instruction,
            acceptance_criteria=acceptance,
            capsule=capsule,
            diff=diff,
            bounded_evidence=bounded_evidence,
        )
        api_response = run_workers_ai_once(
            account_id=os.environ.get("CONTROL_CLOUDFLARE_ACCOUNT_ID", ""),
            api_token=os.environ.get("CONTROL_CLOUDFLARE_API_TOKEN", ""),
            messages=build_messages(pack),
        )
        verdict = parse_verdict_response(api_response, candidate_sha=args.candidate_sha)
        result = {
            "version": "1.0",
            "task_id": args.task_id,
            "run_id": args.active_run_id,
            "role": ROLE,
            "outcome": verdict["verdict"],
            "summary": verdict["summary"],
            "candidate_sha": args.candidate_sha,
            "findings": verdict["findings"],
            "evidence": [
                "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1: START_PROVEN=true; deterministic_contradictions=[]",
                f"STANDARD executor={MODEL_ID}; one bounded call; no tools/fallback",
                f"base={args.base_sha}; candidate={args.candidate_sha}; changed_files={changed_files}",
            ],
        }
    except CloudflareB1ExecutionUnavailable as exc:
        result = {
            "version": "1.0",
            "task_id": args.task_id,
            "run_id": args.active_run_id,
            "role": ROLE,
            "outcome": "EXECUTION_UNAVAILABLE",
            "summary": "Gate-6 STANDARD executor was unavailable; no semantic verdict was fabricated.",
            "candidate_sha": args.candidate_sha,
            "findings": [exc.code],
            "evidence": ["B0 START_PROVEN=true before executor invocation", f"executor={MODEL_ID}"],
        }
    except CloudflareB1Error as exc:
        result = {
            "version": "1.0",
            "task_id": args.task_id,
            "run_id": args.active_run_id,
            "role": ROLE,
            "outcome": "BLOCKED",
            "summary": "Gate-6 deterministic STANDARD contract rejected the canary before accepting a verdict.",
            "candidate_sha": args.candidate_sha,
            "findings": [str(exc)],
            "evidence": ["B0 START_PROVEN=true before deterministic executor validation"],
        }

    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
