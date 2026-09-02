from __future__ import annotations

import pytest

from control_engine.v4_contracts import V4ValidationError
from control_engine.v4_safety import (
    assert_authority_supersession_lock_free,
    assert_integration_target_exact,
)


CANDIDATE_SHA = "c" * 40
BASE_SHA = "d" * 40


def task(*, status: str = "ACTIVE", phase: str = "INTEGRATE") -> dict:
    return {
        "task_id": "T1",
        "mission_id": "M",
        "mission_revision": "2026-09-02-r2",
        "mission_contract_blob_sha": "a" * 40,
        "repository_authority_blob_sha": "b" * 40,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["accept G1"],
        "integration_policy": "AUTO_AFTER_PASS",
        "review_policy": "INTERNAL",
        "convergence_required": False,
        "status": status,
        "phase": phase,
        "candidate": {
            "candidate_sha": CANDIDATE_SHA,
            "candidate_pr_number": 7,
            "candidate_head_branch": "candidate",
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
        },
        "last_review": {
            "candidate_sha": CANDIDATE_SHA,
            "verdict": "PASS",
            "reviewed_at": "2026-09-02T18:00:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-02T17:00:00Z",
        "updated_at": "2026-09-02T18:00:00Z",
    }


def queue(*, lock: dict | None = None, current_task: dict | None = None) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": [],
        "tasks": [current_task or task()],
    }


def test_authority_supersession_cannot_steal_live_persisted_lock() -> None:
    live_lock = {
        "run_id": "run-1",
        "task_id": "T1",
        "started_at": "2026-09-02T18:00:00Z",
        "expires_at": "2026-09-02T19:30:00Z",
    }
    with pytest.raises(V4ValidationError, match="execution_lock=null"):
        assert_authority_supersession_lock_free(queue(lock=live_lock), task_id="T1")

    # After holder release or objective-expiry recovery has already produced
    # lock=null, class-4 eligibility can be considered.
    result = assert_authority_supersession_lock_free(
        queue(lock=None, current_task=task(status="ACTIVE", phase="BUILD")),
        task_id="T1",
    )
    assert result["task_id"] == "T1"


def test_integration_guard_accepts_only_exact_reviewed_live_head_and_base() -> None:
    current = queue()
    result = assert_integration_target_exact(
        current,
        task_id="T1",
        live_candidate_sha=CANDIDATE_SHA,
        live_base_branch="main",
        live_base_sha=BASE_SHA,
    )
    assert result["phase"] == "INTEGRATE"

    with pytest.raises(V4ValidationError, match="candidate head drifted"):
        assert_integration_target_exact(
            current,
            task_id="T1",
            live_candidate_sha="e" * 40,
            live_base_branch="main",
            live_base_sha=BASE_SHA,
        )

    with pytest.raises(V4ValidationError, match="base SHA drifted"):
        assert_integration_target_exact(
            current,
            task_id="T1",
            live_candidate_sha=CANDIDATE_SHA,
            live_base_branch="main",
            live_base_sha="f" * 40,
        )

    with pytest.raises(V4ValidationError, match="base branch drifted"):
        assert_integration_target_exact(
            current,
            task_id="T1",
            live_candidate_sha=CANDIDATE_SHA,
            live_base_branch="release",
            live_base_sha=BASE_SHA,
        )
