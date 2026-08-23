from __future__ import annotations

import argparse
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
REQUIRED_RUNS = {32078764108, 32078764084}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True)
    parser.add_argument("--pr-json", required=True)
    parser.add_argument("--workflow-runs", required=True)
    parser.add_argument("--diff", required=True)
    parser.add_argument("--changed-files", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--active-run-id", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    queue_raw = Path(args.queue).read_bytes()
    queue = json.loads(queue_raw)
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == args.task_id]
    if len(matches) != 1:
        raise SystemExit("canonical production task identity mismatch")
    task = matches[0]
    if task.get("candidate_sha") != args.candidate_sha or task.get("active_run_id") != args.active_run_id:
        raise SystemExit("canonical production binding mismatch")
    if task.get("principal_manual_relay_count") != 0 or queue.get("principal_manual_relay_count") != 0:
        raise SystemExit("principal relay count changed")

    pr_raw = Path(args.pr_json).read_bytes()
    pr = json.loads(pr_raw)
    if pr.get("number") != 103 or pr.get("state") != "open" or pr.get("merged") is True:
        raise SystemExit("PR #103 is not open/unmerged")
    if pr.get("head", {}).get("sha") != args.candidate_sha:
        raise SystemExit("PR #103 head moved")
    if pr.get("base", {}).get("ref") != "main" or pr.get("base", {}).get("sha") != args.base_sha:
        raise SystemExit("PR #103 frozen base binding moved")

    runs_raw = Path(args.workflow_runs).read_bytes()
    runs_payload = json.loads(runs_raw)
    runs = runs_payload.get("workflow_runs", [])
    by_id = {item.get("id"): item for item in runs if isinstance(item, dict)}
    for run_id in REQUIRED_RUNS:
        run = by_id.get(run_id)
        if not run or run.get("head_sha") != args.candidate_sha or run.get("status") != "completed" or run.get("conclusion") != "success":
            raise SystemExit(f"required exact-head CI run is not successful: {run_id}")

    changed_files = [line for line in Path(args.changed_files).read_text(encoding="utf-8").splitlines() if line]
    expected_files = [
        "output/fresh_generation/weekly_etf_eu_review_260814.md",
        "output/fresh_generation/weekly_etf_eu_review_nl_260814.md",
        "runtime/reconcile_etf_eu_funded_markdown.py",
        "tools/validate_etf_eu_markdown_delivery_artifacts.py",
    ]
    if changed_files != expected_files:
        raise SystemExit("production candidate changed-file set mismatch")
    changed_raw = ("\n".join(changed_files) + "\n").encode("utf-8")
    diff_raw = Path(args.diff).read_bytes()

    capsule = build_capsule(
        queue_raw=queue_raw,
        task_id=args.task_id,
        pr_raw=pr_raw,
        workflow_runs_raw=runs_raw,
        changed_files_raw=changed_raw,
        diff_raw=diff_raw,
        observed_at=args.observed_at,
    )
    if capsule.get("deterministic_contradictions") != []:
        raise SystemExit(f"B0 contradiction: {capsule.get('deterministic_contradictions')}")
    if capsule.get("claim", {}).get("start_proven") is not True:
        raise SystemExit("START_PROVEN is not true in B0 capsule")

    acceptance = task.get("acceptance_criteria")
    instruction = task.get("instruction")
    bounded_evidence = {
        "frozen_base_sha": args.base_sha,
        "pr_number": 103,
        "pr_state": pr.get("state"),
        "pr_merged": pr.get("merged"),
        "pr_head_sha": pr.get("head", {}).get("sha"),
        "pr_base_ref": pr.get("base", {}).get("ref"),
        "pr_base_sha": pr.get("base", {}).get("sha"),
        "changed_files": changed_files,
        "required_ci_runs": {
            str(run_id): {
                "status": by_id[run_id].get("status"),
                "conclusion": by_id[run_id].get("conclusion"),
                "head_sha": by_id[run_id].get("head_sha"),
            }
            for run_id in sorted(REQUIRED_RUNS)
        },
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
        raise SystemExit(f"Gate-7 candidate did not route STANDARD: {decision.reasons}")

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
        response = run_workers_ai_once(
            account_id=os.environ.get("CONTROL_CLOUDFLARE_ACCOUNT_ID", ""),
            api_token=os.environ.get("CONTROL_CLOUDFLARE_API_TOKEN", ""),
            messages=build_messages(pack),
        )
        verdict = parse_verdict_response(response, candidate_sha=args.candidate_sha)
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
                f"PR=weekly-etf-eu#103; base={args.base_sha}; candidate={args.candidate_sha}; changed_files={changed_files}",
                "Exact-head CI runs 32078764108 and 32078764084 completed success",
            ],
        }
    except CloudflareB1ExecutionUnavailable as exc:
        result = {
            "version": "1.0",
            "task_id": args.task_id,
            "run_id": args.active_run_id,
            "role": ROLE,
            "outcome": "EXECUTION_UNAVAILABLE",
            "summary": "Gate-7 STANDARD executor was unavailable; no semantic verdict was fabricated.",
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
            "summary": "Gate-7 deterministic STANDARD contract rejected the production proof before accepting a verdict.",
            "candidate_sha": args.candidate_sha,
            "findings": [str(exc)],
            "evidence": ["B0 START_PROVEN=true before deterministic executor validation"],
        }

    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
