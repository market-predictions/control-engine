from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import parse_public_command, safe_work_capsule


NOW = datetime(2026, 9, 22, 17, 0, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
BASE_SHA = "c" * 40
RUN_ID = "candidate-drift-loop"
TASK_ID = "MISSION--M--2026-09-22-r1--G1"


def candidate(sha: str) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": 48,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def queue() -> dict:
    task = {
        "task_id": TASK_ID,
        "mission_id": "M",
        "mission_revision": "2026-09-22-r1",
        "mission_contract_blob_sha": "d" * 40,
        "repository_authority_blob_sha": "e" * 40,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["fresh exact-candidate review passes"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": candidate(OLD_SHA),
        "last_review": {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
            "verdict": "PASS",
            "reviewed_at": "2026-09-22T16:00:00Z",
        },
        "external_review": {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
            "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
            "status": "PENDING",
            "request_ref": "https://github.com/example/repo/pull/48#issuecomment-1",
            "evidence_ref": None,
        },
        "blocker": None,
        "created_at": "2026-09-22T15:00:00Z",
        "updated_at": "2026-09-22T16:00:00Z",
    }
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": {
            "run_id": RUN_ID,
            "task_id": TASK_ID,
            "started_at": "2026-09-22T16:30:00Z",
            "expires_at": "2026-09-22T18:00:00Z",
        },
        "migration_facts": [],
        "tasks": [task],
    }


def candidate_ready_event(q: dict, new_sha: str) -> dict:
    work = safe_work_capsule(q, task_id=TASK_ID, run_id=RUN_ID)
    payload = {
        "run_id": RUN_ID,
        "task_token": work["task_token"],
        "event": "CANDIDATE_READY",
        "repository": work["repository"],
        "action": work["action"],
        "candidate": work["candidate"],
        "new_candidate_sha": new_sha,
        "candidate_pr_number": 48,
        "candidate_head_branch": "candidate",
        "new_expected_base_branch": "main",
        "new_expected_base_sha": BASE_SHA,
    }
    return parse_public_command("CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":")))


def run_event(monkeypatch, q: dict, command: dict, live: dict):
    writes: list[tuple[dict, str]] = []

    def fake_write(state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: deepcopy(live))
    state = {"queue": deepcopy(q), "runtime_enabled": True, "integration_enabled": False}
    _, result = carrier._event(command, state, now=NOW)
    return writes, result


def test_candidate_ready_from_stale_review_first_rewinds_to_repair_then_rebinds(monkeypatch) -> None:
    q = queue()
    assert safe_work_capsule(q, task_id=TASK_ID, run_id=RUN_ID)["action"] == "RECONCILE_EXTERNAL_REVIEW"

    first = candidate_ready_event(q, NEW_SHA)
    writes, result = run_event(monkeypatch, q, first, candidate(NEW_SHA))

    assert len(writes) == 1
    repair, reason = writes[0]
    assert reason == "candidate-drift-to-repair"
    assert result["result"] == "YIELDED"
    assert repair["tasks"][0]["phase"] == "REPAIR"
    assert repair["tasks"][0]["candidate"]["candidate_sha"] == OLD_SHA
    assert repair["execution_lock"] is None

    repair["execution_lock"] = {
        "run_id": RUN_ID,
        "task_id": TASK_ID,
        "started_at": "2026-09-22T16:31:00Z",
        "expires_at": "2026-09-22T18:01:00Z",
    }
    second = candidate_ready_event(repair, NEW_SHA)
    writes, result = run_event(monkeypatch, repair, second, candidate(NEW_SHA))

    assert len(writes) == 1
    rebound, reason = writes[0]
    assert reason == "candidate-ready"
    assert result["result"] == "YIELDED"
    assert rebound["tasks"][0]["phase"] == "REVIEW"
    assert rebound["tasks"][0]["candidate"]["candidate_sha"] == NEW_SHA
    assert rebound["tasks"][0]["last_review"] is None
    assert rebound["tasks"][0]["external_review"] is None
    assert rebound["execution_lock"] is None
