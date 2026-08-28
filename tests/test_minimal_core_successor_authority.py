import pytest

from control_engine import minimal_core as core


SHA = "a" * 40


def _task(task_id, operation, role, successors):
    return {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": task_id,
        "operation": operation,
        "role": role,
        "repository": "market-predictions/control-engine",
        "priority": 0,
        "candidate_sha": SHA,
        "status": core.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "successor_by_outcome": successors,
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-27T19:00:00Z",
        "updated_at": "2026-08-27T19:00:00Z",
    }


def _queue(task):
    return {"version": "1.0", "principal_manual_relay_count": 0, "tasks": [task]}


def test_project_integration_cannot_create_successor_authority():
    successor = {
        "task_id": "CHAINED-INTEGRATION",
        "operation": "PROJECT_INTEGRATION",
        "role": core.ROLE_A,
        "repository": "market-predictions/control-engine",
        "candidate_sha": SHA,
        "successor_by_outcome": {},
    }
    invalid = _task(
        "INTEGRATE",
        "PROJECT_INTEGRATION",
        core.ROLE_A,
        {"COMPLETED": successor},
    )
    with pytest.raises(core.MinimalCoreError, match="may not create successor authority"):
        core.validate(_queue(invalid))


def test_successor_task_id_is_required_before_predecessor_can_be_claimed():
    successor = {
        "operation": "ASSURANCE",
        "role": core.ROLE_B,
        "repository": "market-predictions/control-engine",
        "candidate_sha": SHA,
        "successor_by_outcome": {},
    }
    invalid = _task(
        "IMPLEMENT",
        "IMPLEMENTATION",
        core.ROLE_A,
        {"COMPLETED": successor},
    )
    with pytest.raises(core.MinimalCoreError, match="successor task_id is required"):
        core.validate(_queue(invalid))
