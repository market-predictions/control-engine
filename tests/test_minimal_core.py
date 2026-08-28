from datetime import datetime, timedelta, timezone

import pytest

from control_engine import minimal_core as core


NOW = datetime(2026, 8, 27, 20, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def task(
    task_id,
    operation,
    role,
    *,
    repository="market-predictions/control-engine",
    candidate_sha=SHA,
    priority=0,
    successors=None,
):
    return {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": task_id,
        "operation": operation,
        "role": role,
        "repository": repository,
        "priority": priority,
        "candidate_sha": candidate_sha,
        "status": core.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "successor_by_outcome": successors or {},
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-27T19:00:00Z",
        "updated_at": "2026-08-27T19:00:00Z",
    }


def queue(*tasks):
    return {"version": "1.0", "principal_manual_relay_count": 0, "tasks": list(tasks)}


def b_result(task_id, run_id, outcome, candidate_sha=SHA):
    return {
        "version": "1.0",
        "task_id": task_id,
        "run_id": run_id,
        "role": core.ROLE_B,
        "outcome": outcome,
        "candidate_sha": candidate_sha,
    }


def integration_successor(task_id="CONTROL-204-INTEGRATE"):
    return {
        "task_id": task_id,
        "operation": "PROJECT_INTEGRATION",
        "role": core.ROLE_A,
        "repository": "market-predictions/control-engine",
        "candidate_sha": SHA,
        "successor_by_outcome": {},
    }


def repair_successor(task_id="CONTROL-204-REPAIR-1"):
    return {
        "task_id": task_id,
        "operation": "REPAIR",
        "role": core.ROLE_A,
        "repository": "market-predictions/control-engine",
        "candidate_sha": SHA,
        "successor_by_outcome": {},
    }


def assurance_successor(task_id="CONTROL-204-ASSURE", candidate_sha=SHA):
    return {
        "task_id": task_id,
        "operation": "ASSURANCE",
        "role": core.ROLE_B,
        "repository": "market-predictions/control-engine",
        "candidate_sha": candidate_sha,
        "successor_by_outcome": {},
    }


def test_pass_terminalizes_assurance_and_materializes_one_integration_successor():
    q1, _ = core.claim(
        queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B, successors={"PASS": integration_successor()})),
        task_id="CONTROL-204-ASSURE",
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        run_id="run-204",
    )
    q2, successor_id = core.finalize_result(
        q1,
        task_id="CONTROL-204-ASSURE",
        result=b_result("CONTROL-204-ASSURE", "run-204", "PASS"),
        result_ref="control/worker-results/CONTROL-204-ASSURE--run-204.json",
        now=NOW + timedelta(minutes=1),
    )
    assert successor_id == "CONTROL-204-INTEGRATE"
    terminal = core.explain_task(q2, "CONTROL-204-ASSURE")
    assert terminal["status"] == core.STATUS_TERMINAL
    assert terminal["run_id"] == "run-204"
    assert core.explain_task(q2, successor_id)["operation"] == "PROJECT_INTEGRATION"


def test_execution_failure_requeues_same_task_without_successor():
    q1, _ = core.claim(
        queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B)),
        task_id="CONTROL-204-ASSURE",
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        run_id="run-fail",
    )
    q2 = core.release_execution_failure(
        q1,
        task_id="CONTROL-204-ASSURE",
        run_id="run-fail",
        code="EXECUTOR_UNAVAILABLE",
        now=NOW + timedelta(minutes=1),
    )
    current = core.explain_task(q2, "CONTROL-204-ASSURE")
    assert current["status"] == core.STATUS_QUEUED
    assert current["outcome"] is None
    assert current["run_id"] is None
    assert current["last_execution_error"] == "EXECUTOR_UNAVAILABLE"
    assert len(q2["tasks"]) == 1


def test_expired_lease_wins_over_persisted_result():
    task_id = "CONTROL-204-ASSURE"
    q1, _ = core.claim(
        queue(task(task_id, "ASSURANCE", core.ROLE_B)),
        task_id=task_id,
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        lease_seconds=10,
        run_id="run-late",
    )
    q2, report = core.reconcile(
        q1,
        persisted_results={(task_id, "run-late"): (b_result(task_id, "run-late", "PASS"), "result.json")},
        now=NOW + timedelta(seconds=20),
    )
    assert report == {"finalized_results": [], "expired_claims": [task_id]}
    current = core.explain_task(q2, task_id)
    assert current["status"] == core.STATUS_QUEUED
    assert current["outcome"] is None
    assert current["result_ref"] is None
    assert current["last_execution_error"] == "LEASE_EXPIRED"


def test_current_lease_persisted_result_finalizes():
    task_id = "CONTROL-204-ASSURE"
    q1, _ = core.claim(
        queue(task(task_id, "ASSURANCE", core.ROLE_B)),
        task_id=task_id,
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        lease_seconds=60,
        run_id="run-current",
    )
    q2, report = core.reconcile(
        q1,
        persisted_results={
            (task_id, "run-current"): (
                b_result(task_id, "run-current", "INDETERMINATE"),
                "control/worker-results/CONTROL-204-ASSURE--run-current.json",
            )
        },
        now=NOW + timedelta(seconds=20),
    )
    assert report == {"finalized_results": [task_id], "expired_claims": []}
    terminal = core.explain_task(q2, task_id)
    assert terminal["outcome"] == "INDETERMINATE"
    assert terminal["run_id"] == "run-current"


def test_invalid_current_run_result_is_execution_failure_not_semantic_verdict():
    task_id = "CONTROL-204-ASSURE"
    q1, _ = core.claim(
        queue(task(task_id, "ASSURANCE", core.ROLE_B)),
        task_id=task_id,
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        lease_seconds=60,
        run_id="run-invalid",
    )
    q2, report = core.reconcile(
        q1,
        persisted_results={(task_id, "run-invalid"): (None, "invalid.json")},
        now=NOW + timedelta(seconds=10),
    )
    assert report == {"finalized_results": [], "expired_claims": []}
    current = core.explain_task(q2, task_id)
    assert current["status"] == core.STATUS_QUEUED
    assert current["outcome"] is None
    assert current["last_execution_error"] == "INVALID_PERSISTED_RESULT"


def test_invalid_present_candidate_on_blocked_a1_requeues_as_execution_failure():
    task_id = "A1-BLOCKED-BAD-CANDIDATE"
    run_id = "run-bad-a1-candidate"
    work = task(
        task_id,
        "IMPLEMENTATION",
        core.ROLE_A,
        candidate_sha=None,
        successors={"COMPLETED": assurance_successor(f"{task_id}--ASSURE", candidate_sha=None)},
    )
    q1, _ = core.claim(
        queue(work),
        task_id=task_id,
        worker_instance=core.INSTANCE_A1,
        backend="test",
        now=NOW,
        run_id=run_id,
    )
    malformed = {
        "version": "1.0",
        "task_id": task_id,
        "run_id": run_id,
        "role": core.ROLE_A,
        "outcome": "BLOCKED",
        "candidate_sha": [],
    }
    result_ref = f"control/worker-results/{task_id}--{run_id}.json"
    q2, report = core.reconcile(
        q1,
        persisted_results={(task_id, run_id): (malformed, result_ref)},
        now=NOW + timedelta(seconds=10),
    )
    assert report == {"finalized_results": [], "expired_claims": []}
    current = core.explain_task(q2, task_id)
    assert current["status"] == core.STATUS_QUEUED
    assert current["outcome"] is None
    assert current["last_execution_error"] == "INVALID_PERSISTED_RESULT"


def test_expired_claim_without_result_requeues_same_task():
    q1, _ = core.claim(
        queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B)),
        task_id="CONTROL-204-ASSURE",
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        lease_seconds=10,
        run_id="run-expire",
    )
    q2, report = core.reconcile(q1, now=NOW + timedelta(seconds=20))
    assert report == {"finalized_results": [], "expired_claims": ["CONTROL-204-ASSURE"]}
    assert core.explain_task(q2, "CONTROL-204-ASSURE")["last_execution_error"] == "LEASE_EXPIRED"


def test_exact_candidate_binding_is_mandatory_for_b1():
    q1, _ = core.claim(
        queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B)),
        task_id="CONTROL-204-ASSURE",
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        run_id="run-bind",
    )
    with pytest.raises(core.MinimalCoreError, match="candidate mismatch"):
        core.finalize_result(
            q1,
            task_id="CONTROL-204-ASSURE",
            result=b_result("CONTROL-204-ASSURE", "run-bind", "PASS", candidate_sha="b" * 40),
            result_ref="control/worker-results/CONTROL-204-ASSURE--run-bind.json",
            now=NOW + timedelta(minutes=1),
        )


@pytest.mark.parametrize("operation", ["ASSURANCE", "REPAIR", "PROJECT_INTEGRATION"])
def test_candidate_bound_operations_require_concrete_exact_sha(operation):
    invalid = task("BOUND", operation, core.OPERATION_ROLE[operation], candidate_sha=None)
    with pytest.raises(core.MinimalCoreError, match="requires exact candidate SHA"):
        core.validate(queue(invalid))


@pytest.mark.parametrize(
    ("successors", "message"),
    [
        ({"INDETERMINATE": integration_successor()}, "INDETERMINATE assurance"),
        ({"PASS": repair_successor()}, "invalid authority"),
        ({"FAIL": integration_successor()}, "invalid authority"),
    ],
)
def test_assurance_successor_routing_is_fail_closed(successors, message):
    with pytest.raises(core.MinimalCoreError, match=message):
        core.validate(queue(task("ASSURE", "ASSURANCE", core.ROLE_B, successors=successors)))


@pytest.mark.parametrize("operation", ["IMPLEMENTATION", "REPAIR"])
def test_a1_completed_work_requires_assurance_reservation(operation):
    invalid = task("A1-NO-ASSURE", operation, core.ROLE_A, successors={})
    with pytest.raises(core.MinimalCoreError, match="must reserve assurance"):
        core.validate(queue(invalid))


@pytest.mark.parametrize("operation", ["IMPLEMENTATION", "REPAIR"])
def test_a1_completed_work_cannot_route_directly_to_integration(operation):
    with pytest.raises(core.MinimalCoreError, match="must route through assurance"):
        core.validate(
            queue(
                task(
                    "A1-WORK",
                    operation,
                    core.ROLE_A,
                    successors={"COMPLETED": integration_successor()},
                )
            )
        )


@pytest.mark.parametrize("operation", ["IMPLEMENTATION", "REPAIR"])
def test_a1_completed_work_routes_to_result_bound_assurance(operation):
    core.validate(
        queue(
            task(
                "A1-UNBOUND",
                operation,
                core.ROLE_A,
                successors={"COMPLETED": assurance_successor(candidate_sha=None)},
            )
        )
    )
    malformed = task(
        "A1-BAD-SHA",
        operation,
        core.ROLE_A,
        successors={"COMPLETED": assurance_successor(candidate_sha="not-a-sha")},
    )
    with pytest.raises(core.MinimalCoreError, match="candidate template is invalid"):
        core.validate(queue(malformed))


def test_blocked_a1_work_cannot_create_successor_authority():
    invalid = task(
        "A1-BLOCKED",
        "IMPLEMENTATION",
        core.ROLE_A,
        successors={"BLOCKED": assurance_successor()},
    )
    with pytest.raises(core.MinimalCoreError, match="blocked A1 work"):
        core.validate(queue(invalid))


def test_role_capacity_is_fail_closed_from_queue_alone():
    q1, _ = core.claim(
        queue(
            task("A", "PROJECT_INTEGRATION", core.ROLE_A, repository="repo-a"),
            task("B", "PROJECT_INTEGRATION", core.ROLE_A, repository="repo-b", priority=1),
        ),
        task_id="A",
        worker_instance=core.INSTANCE_A1,
        backend="test",
        now=NOW,
        run_id="run-a",
    )
    with pytest.raises(core.MinimalCoreError, match="role capacity"):
        core.claim(
            q1,
            task_id="B",
            worker_instance=core.INSTANCE_A1,
            backend="test",
            now=NOW,
            run_id="run-b",
            require_preferred=False,
        )


def test_operation_role_is_immutable_and_principal_relay_stays_zero():
    with pytest.raises(core.MinimalCoreError, match="role does not match immutable operation"):
        core.validate(queue(task("X", "ASSURANCE", core.ROLE_A)))

    for invalid_relay in (1, False, 0.0, "0", None):
        q = queue(task("X", "ASSURANCE", core.ROLE_B))
        q["principal_manual_relay_count"] = invalid_relay
        with pytest.raises(core.MinimalCoreError, match="integer zero"):
            core.validate(q)

        item = task("X", "ASSURANCE", core.ROLE_B)
        item["principal_manual_relay_count"] = invalid_relay
        with pytest.raises(core.MinimalCoreError, match="integer zero"):
            core.validate(queue(item))


def test_duplicate_successor_identity_fails_before_claim():
    assure = task(
        "ASSURE",
        "ASSURANCE",
        core.ROLE_B,
        successors={"PASS": integration_successor("EXISTING")},
    )
    existing = task("EXISTING", "PROJECT_INTEGRATION", core.ROLE_A)
    with pytest.raises(core.MinimalCoreError, match="successor task already exists"):
        core.claim(
            queue(assure, existing),
            task_id="ASSURE",
            worker_instance=core.INSTANCE_B1,
            backend="test",
            now=NOW,
            run_id="run-dup",
        )


def test_duplicate_successor_reservation_fails_before_claim():
    shared_id = "SHARED-FUTURE-TASK"
    first = task(
        "ASSURE-A",
        "ASSURANCE",
        core.ROLE_B,
        repository="repo-a",
        successors={
            "PASS": {
                "task_id": shared_id,
                "operation": "PROJECT_INTEGRATION",
                "role": core.ROLE_A,
                "repository": "repo-a",
                "candidate_sha": SHA,
            }
        },
    )
    second = task(
        "ASSURE-B",
        "ASSURANCE",
        core.ROLE_B,
        repository="repo-b",
        priority=1,
        successors={
            "PASS": {
                "task_id": shared_id,
                "operation": "PROJECT_INTEGRATION",
                "role": core.ROLE_A,
                "repository": "repo-b",
                "candidate_sha": SHA,
            }
        },
    )
    with pytest.raises(core.MinimalCoreError, match="reserved by another task"):
        core.claim(
            queue(first, second),
            task_id="ASSURE-A",
            worker_instance=core.INSTANCE_B1,
            backend="test",
            now=NOW,
            run_id="run-reservation-collision",
        )


def test_exact_terminal_result_replay_is_idempotent_without_run_projection():
    q1, _ = core.claim(
        queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B, successors={"PASS": integration_successor()})),
        task_id="CONTROL-204-ASSURE",
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        run_id="run-replay",
    )
    result = b_result("CONTROL-204-ASSURE", "run-replay", "PASS")
    ref = "control/worker-results/CONTROL-204-ASSURE--run-replay.json"
    q2, first_successor = core.finalize_result(
        q1,
        task_id="CONTROL-204-ASSURE",
        result=result,
        result_ref=ref,
        now=NOW + timedelta(minutes=1),
    )
    q3, replay_successor = core.finalize_result(
        q2,
        task_id="CONTROL-204-ASSURE",
        result=result,
        result_ref=ref,
        now=NOW + timedelta(minutes=2),
    )
    assert q3 == q2
    assert replay_successor == first_successor == "CONTROL-204-INTEGRATE"
    assert core.explain_task(q3, "CONTROL-204-ASSURE")["run_id"] == "run-replay"


def test_terminal_b1_replay_rejects_mismatched_successor_candidate():
    q1, _ = core.claim(
        queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B, successors={"PASS": integration_successor()})),
        task_id="CONTROL-204-ASSURE",
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        run_id="run-replay-bind",
    )
    result = b_result("CONTROL-204-ASSURE", "run-replay-bind", "PASS")
    ref = "control/worker-results/CONTROL-204-ASSURE--run-replay-bind.json"
    q2, _ = core.finalize_result(
        q1,
        task_id="CONTROL-204-ASSURE",
        result=result,
        result_ref=ref,
        now=NOW + timedelta(minutes=1),
    )
    core._task(q2, "CONTROL-204-INTEGRATE")["candidate_sha"] = "b" * 40
    with pytest.raises(core.MinimalCoreError, match="terminal task materialized successor candidate mismatch"):
        core.finalize_result(
            q2,
            task_id="CONTROL-204-ASSURE",
            result=result,
            result_ref=ref,
            now=NOW + timedelta(minutes=2),
        )


def test_terminal_run_identity_is_unique_in_queue():
    first = task("DONE-1", "ASSURANCE", core.ROLE_B)
    first.update(status=core.STATUS_TERMINAL, outcome="INDETERMINATE", result_ref="r1.json", terminal_run_id="run-same")
    second = task("DONE-2", "ASSURANCE", core.ROLE_B)
    second.update(status=core.STATUS_TERMINAL, outcome="INDETERMINATE", result_ref="r2.json", terminal_run_id="run-same")
    with pytest.raises(core.MinimalCoreError, match="duplicate Minimal Core run identity"):
        core.validate(queue(first, second))


def test_stale_result_from_prior_run_cannot_block_current_retry_expiry():
    task_id = "CONTROL-204-ASSURE"
    q1, _ = core.claim(
        queue(task(task_id, "ASSURANCE", core.ROLE_B)),
        task_id=task_id,
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW,
        lease_seconds=10,
        run_id="run-old",
    )
    q2 = core.release_execution_failure(
        q1,
        task_id=task_id,
        run_id="run-old",
        code="EXECUTOR_UNAVAILABLE",
        now=NOW + timedelta(seconds=5),
    )
    q3, _ = core.claim(
        q2,
        task_id=task_id,
        worker_instance=core.INSTANCE_B1,
        backend="test",
        now=NOW + timedelta(seconds=10),
        lease_seconds=10,
        run_id="run-new",
    )
    q4, report = core.reconcile(
        q3,
        persisted_results={
            (task_id, "run-old"): (
                b_result(task_id, "run-old", "PASS"),
                "control/worker-results/CONTROL-204-ASSURE--run-old.json",
            )
        },
        now=NOW + timedelta(seconds=25),
    )
    assert report == {"finalized_results": [], "expired_claims": [task_id]}
    current = core.explain_task(q4, task_id)
    assert current["status"] == core.STATUS_QUEUED
    assert current["last_execution_error"] == "LEASE_EXPIRED"
