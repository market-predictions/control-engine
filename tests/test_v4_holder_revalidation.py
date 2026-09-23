from datetime import datetime, timezone

from scripts import control_v4_runtime_carrier as carrier


NOW = datetime(2026, 9, 23, 19, 30, 41, tzinfo=timezone.utc)
RUN_ID = "v4:test-holder-revalidation"
TASK_ID = "MISSION--WEEKLY_ETF_EU--2026-09-16-r6--WEEU-GOLDEN-PATH-20"
CANDIDATE_SHA = "1" * 40
BASE_SHA = "2" * 40
MISSION_SHA = "3" * 40
AUTHORITY_SHA = "4" * 40


def locked_repair_queue() -> dict:
    candidate = {
        "candidate_sha": CANDIDATE_SHA,
        "candidate_pr_number": 128,
        "candidate_head_branch": "recovery/v6-golden-path-20",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": {
            "run_id": RUN_ID,
            "task_id": TASK_ID,
            "started_at": "2026-09-23T19:29:36Z",
            "expires_at": "2026-09-23T20:59:36Z",
        },
        "migration_facts": [],
        "tasks": [{
            "task_id": TASK_ID,
            "mission_id": "WEEKLY_ETF_EU",
            "mission_revision": "2026-09-16-r6",
            "mission_contract_blob_sha": MISSION_SHA,
            "repository_authority_blob_sha": AUTHORITY_SHA,
            "gap_id": "WEEU-GOLDEN-PATH-20",
            "repository": "market-predictions/weekly-etf-eu",
            "acceptance": ["Prove the exact golden path."],
            "integration_policy": "HOLD_AFTER_PASS",
            "review_policy": "EXTERNAL",
            "convergence_required": False,
            "status": "ACTIVE",
            "phase": "REPAIR",
            "candidate": candidate,
            "last_review": None,
            "external_review": None,
            "blocker": None,
            "created_at": "2026-09-23T06:39:06Z",
            "updated_at": "2026-09-23T19:29:36Z",
        }],
    }


def state(queue: dict) -> dict:
    return {
        "queue": queue,
        "runtime_enabled": True,
        "integration_enabled": False,
        "main_sha": "5" * 40,
        "runtime_sha": "6" * 40,
        "queue_blob": "7" * 40,
        "repository_node_id": "R_test",
    }


def test_same_run_holder_revalidation_has_no_target_network_dependency(monkeypatch) -> None:
    queue = locked_repair_queue()

    def unexpected_target_read(*_args, **_kwargs):
        raise AssertionError("same-run holder revalidation must not read target network")

    monkeypatch.setattr(carrier, "_target_pr_candidate", unexpected_target_read)
    monkeypatch.setattr(carrier, "_assert_public_target_repository", unexpected_target_read)

    current_state = state(queue)
    returned_state, result = carrier._tick(
        {"kind": "TICK", "run_id": RUN_ID, "yielded_task_tokens": []},
        current_state,
        now=NOW,
    )

    assert returned_state is current_state
    assert result["result"] == "WORK"
    assert result["run_id"] == RUN_ID
    assert result["action"] == "REPAIR"
    assert result["repository"] == "market-predictions/weekly-etf-eu"
    assert result["candidate"]["candidate_sha"] == CANDIDATE_SHA
    assert result["candidate"]["expected_base_sha"] == BASE_SHA
    assert "live_candidate" not in result


def test_other_run_still_gets_busy_without_target_network(monkeypatch) -> None:
    queue = locked_repair_queue()

    def unexpected_target_read(*_args, **_kwargs):
        raise AssertionError("BUSY path must not read target network")

    monkeypatch.setattr(carrier, "_target_pr_candidate", unexpected_target_read)
    returned_state, result = carrier._tick(
        {"kind": "TICK", "run_id": "v4:other-run", "yielded_task_tokens": []},
        state(queue),
        now=NOW,
    )

    assert returned_state["queue"] == queue
    assert result == {
        "protocol": "CONTROL_V4_RUNTIME_RESULT_V1",
        "result": "BUSY",
        "run_id": "v4:other-run",
    }
