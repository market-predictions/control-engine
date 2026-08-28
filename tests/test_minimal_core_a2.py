from datetime import datetime, timezone

import pytest

from control_engine import minimal_core as core


NOW = datetime(2026, 8, 28, 20, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def _queue(*tasks):
    return {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": list(tasks),
    }


def _integration(task_id: str, repository: str, *, priority: int = 0, created_at: str = "2026-08-28T19:00:00Z"):
    return {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": task_id,
        "operation": "PROJECT_INTEGRATION",
        "role": core.ROLE_A,
        "repository": repository,
        "candidate_sha": SHA,
        "priority": priority,
        "status": core.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "successor_by_outcome": {},
        "principal_manual_relay_count": 0,
        "created_at": created_at,
        "updated_at": created_at,
    }


def _assurance(task_id: str, repository: str, *, priority: int = 0):
    task = _integration(task_id, repository, priority=priority)
    task.update({
        "operation": "ASSURANCE",
        "role": core.ROLE_B,
        "successor_by_outcome": {
            "PASS": {
                "task_id": f"{task_id}--INTEGRATE",
                "operation": "PROJECT_INTEGRATION",
                "role": core.ROLE_A,
                "repository": repository,
                "candidate_sha": SHA,
            },
            "FAIL": {
                "task_id": f"{task_id}--REPAIR",
                "operation": "REPAIR",
                "role": core.ROLE_A,
                "repository": repository,
                "candidate_sha": SHA,
            },
        },
    })
    return task


def test_a1_and_a2_can_claim_different_repositories():
    q = _queue(
        _integration("A", "repo-a"),
        _integration("B", "repo-b", priority=1),
    )
    q, _ = core.claim(q, task_id="A", worker_instance=core.INSTANCE_A1, backend="test", now=NOW)
    q, _ = core.claim(q, task_id="B", worker_instance=core.INSTANCE_A2, backend="test", now=NOW)

    core.validate(q)
    claims = {
        task["claim"]["worker_instance"]: task["repository"]
        for task in q["tasks"]
        if task["status"] == core.STATUS_EXECUTING
    }
    assert claims == {core.INSTANCE_A1: "repo-a", core.INSTANCE_A2: "repo-b"}


def test_auto_selection_skips_repository_already_executing():
    q = _queue(
        _integration("A", "repo-a"),
        _integration("B", "repo-a", priority=1),
        _integration("C", "repo-b", priority=2),
    )
    q, _ = core.claim(q, task_id="A", worker_instance=core.INSTANCE_A1, backend="test", now=NOW)

    assert core.select_task(q, core.ROLE_A)["task_id"] == "C"
    with pytest.raises(core.MinimalCoreError, match="repository exclusivity"):
        core.claim(
            q,
            task_id="B",
            worker_instance=core.INSTANCE_A2,
            backend="test",
            now=NOW,
            require_preferred=False,
        )


def test_worker_instance_cannot_hold_two_claims():
    q = _queue(
        _integration("A", "repo-a"),
        _integration("B", "repo-b", priority=1),
    )
    q, _ = core.claim(q, task_id="A", worker_instance=core.INSTANCE_A1, backend="test", now=NOW)

    with pytest.raises(core.MinimalCoreError, match="worker capacity exceeded: A1"):
        core.claim(
            q,
            task_id="B",
            worker_instance=core.INSTANCE_A1,
            backend="test",
            now=NOW,
            require_preferred=False,
        )


def test_b1_remains_single_capacity_and_only_b_worker():
    assert core.WORKER_ROLE == {
        core.INSTANCE_A1: core.ROLE_A,
        core.INSTANCE_A2: core.ROLE_A,
        core.INSTANCE_B1: core.ROLE_B,
    }
    q = _queue(
        _assurance("A", "repo-a"),
        _assurance("B", "repo-b", priority=1),
    )
    q, _ = core.claim(q, task_id="A", worker_instance=core.INSTANCE_B1, backend="test", now=NOW)

    with pytest.raises(core.MinimalCoreError, match="worker capacity exceeded: B1"):
        core.claim(
            q,
            task_id="B",
            worker_instance=core.INSTANCE_B1,
            backend="test",
            now=NOW,
            require_preferred=False,
        )
