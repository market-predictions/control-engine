#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from control_engine.codex_b1 import build_review_request, classify_review_snapshot


def _load(path: str) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON array")
    return value


def command_request(args: argparse.Namespace) -> int:
    criteria = json.loads(Path(args.criteria).read_text(encoding="utf-8"))
    body = build_review_request(
        task_id=args.task_id,
        handover_id=args.handover_id,
        candidate_sha=args.candidate_sha,
        acceptance_criteria=criteria,
    )
    Path(args.output).write_text(body, encoding="utf-8")
    return 0


def command_classify(args: argparse.Namespace) -> int:
    decision = classify_review_snapshot(
        task_id=args.task_id,
        handover_id=args.handover_id,
        candidate_sha=args.candidate_sha,
        request_comment_id=args.request_comment_id,
        reviews=_load(args.reviews),
        review_comments=_load(args.review_comments),
        trigger_reactions=_load(args.reactions),
        issue_comments=_load(args.issue_comments),
    )
    payload = {
        "protocol_id": "CONTROL_CODEX_DEEP_B1_CANARY_RESULT_V1",
        "semantic_authority": False,
        "status": decision.status,
        "verdict": decision.verdict,
        "summary": decision.summary,
        "findings": list(decision.findings),
        "reviewed_commit": decision.reviewed_commit,
    }
    Path(args.output).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"CODEX_B1_CANARY_STATUS={decision.status}")
    if decision.verdict:
        print(f"CODEX_B1_CANARY_VERDICT={decision.verdict}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Non-authoritative Codex deep-B1 handshake canary helper")
    sub = parser.add_subparsers(dest="command", required=True)

    request = sub.add_parser("request")
    request.add_argument("--task-id", required=True)
    request.add_argument("--handover-id", required=True)
    request.add_argument("--candidate-sha", required=True)
    request.add_argument("--criteria", required=True)
    request.add_argument("--output", required=True)
    request.set_defaults(func=command_request)

    classify = sub.add_parser("classify")
    classify.add_argument("--task-id", required=True)
    classify.add_argument("--handover-id", required=True)
    classify.add_argument("--candidate-sha", required=True)
    classify.add_argument("--request-comment-id", required=True, type=int)
    classify.add_argument("--reviews", required=True)
    classify.add_argument("--review-comments", required=True)
    classify.add_argument("--reactions", required=True)
    classify.add_argument("--issue-comments", required=True)
    classify.add_argument("--output", required=True)
    classify.set_defaults(func=command_classify)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.func(args)
    except Exception as exc:
        sys.stderr.write(f"CODEX_B1_CANARY_ERROR:{type(exc).__name__}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
