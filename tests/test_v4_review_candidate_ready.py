from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import (
    StaleEventError,
    parse_public_command,
    safe_work_capsule,
)


NOW = datetime(2026, 9, 21, 17, 30, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
BASE_SHA = "c" * 40
MISSION_BLOB = "d" * 40
AUTHORITY_BLOB = "e" * 40
TASK_ID = "MISSION--M--2026-09-21-r1--G1"


def candidate(sha: str = OLD_SHA, *, base_sha: str = BASE_SHA) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": 48,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": base_sha,
    }


def review_pass() -> dict:
    return {
        "candidate_sha": OLD_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "verdict": "PASS",
        "reviewed_at": "2026-09-21T17:00:00Z",
    }


def external_pending() -> dict:
    return {
        "candidate_sha": OLD_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
        "status": "PENDING",
        "request_ref": "https://github.com/example/repo/pull/48#issuecomment-1",
        "evidence_ref": None,
    }


def review_queue() -> dict:
    task = {
        "task_id": TASK_ID,
        "mission_id": "M",
        "mission_revision": "2026-09-21-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["private acceptance"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": candidate(),
        "last_review": review_pass(),
        "external_review": external_pending(),
        "blocker": None,
        "created_at": "2026-09-21T16:00:00Z",
        "updated_at": "2026-09-21T17:00:00Z",
    }
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": {
            "run_id": "run-1",
            "task_id": TASK_ID,
            "started_at": "2026-09-21T17:00:00Z",
            "expires_at": "2026-09-21T18:30:00Z",
        },
        "migration_facts": [],
        "tasks": [task],
    }


def candidate_ready_body(q: dict, *, new_candidate: dict) -> str:
    capsule = safe_work_capsule(q, task_id=TASK_ID, run_id="run-1")
    payload = {
        "run_id": "run-1",
        "task_token": capsule["task_token"],
        "event": "CANDIDATE_READY",
        "repository": capsule["repository"],
        "action": capsule["action"],
        "candidate": capsule["candidate"],
        "new_candidate_sha": new_candidate["candidate_sha"],
        "candidate_pr_number": new_candidate["candidate_pr_number"],
        "candidate_head_branch": new_candidate["candidate_head_branch"],
        "new_expected_base_branch": new_candidate["expected_base_branch"],
        "new_expected_base_sha": new_candidate["expected_base_sha"],
    }
    return "CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":"))


def test_review_candidate_ready_rebinds_exact_live_head_and_clears_stale_reviews(monkeypatch) -> None:
    q = review_queue()
    live = candidate(NEW_SHA)
    command = parse_public_command(candidate_ready_body(q, new_candidate=live))
    state = {"queue": q, "runtime_enabled": True, "integration_enabled": False}
    writes: list[tuple[dict, str]] = []

    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: live)

    def fake_write(current_state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**current_state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)

    _, result = carrier._event(command, state, now=NOW)

    assert len(writes) == 1
    updated, reason = writes[0]
    assert reason == "candidate-ready"
    current = updated["tasks"][0]
    assert current["candidate"] == live
    assert current["last_review"] is None
    assert current["external_review"] is None
    assert current["status"] == "ACTIVE"
    assert current["phase"] == "REVIEW"
    assert updated["execution_lock"] is None
    assert result["result"] == "YIELDED"


def test_review_candidate_ready_still_fails_closed_when_live_identity_differs(monkeypatch) -> None:
    q = review_queue()
    requested = candidate(NEW_SHA)
    command = parse_public_command(candidate_ready_body(q, new_candidate=requested))
    state = {"queue": q, "runtime_enabled": True, "integration_enabled": False}
    different_live = candidate(NEW_SHA, base_sha="f" * 40)

    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: different_live)

    with pytest.raises(StaleEventError):
        carrier._event(command, state, now=NOW)
