from datetime import datetime, timedelta, timezone

import pytest

from control_engine import minimal_core as core


NOW = datetime(2026, 8, 27, 20, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def task(task_id, operation, role, *, repository="market-predictions/control-engine", candidate_sha=SHA, priority=0, successors=None):
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
        "attempt_count": 0,
        "last_execution_error": None,
        "successor_by_outcome": successors or {},
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-27T19:00:00Z",
        "updated_at": "2026-08-27T19:00:00Z",
    }


def queue(*tasks):
    return {"version": "1.0", "principal_manual_relay_count": 0, "tasks": list(tasks)}


def runs():
    return {"version": "1.0", "runs": []}


def b_result(task_id, run_id, outcome, candidate_sha=SHA):
    return {
        "version": "1.0",
        "task_id": task_id,
        "run_id": run_id,
        "role": core.ROLE_B,
        "outcome": outcome,
        "candidate_sha": candidate_sha,
    }


def test_pass_terminalizes_assurance_and_materializes_one_integration_successor():
    successor = {
        "PASS": {
            "task_id": "CONTROL-204-INTEGRATE",
            "operation": "PROJECT_INTEGRATION",
            "role": core.ROLE_A,
            "repository": "market-predictions/control-engine",
            "candidate_sha": SHA,
            "successor_by_outcome": {},
        }
    }
    q0 = queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B, successors=successor))
    q1, r1, _ = core.claim(q0, runs(), task_id="CONTROL-204-ASSURE", worker_instance=core.INSTANCE_B1, backend="test", now=NOW, run_id="run-204")
    q2, r2, successor_id = core.finalize_result(
        q1,
        r1,
        task_id="CONTROL-204-ASSURE",
        result=b_result("CONTROL-204-ASSURE", "run-204", "PASS"),
        result_ref="control/worker-results/CONTROL-204-ASSURE.json",
        now=NOW + timedelta(minutes=1),
    )
    assert successor_id == "CONTROL-204-INTEGRATE"
    assert core.explain_task(q2, "CONTROL-204-ASSURE")["status"] == core.STATUS_TERMINAL
    assert core.explain_task(q2, "CONTROL-204-INTEGRATE")["status"] == core.STATUS_QUEUED
    assert core.explain_task(q2, "CONTROL-204-INTEGRATE")["operation"] == "PROJECT_INTEGRATION"
    assert [run["outcome"] for run in r2["runs"]] == ["PASS"]


def test_execution_failure_requeues_same_task_without_successor():
    q0 = queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B))
    q1, r1, _ = core.claim(q0, runs(), task_id="CONTROL-204-ASSURE", worker_instance=core.INSTANCE_B1, backend="test", now=NOW, run_id="run-fail")
    q2, r2 = core.release_execution_failure(q1, r1, task_id="CONTROL-204-ASSURE", run_id="run-fail", code="EXECUTOR_UNAVAILABLE", now=NOW + timedelta(minutes=1))
    current = core.explain_task(q2, "CONTROL-204-ASSURE")
    assert current["status"] == core.STATUS_QUEUED
    assert current["outcome"] is None
    assert current["last_execution_error"] == "EXECUTOR_UNAVAILABLE"
    assert len(q2["tasks"]) == 1
    assert r2["runs"][0]["outcome"] == "EXECUTOR_UNAVAILABLE"


def test_persisted_result_wins_over_expired_lease():
    q0 = queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B))
    q1, r1, _ = core.claim(q0, runs(), task_id="CONTROL-204-ASSURE", worker_instance=core.INSTANCE_B1, backend="test", now=NOW, lease_seconds=10, run_id="run-late")
    result = b_result("CONTROL-204-ASSURE", "run-late", "INDETERMINATE")
    q2, r2, report = core.reconcile(
        q1,
        r1,
        persisted_results={"CONTROL-204-ASSURE": (result, "control/worker-results/CONTROL-204-ASSURE.json")},
        now=NOW + timedelta(seconds=20),
    )
    assert report == {"finalized_results": ["CONTROL-204-ASSURE"], "expired_claims": []}
    assert core.explain_task(q2, "CONTROL-204-ASSURE")["outcome"] == "INDETERMINATE"
    assert r2["runs"][0]["outcome"] == "INDETERMINATE"


def test_expired_claim_without_result_requeues_same_task():
    q0 = queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B))
    q1, r1, _ = core.claim(q0, runs(), task_id="CONTROL-204-ASSURE", worker_instance=core.INSTANCE_B1, backend="test", now=NOW, lease_seconds=10, run_id="run-expire")
    q2, r2, report = core.reconcile(q1, r1, now=NOW + timedelta(seconds=20))
    assert report == {"finalized_results": [], "expired_claims": ["CONTROL-204-ASSURE"]}
    current = core.explain_task(q2, "CONTROL-204-ASSURE")
    assert current["status"] == core.STATUS_QUEUED
    assert current["last_execution_error"] == "LEASE_EXPIRED"
    assert r2["runs"][0]["outcome"] == "LEASE_EXPIRED"


def test_exact_candidate_binding_is_mandatory_for_b1():
    q0 = queue(task("CONTROL-204-ASSURE", "ASSURANCE", core.ROLE_B))
    q1, r1, _ = core.claim(q0, runs(), task_id="CONTROL-204-ASSURE", worker_instance=core.INSTANCE_B1, backend="test", now=NOW, run_id="run-bind")
    with pytest.raises(core.MinimalCoreError, match="candidate mismatch"):
        core.finalize_result(
            q1,
            r1,
            task_id="CONTROL-204-ASSURE",
            result=b_result("CONTROL-204-ASSURE", "run-bind", "PASS", candidate_sha="b" * 40),
            result_ref="control/worker-results/CONTROL-204-ASSURE.json",
            now=NOW + timedelta(minutes=1),
        )


def test_role_capacity_is_fail_closed():
    a = task("A", "IMPLEMENTATION", core.ROLE_A, repository="repo-a")
    b = task("B", "IMPLEMENTATION", core.ROLE_A, repository="repo-b", priority=1)
    q1, r1, _ = core.claim(queue(a, b), runs(), task_id="A", worker_instance=core.INSTANCE_A1, backend="test", now=NOW, run_id="run-a")
    with pytest.raises(core.MinimalCoreError, match="role capacity"):
        core.claim(q1, r1, task_id="B", worker_instance=core.INSTANCE_A1, backend="test", now=NOW, run_id="run-b", require_preferred=False)


def test_operation_role_is_immutable_and_principal_relay_stays_zero():
    invalid = task("X", "ASSURANCE", core.ROLE_A)
    with pytest.raises(core.MinimalCoreError, match="role does not match immutable operation"):
        core.validate(queue(invalid))
    valid = task("X", "ASSURANCE", core.ROLE_B)
    q = queue(valid)
    q["principal_manual_relay_count"] = 1
    with pytest.raises(core.MinimalCoreError, match="must remain zero"):
        core.validate(q)


def test_duplicate_successor_identity_fails_closed():
    successor = {
        "PASS": {
            "task_id": "EXISTING",
            "operation": "PROJECT_INTEGRATION",
            "role": core.ROLE_A,
            "repository": "repo",
            "candidate_sha": SHA,
            "successor_by_outcome": {},
        }
    }
    assure = task("ASSURE", "ASSURANCE", core.ROLE_B, repository="repo", successors=successor)
    existing = task("EXISTING", "PROJECT_INTEGRATION", core.ROLE_A, repository="repo")
    q1, r1, _ = core.claim(queue(assure, existing), runs(), task_id="ASSURE", worker_instance=core.INSTANCE_B1, backend="test", now=NOW, run_id="run-dup")
    with pytest.raises(core.MinimalCoreError, match="successor task already exists"):
        core.finalize_result(
            q1,
            r1,
            task_id="ASSURE",
            result=b_result("ASSURE", "run-dup", "PASS"),
            result_ref="control/worker-results/ASSURE.json",
            now=NOW + timedelta(minutes=1),
        )
