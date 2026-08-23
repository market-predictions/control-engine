#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from control_engine.cloudflare_b1 import (
    MODEL_ID,
    CloudflareB1Error,
    CloudflareB1ExecutionUnavailable,
    build_messages,
    build_semantic_pack,
    parse_verdict_response,
    run_workers_ai_once,
)


def load_fixture(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise CloudflareB1Error("shadow fixture must be an object")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Non-authoritative Cloudflare B1 shadow calibration")
    parser.add_argument("fixture")
    args = parser.parse_args()

    fixture = load_fixture(Path(args.fixture))
    candidate_sha = fixture["candidate_sha"]
    expected = fixture["expected_verdict"]
    pack = build_semantic_pack(
        task_id=fixture["task_id"],
        handover_id=fixture["handover_id"],
        candidate_sha=candidate_sha,
        assurance_contract=fixture["assurance_contract"],
        acceptance_criteria=fixture["acceptance_criteria"],
        capsule=fixture["capsule"],
        diff=fixture["diff"],
        bounded_evidence=fixture["bounded_evidence"],
    )

    try:
        response = run_workers_ai_once(
            account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            api_token=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
            messages=build_messages(pack),
        )
        verdict = parse_verdict_response(response, candidate_sha=candidate_sha)
    except CloudflareB1ExecutionUnavailable as exc:
        print(json.dumps({
            "fixture_id": fixture["fixture_id"],
            "model": MODEL_ID,
            "semantic_authority": False,
            "execution_status": exc.code,
            "expected_verdict": expected,
            "observed_verdict": None,
            "match": False,
        }, sort_keys=True))
        return 75

    observed = verdict["verdict"]
    match = observed == expected
    print(json.dumps({
        "fixture_id": fixture["fixture_id"],
        "model": MODEL_ID,
        "semantic_authority": False,
        "execution_status": "SHADOW_COMPLETED",
        "expected_verdict": expected,
        "observed_verdict": observed,
        "match": match,
        "finding_count": len(verdict["findings"]),
        "lineage_id": pack["lineage_id"],
    }, sort_keys=True))
    if not match:
        return 4 if observed == "PASS" and expected != "PASS" else 3
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (CloudflareB1Error, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "semantic_authority": False,
            "execution_status": "SHADOW_FIXTURE_INVALID",
            "error_type": type(exc).__name__,
        }, sort_keys=True))
        raise SystemExit(2)
