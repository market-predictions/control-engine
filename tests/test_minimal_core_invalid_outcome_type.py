from datetime import datetime, timezone

from control_engine import minimal_core as core


NOW = datetime(2026, 8, 27, 22, 10, tzinfo=timezone.utc)
SHA = "a" * 40
TASK_ID = "ASSURE"
RUN_ID = "run-invalid-outcome"
RESULT_REF = f"control/worker-results/{TASK_ID}--{RUN_ID}.json"


def test_unhashable_persisted_outcome_requeues_as_execution_failure():
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "lifecycle_model": core.PROTOCOL_ID,
                "task_id": TASK_ID,
                "operation": "ASSURANCE",
                "role": core.ROLE_B,
                "repository": "market-predictions/control-engine",
                "priority": 0,
                "candidate_sha": SHA,
                "status": core.STATUS_EXECUTING,
                "outcome": None,
                "claim": {
                    "run_id": RUN_ID,
                    "role": core.ROLE_B,
                    "worker_instance": core.INSTANCE_B1,
                    "backend": "test",
                    "started_at": "2026-08-27T22:00:00Z",
                    "expires_at": "2026-08-27T23:00:00Z",
                },
                "result_ref": None,
                "terminal_run_id": None,
                "attempt_count": 1,
                "last_execution_error": None,
                "successor_by_outcome": {},
                "principal_manual_relay_count": 0,
                "created_at": "2026-08-27T21:00:00Z",
                "updated_at": "2026-08-27T22:00:00Z",
            }
        ],
    }
    malformed = {
        "version": "1.0",
        "task_id": TASK_ID,
        "run_id": RUN_ID,
        "role": core.ROLE_B,
        "outcome": [],
        "candidate_sha": SHA,
    }

    queue2, report = core.reconcile(
        queue,
        persisted_results={(TASK_ID, RUN_ID): (malformed, RESULT_REF)},
        now=NOW,
    )

    task = core.explain_task(queue2, TASK_ID)
    assert task["status"] == core.STATUS_QUEUED
    assert task["last_execution_error"] == "INVALID_PERSISTED_RESULT"
    assert task["outcome"] is None
    assert report == {"finalized_results": [], "expired_claims": []}
