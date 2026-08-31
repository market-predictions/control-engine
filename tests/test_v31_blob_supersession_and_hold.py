from datetime import datetime, timezone

from control_engine import kernel_v31 as core

NOW = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)
REVISION = "2026-08-31-r1"


def queue(*tasks):
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [],
        "tasks": list(tasks),
    }


def implementation_task():
    return {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": core.deterministic_root_id("M1", REVISION, "G1"),
        "operation": "IMPLEMENTATION",
        "role": core.ROLE_A,
        "repository": "owner/repo",
        "status": core.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-31T08:00:00Z",
        "updated_at": "2026-08-31T08:00:00Z",
        "queued_at": "2026-08-31T08:00:00Z",
        "mission_id": "M1",
        "mission_revision": REVISION,
        "mission_contract_blob_sha": "a" * 40,
        "repository_authority_blob_sha": "c" * 40,
        "gap_id": "G1",
        "integration_policy": "AUTO_AFTER_PASS",
        "acceptance": ["done"],
    }


def assurance_task():
    return {
        **implementation_task(),
        "task_id": core.deterministic_root_id("M1", REVISION, "G1") + "--ASSURANCE-aaaaaaaaaaaa",
        "operation": "ASSURANCE",
        "role": core.ROLE_B,
        "status": core.STATUS_TERMINAL,
        "outcome": "PASS",
        "result_ref": "control/worker-results/result.json",
        "terminal_run_id": "run-b1",
        "candidate": {
            "candidate_sha": "1" * 40,
            "candidate_pr_number": 7,
            "candidate_head_branch": "control/candidate",
            "expected_base_branch": "main",
            "expected_base_sha": "2" * 40,
        },
        "integration_state": "PENDING",
    }


def test_reconcile_supersedes_queued_task_when_frozen_mission_blob_is_stale():
    original = implementation_task()
    reconciled, report = core.reconcile(
        queue(original),
        now=NOW,
        active_missions={"M1": REVISION},
        active_gaps={("M1", REVISION, "G1")},
        active_mission_blobs={("M1", REVISION): "b" * 40},
    )

    assert report["superseded_claims"] == [original["task_id"]]
    assert reconciled["tasks"][0]["status"] == core.STATUS_SUPERSEDED
    assert reconciled["tasks"][0]["claim"] is None


def test_reconcile_keeps_exact_active_mission_blob_claimable():
    original = implementation_task()
    reconciled, report = core.reconcile(
        queue(original),
        now=NOW,
        active_missions={"M1": REVISION},
        active_gaps={("M1", REVISION, "G1")},
        active_mission_blobs={("M1", REVISION): "a" * 40},
    )

    assert report["superseded_claims"] == []
    assert reconciled["tasks"][0]["status"] == core.STATUS_QUEUED


def test_recovery_hold_reuses_existing_integration_state_without_new_runtime_model():
    original = assurance_task()
    held = core.mark_integration_hold(queue(original), assurance_task_id=original["task_id"], held_at=NOW)

    assert held["tasks"][0]["integration_state"] == "HOLD"
    assert held["tasks"][0]["status"] == core.STATUS_TERMINAL
    assert held["tasks"][0]["outcome"] == "PASS"
