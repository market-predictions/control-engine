from datetime import datetime, timedelta, timezone

import pytest

from control_engine import kernel_v31 as k


NOW = datetime(2026, 8, 30, 10, 0, tzinfo=timezone.utc)


def candidate(seed: str = "a", base: str = "b", pr: int = 1):
    return {
        "candidate_sha": seed * 40,
        "candidate_pr_number": pr,
        "candidate_head_branch": f"control/test-{seed}",
        "expected_base_branch": "main",
        "expected_base_sha": base * 40,
    }


def root(task_id="MISSION-M1-r1-G1", repo="o/r", created="2026-08-30T09:00:00Z"):
    return {
        "lifecycle_model": k.PROTOCOL_ID,
        "task_id": task_id,
        "operation": "IMPLEMENTATION",
        "role": k.ROLE_A,
        "repository": repo,
        "status": k.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "principal_manual_relay_count": 0,
        "created_at": created,
        "updated_at": created,
        "queued_at": created,
        "mission_id": "M1",
        "mission_revision": "r1",
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "gap_id": "G1",
        "integration_policy": "AUTO_AFTER_PASS",
        "acceptance": ["observable outcome"],
    }


def queue(*tasks):
    return {"version": "3.1", "principal_manual_relay_count": 0, "tasks": list(tasks)}


def claim_a(q, task_id="MISSION-M1-r1-G1", now=NOW, run="run-a"):
    return k.claim(
        q,
        task_id=task_id,
        worker_instance=k.INSTANCE_A1,
        authenticated_role=k.ROLE_A,
        now=now,
        run_id=run,
    )[0]


def record_a_completed(q, task_id="MISSION-M1-r1-G1", run="run-a", cand=None, now=NOW + timedelta(minutes=1)):
    cand = cand or candidate()
    return k.record(
        q,
        task_id=task_id,
        run_id=run,
        worker_instance=k.INSTANCE_A1,
        authenticated_role=k.ROLE_A,
        result={"task_id": task_id, "run_id": run, "role": k.ROLE_A, "outcome": "COMPLETED", "candidate": cand},
        result_ref=f"control/worker-results/{task_id}--{run}.json",
        now=now,
    )


def test_deterministic_auto_selection_uses_time_then_task_id():
    late = root(task_id="Z", repo="o/z", created="2026-08-30T09:01:00Z")
    b = root(task_id="B", repo="o/b")
    a = root(task_id="A", repo="o/a")
    assert k.select_task(queue(late, b, a), k.ROLE_A)["task_id"] == "A"


def test_authenticated_role_cannot_be_spoofed():
    with pytest.raises(k.KernelError, match="authenticated caller role"):
        k.claim(
            queue(root()),
            task_id="MISSION-M1-r1-G1",
            worker_instance=k.INSTANCE_B1,
            authenticated_role=k.ROLE_A,
            now=NOW,
        )


def test_claim_uses_one_fixed_lease_and_start_is_current():
    q, claimed = k.claim(
        queue(root()),
        task_id="MISSION-M1-r1-G1",
        worker_instance=k.INSTANCE_A1,
        authenticated_role=k.ROLE_A,
        now=NOW,
        run_id="run-a",
    )
    assert claimed["claim"]["expires_at"] == "2026-08-30T11:30:00Z"
    assert k.assert_current_claim(
        q,
        task_id=claimed["task_id"],
        run_id="run-a",
        worker_instance=k.INSTANCE_A1,
        authenticated_role=k.ROLE_A,
        now=NOW + timedelta(minutes=1),
    )["status"] == k.STATUS_EXECUTING
    with pytest.raises(k.KernelError, match="one fixed lease"):
        k.claim(
            queue(root()),
            task_id="MISSION-M1-r1-G1",
            worker_instance=k.INSTANCE_A1,
            authenticated_role=k.ROLE_A,
            now=NOW,
            lease_seconds=60,
        )


def test_release_requeues_same_task_without_semantic_result_or_successor():
    q = claim_a(queue(root()))
    q = k.release(
        q,
        task_id="MISSION-M1-r1-G1",
        run_id="run-a",
        worker_instance=k.INSTANCE_A1,
        authenticated_role=k.ROLE_A,
        reason="EXECUTION_UNAVAILABLE",
        now=NOW + timedelta(minutes=1),
    )
    assert len(q["tasks"]) == 1
    t = q["tasks"][0]
    assert t["status"] == k.STATUS_QUEUED
    assert t["claim"] is None
    assert t["result_ref"] is None
    assert t["last_execution_error"] == "EXECUTION_UNAVAILABLE"


def test_late_record_is_rejected_not_resurrected():
    q = claim_a(queue(root()))
    with pytest.raises(k.KernelError, match="claim expired"):
        record_a_completed(q, now=NOW + timedelta(seconds=k.LEASE_SECONDS + 1))


def test_a_record_terminalizes_and_materializes_exactly_one_assurance():
    q = claim_a(queue(root()))
    q, successor_id = record_a_completed(q)
    predecessor = next(t for t in q["tasks"] if t["task_id"] == "MISSION-M1-r1-G1")
    successor = next(t for t in q["tasks"] if t["task_id"] == successor_id)
    assert predecessor["status"] == k.STATUS_TERMINAL
    assert predecessor["outcome"] == "COMPLETED"
    assert predecessor["claim"] is None
    assert successor["operation"] == "ASSURANCE"
    assert successor["candidate"] == candidate()
    assert len([t for t in q["tasks"] if t["operation"] == "ASSURANCE"]) == 1


def test_b_pass_has_no_semantic_integration_successor():
    q = claim_a(queue(root()))
    q, b_id = record_a_completed(q)
    q, _ = k.claim(
        q,
        task_id=b_id,
        worker_instance=k.INSTANCE_B1,
        authenticated_role=k.ROLE_B,
        now=NOW + timedelta(minutes=2),
        run_id="run-b",
    )
    q, successor = k.record(
        q,
        task_id=b_id,
        run_id="run-b",
        worker_instance=k.INSTANCE_B1,
        authenticated_role=k.ROLE_B,
        result={"task_id": b_id, "run_id": "run-b", "role": k.ROLE_B, "outcome": "PASS", "candidate": candidate()},
        result_ref=f"control/worker-results/{b_id}--run-b.json",
        now=NOW + timedelta(minutes=3),
    )
    assert successor is None
    b = next(t for t in q["tasks"] if t["task_id"] == b_id)
    assert b["integration_state"] == "PENDING"
    assert all(t["operation"] != "PROJECT_INTEGRATION" for t in q["tasks"] if t.get("lifecycle_model") == k.PROTOCOL_ID)


def test_hold_after_pass_never_becomes_pending_auto_integration():
    t = root()
    t["integration_policy"] = "HOLD_AFTER_PASS"
    q = claim_a(queue(t))
    q, b_id = record_a_completed(q)
    q, _ = k.claim(q, task_id=b_id, worker_instance=k.INSTANCE_B1, authenticated_role=k.ROLE_B, now=NOW + timedelta(minutes=2), run_id="run-b")
    q, _ = k.record(
        q,
        task_id=b_id,
        run_id="run-b",
        worker_instance=k.INSTANCE_B1,
        authenticated_role=k.ROLE_B,
        result={"task_id": b_id, "run_id": "run-b", "role": k.ROLE_B, "outcome": "PASS", "candidate": candidate()},
        result_ref="control/worker-results/b.json",
        now=NOW + timedelta(minutes=3),
    )
    assert next(t for t in q["tasks"] if t["task_id"] == b_id)["integration_state"] == "HOLD"


def test_b_fail_repair_requires_fresh_candidate_then_fresh_assurance():
    q = claim_a(queue(root()))
    q, b_id = record_a_completed(q, cand=candidate("a", "b", 1))
    q, _ = k.claim(q, task_id=b_id, worker_instance=k.INSTANCE_B1, authenticated_role=k.ROLE_B, now=NOW + timedelta(minutes=2), run_id="run-b")
    q, repair_id = k.record(
        q,
        task_id=b_id,
        run_id="run-b",
        worker_instance=k.INSTANCE_B1,
        authenticated_role=k.ROLE_B,
        result={"task_id": b_id, "run_id": "run-b", "role": k.ROLE_B, "outcome": "FAIL", "candidate": candidate("a", "b", 1)},
        result_ref="control/worker-results/fail.json",
        now=NOW + timedelta(minutes=3),
    )
    q, _ = k.claim(q, task_id=repair_id, worker_instance=k.INSTANCE_A1, authenticated_role=k.ROLE_A, now=NOW + timedelta(minutes=4), run_id="run-r")
    with pytest.raises(k.KernelError, match="fresh candidate"):
        k.record(
            q,
            task_id=repair_id,
            run_id="run-r",
            worker_instance=k.INSTANCE_A1,
            authenticated_role=k.ROLE_A,
            result={"task_id": repair_id, "run_id": "run-r", "role": k.ROLE_A, "outcome": "COMPLETED", "candidate": candidate("a", "b", 1)},
            result_ref="control/worker-results/repair-old.json",
            now=NOW + timedelta(minutes=5),
        )
    q, fresh_b = k.record(
        q,
        task_id=repair_id,
        run_id="run-r",
        worker_instance=k.INSTANCE_A1,
        authenticated_role=k.ROLE_A,
        result={"task_id": repair_id, "run_id": "run-r", "role": k.ROLE_A, "outcome": "COMPLETED", "candidate": candidate("c", "b", 1)},
        result_ref="control/worker-results/repair-new.json",
        now=NOW + timedelta(minutes=5),
    )
    assert next(t for t in q["tasks"] if t["task_id"] == fresh_b)["candidate"]["candidate_sha"] == "c" * 40


def test_assurance_candidate_envelope_mismatch_is_rejected():
    q = claim_a(queue(root()))
    q, b_id = record_a_completed(q)
    q, _ = k.claim(q, task_id=b_id, worker_instance=k.INSTANCE_B1, authenticated_role=k.ROLE_B, now=NOW + timedelta(minutes=2), run_id="run-b")
    wrong = candidate("c", "b", 1)
    with pytest.raises(k.KernelError, match="candidate envelope mismatch"):
        k.record(
            q,
            task_id=b_id,
            run_id="run-b",
            worker_instance=k.INSTANCE_B1,
            authenticated_role=k.ROLE_B,
            result={"task_id": b_id, "run_id": "run-b", "role": k.ROLE_B, "outcome": "PASS", "candidate": wrong},
            result_ref="control/worker-results/bad.json",
            now=NOW + timedelta(minutes=3),
        )


def test_reconcile_expired_claim_requeues_and_never_invents_result():
    q = claim_a(queue(root()))
    q, report = k.reconcile(q, now=NOW + timedelta(seconds=k.LEASE_SECONDS + 1))
    t = q["tasks"][0]
    assert report["expired_claims"] == [t["task_id"]]
    assert t["status"] == k.STATUS_QUEUED
    assert t["result_ref"] is None


def test_reconcile_superseded_revision_revokes_active_claim():
    q = claim_a(queue(root()))
    q, report = k.reconcile(q, now=NOW + timedelta(minutes=1), active_missions={"M1": "r2"})
    assert report["superseded_claims"] == ["MISSION-M1-r1-G1"]
    assert q["tasks"][0]["status"] == k.STATUS_SUPERSEDED
    assert q["tasks"][0]["claim"] is None


def mission(gaps, mission_id="M1", revision="r1", repository="o/r"):
    return {
        "mission": {
            "mission_id": mission_id,
            "mission_revision": revision,
            "repository": repository,
            "gaps": gaps,
        },
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
    }


def gap(gap_id, deps=()):
    return {
        "gap_id": gap_id,
        "gap_state": "OPEN",
        "depends_on": list(deps),
        "repository": "o/r",
        "operation": "IMPLEMENTATION",
        "acceptance": [f"{gap_id} outcome"],
        "integration_policy": "AUTO_AFTER_PASS",
    }


def test_feed_is_idempotent_and_materializes_at_most_one_gap_per_mission():
    m = mission([gap("G1"), gap("G2")])
    q, created = k.feed(queue(), missions=[m], now=NOW)
    assert created == ["MISSION-M1-r1-G1"]
    q2, created2 = k.feed(q, missions=[m], now=NOW + timedelta(minutes=1))
    assert created2 == ["MISSION-M1-r1-G2"]
    q3, created3 = k.feed(q2, missions=[m], now=NOW + timedelta(minutes=2))
    assert created3 == []
    assert len(q3["tasks"]) == 2


def test_feed_respects_explicit_dependencies_without_planning():
    m = mission([gap("G2", deps=["G1"])])
    q, created = k.feed(queue(), missions=[m], now=NOW)
    assert created == []


def test_legacy_completed_integration_is_migration_fact_not_new_project_task():
    legacy = {
        "task_id": "MISSION-M1-r1-G1--ASSURE--INTEGRATE",
        "operation": "PROJECT_INTEGRATION",
        "status": "TERMINAL",
        "outcome": "COMPLETED",
    }
    m = mission([gap("G2", deps=["G1"])])
    q, created = k.feed(queue(legacy), missions=[m], now=NOW)
    assert created == ["MISSION-M1-r1-G2"]
    assert q["tasks"][-1]["operation"] == "IMPLEMENTATION"


def test_mark_integrated_makes_gap_satisfied_for_next_feed():
    q = claim_a(queue(root()))
    q, b_id = record_a_completed(q)
    q, _ = k.claim(q, task_id=b_id, worker_instance=k.INSTANCE_B1, authenticated_role=k.ROLE_B, now=NOW + timedelta(minutes=2), run_id="run-b")
    q, _ = k.record(
        q,
        task_id=b_id,
        run_id="run-b",
        worker_instance=k.INSTANCE_B1,
        authenticated_role=k.ROLE_B,
        result={"task_id": b_id, "run_id": "run-b", "role": k.ROLE_B, "outcome": "PASS", "candidate": candidate()},
        result_ref="control/worker-results/pass.json",
        now=NOW + timedelta(minutes=3),
    )
    q = k.mark_integrated(q, assurance_task_id=b_id, merge_sha="d" * 40, merged_at=NOW + timedelta(minutes=4))
    assert k.gap_satisfied(q, "M1", "r1", "G1")


def test_base_drift_creates_exactly_one_repair():
    q = claim_a(queue(root()))
    q, b_id = record_a_completed(q)
    q, _ = k.claim(q, task_id=b_id, worker_instance=k.INSTANCE_B1, authenticated_role=k.ROLE_B, now=NOW + timedelta(minutes=2), run_id="run-b")
    q, _ = k.record(
        q,
        task_id=b_id,
        run_id="run-b",
        worker_instance=k.INSTANCE_B1,
        authenticated_role=k.ROLE_B,
        result={"task_id": b_id, "run_id": "run-b", "role": k.ROLE_B, "outcome": "PASS", "candidate": candidate()},
        result_ref="control/worker-results/pass.json",
        now=NOW + timedelta(minutes=3),
    )
    q, repair_id = k.materialize_base_drift_repair(q, assurance_task_id=b_id, now=NOW + timedelta(minutes=4))
    repair = next(t for t in q["tasks"] if t["task_id"] == repair_id)
    assert repair["reason"] == "BASE_DRIFT_AFTER_PASS"
    with pytest.raises(k.KernelError):
        k.materialize_base_drift_repair(q, assurance_task_id=b_id, now=NOW + timedelta(minutes=5))
