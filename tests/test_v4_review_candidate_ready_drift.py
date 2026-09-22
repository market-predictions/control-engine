from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_contracts import acquire_task_v4
from control_engine.v4_runtime_protocol import parse_public_command, safe_work_capsule


NOW = datetime(2026, 9, 22, 18, 45, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
BASE_SHA = "c" * 40
MISSION_BLOB = "d" * 40
AUTHORITY_BLOB = "e" * 40
TASK_ID = "MISSION--M--2026-09-22-r1--G1"


def candidate(sha: str) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": 48,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def review_task() -> dict:
    return {
        "task_id": TASK_ID,
        "mission_id": "M",
        "mission_revision": "2026-09-22-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["fresh exact-candidate review must pass"],
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
            "reviewed_at": "2026-09-22T17:00:00Z",
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
        "created_at": "2026-09-22T16:00:00Z",
        "updated_at": "2026-09-22T17:00:00Z",
    }


def queue(one_task: dict, *, run_id: str) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": {
            "run_id": run_id,
            "task_id": one_task["task_id"],
            "started_at": "2026-09-22T18:00:00Z",
            "expires_at": "2026-09-22T19:30:00Z",
        },
        "migration_facts": [],
        "tasks": [one_task],
    }


def candidate_ready_event(q: dict, *, new_sha: str) -> dict:
    current = q["tasks"][0]
    run_id = q["execution_lock"]["run_id"]
    capsule = safe_work_capsule(q, task_id=current["task_id"], run_id=run_id)
    payload = {
        "run_id": run_id,
        "task_token": capsule["task_token"],
        "event": "CANDIDATE_READY",
        "repository": capsule["repository"],
        "action": capsule["action"],
        "candidate": capsule["candidate"],
        "new_candidate_sha": new_sha,
        "candidate_pr_number": 48,
        "candidate_head_branch": "candidate",
        "new_expected_base_branch": "main",
        "new_expected_base_sha": BASE_SHA,
    }
    return parse_public_command(
        "CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":"))
    )


def fake_state(q: dict) -> dict:
    return {
        "queue": q,
        "runtime_enabled": True,
        "integration_enabled": False,
        "main_sha": "1" * 40,
        "runtime_sha": "2" * 40,
        "queue_blob": "3" * 40,
        "repository_node_id": "R_test",
    }


def test_candidate_ready_from_review_drift_enters_repair_then_rebinds(monkeypatch) -> None:
    q = queue(review_task(), run_id="run-review")
    live = candidate(NEW_SHA)
    writes: list[tuple[dict, str]] = []

    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: live)

    def fake_write(state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)

    state, result = carrier._event(candidate_ready_event(q, new_sha=NEW_SHA), fake_state(q), now=NOW)
    drifted = state["queue"]["tasks"][0]
    assert result["result"] == "YIELDED"
    assert drifted["status"] == "ACTIVE"
    assert drifted["phase"] == "REPAIR"
    assert drifted["candidate"]["candidate_sha"] == OLD_SHA
    assert state["queue"]["execution_lock"] is None
    assert writes[-1][1] == "candidate-drift-to-repair"

    reacquired = acquire_task_v4(
        state["queue"],
        task_id=TASK_ID,
        run_id="run-repair",
        now=NOW,
        control_runtime_enabled=True,
        integration_enabled=False,
    )
    state2, result2 = carrier._event(
        candidate_ready_event(reacquired, new_sha=NEW_SHA),
        {**state, "queue": reacquired},
        now=NOW,
    )
    rebound = state2["queue"]["tasks"][0]
    assert result2["result"] == "YIELDED"
    assert rebound["status"] == "ACTIVE"
    assert rebound["phase"] == "REVIEW"
    assert rebound["candidate"] == live
    assert rebound["last_review"] is None
    assert rebound["external_review"] is None
    assert rebound["blocker"] is None
    assert state2["queue"]["execution_lock"] is None
    assert writes[-1][1] == "candidate-ready"
