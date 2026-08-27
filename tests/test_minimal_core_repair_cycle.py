from datetime import datetime, timedelta, timezone

import pytest

from control_engine import minimal_core as core


NOW = datetime(2026, 8, 27, 23, 0, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
NEWER_SHA = "c" * 40
REPO = "market-predictions/control-engine"


def _queue(task):
    return {"version": "1.0", "principal_manual_relay_count": 0, "tasks": [task]}


def _runs():
    return {"version": "1.0", "runs": []}


def _repair_task():
    return {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": "CONTROL-204-REPAIR",
        "operation": "REPAIR",
        "role": core.ROLE_A,
        "repository": REPO,
        "priority": 0,
        "candidate_sha": OLD_SHA,
        "status": core.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "successor_by_outcome": {
            "COMPLETED": {
                "task_id": "CONTROL-204-REASSURE",
                "operation": "ASSURANCE",
                "role": core.ROLE_B,
                "repository": REPO,
                "candidate_sha": None,
            }
        },
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-27T22:00:00Z",
        "updated_at": "2026-08-27T22:00:00Z",
    }


def _a_result(task_id, run_id, candidate_sha):
    return {
        "version": "1.0",
        "task_id": task_id,
        "run_id": run_id,
        "role": core.ROLE_A,
        "outcome": "COMPLETED",
        "candidate_sha": candidate_sha,
    }


def _b_fail(task_id, run_id, candidate_sha):
    return {
        "version": "1.0",
        "task_id": task_id,
        "run_id": run_id,
        "role": core.ROLE_B,
        "outcome": "FAIL",
        "candidate_sha": candidate_sha,
    }


def test_repair_result_binds_fresh_assurance_candidate_and_regenerates_one_step_contract():
    q1, r1, _ = core.claim(
        _queue(_repair_task()),
        _runs(),
        task_id="CONTROL-204-REPAIR",
        worker_instance=core.INSTANCE_A1,
        backend="test",
        now=NOW,
        run_id="run-repair-1",
    )
    q2, r2, successor_id = core.finalize_result(
        q1,
        r1,
        task_id="CONTROL-204-REPAIR",
        result=_a_result("CONTROL-204-REPAIR", "run-repair-1", NEW_SHA),
        result_ref="control/worker-results/CONTROL-204-REPAIR--run-repair-1.json",
        now=NOW + timedelta(minutes=1),
    )
    assert successor_id == "CONTROL-204-REASSURE"
    assure = next(task for task in q2["tasks"] if task["task_id"] == successor_id)
    assert assure["candidate_sha"] == NEW_SHA
    assert assure["successor_by_outcome"]["PASS"]["candidate_sha"] == NEW_SHA
    assert assure["successor_by_outcome"]["FAIL"]["candidate_sha"] == NEW_SHA
    assert "successor_by_outcome" not in assure["successor_by_outcome"]["FAIL"]

    q3, r3, _ = core.claim(
        q2,
        r2,
        task_id=successor_id,
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW + timedelta(minutes=2),
        run_id="run-assure-1",
    )
    q4, r4, repair2_id = core.finalize_result(
        q3,
        r3,
        task_id=successor_id,
        result=_b_fail(successor_id, "run-assure-1", NEW_SHA),
        result_ref=f"control/worker-results/{successor_id}--run-assure-1.json",
        now=NOW + timedelta(minutes=3),
    )
    repair2 = next(task for task in q4["tasks"] if task["task_id"] == repair2_id)
    assert repair2["operation"] == "REPAIR"
    assert repair2["candidate_sha"] == NEW_SHA
    assert repair2["successor_by_outcome"]["COMPLETED"]["candidate_sha"] is None

    q5, r5, _ = core.claim(
        q4,
        r4,
        task_id=repair2_id,
        worker_instance=core.INSTANCE_A1,
        backend="test",
        now=NOW + timedelta(minutes=4),
        run_id="run-repair-2",
    )
    q6, _, assure2_id = core.finalize_result(
        q5,
        r5,
        task_id=repair2_id,
        result=_a_result(repair2_id, "run-repair-2", NEWER_SHA),
        result_ref=f"control/worker-results/{repair2_id}--run-repair-2.json",
        now=NOW + timedelta(minutes=5),
    )
    assure2 = next(task for task in q6["tasks"] if task["task_id"] == assure2_id)
    assert assure2["candidate_sha"] == NEWER_SHA
    assert assure2["successor_by_outcome"]["PASS"]["candidate_sha"] == NEWER_SHA
    assert assure2["successor_by_outcome"]["FAIL"]["candidate_sha"] == NEWER_SHA


def test_completed_repair_with_successor_requires_exact_result_candidate():
    q1, r1, _ = core.claim(
        _queue(_repair_task()),
        _runs(),
        task_id="CONTROL-204-REPAIR",
        worker_instance=core.INSTANCE_A1,
        backend="test",
        now=NOW,
        run_id="run-missing-sha",
    )
    with pytest.raises(core.MinimalCoreError, match="requires exact resulting candidate SHA"):
        core.finalize_result(
            q1,
            r1,
            task_id="CONTROL-204-REPAIR",
            result=_a_result("CONTROL-204-REPAIR", "run-missing-sha", None),
            result_ref="control/worker-results/CONTROL-204-REPAIR--run-missing-sha.json",
            now=NOW + timedelta(minutes=1),
        )
