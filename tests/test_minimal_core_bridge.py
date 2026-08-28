import json
from pathlib import Path

import pytest

from control_engine import minimal_core as core
from scripts import private_minimal_core_apply as bridge


def test_cutover_blocks_legacy_owner_of_same_role():
    queue = {
        "tasks": [
            {
                "task_id": "LEGACY-B",
                "repository": "other/repo",
                "active_run_id": "run-legacy",
                "active_role": core.ROLE_B,
            }
        ]
    }
    with pytest.raises(RuntimeError, match="legacy role claim"):
        bridge._assert_no_legacy_conflict(queue, core.ROLE_B, "target/repo")


def test_cutover_blocks_legacy_owner_of_same_repository():
    queue = {
        "tasks": [
            {
                "task_id": "LEGACY-A",
                "repository": "target/repo",
                "active_run_id": "run-legacy",
                "active_role": core.ROLE_A,
            }
        ]
    }
    with pytest.raises(RuntimeError, match="legacy repository claim"):
        bridge._assert_no_legacy_conflict(queue, core.ROLE_B, "target/repo")


def test_cutover_ignores_inactive_legacy_history():
    queue = {
        "tasks": [
            {
                "task_id": "LEGACY-HISTORY",
                "repository": "target/repo",
                "active_run_id": None,
                "active_role": None,
            }
        ]
    }
    bridge._assert_no_legacy_conflict(queue, core.ROLE_B, "target/repo")


def _profile(status):
    return {
        "protocol_id": "CONTROL_ASSURANCE_EXECUTION_PROFILE_V1",
        "version": "1.0",
        "status": status,
        "lifecycle_authority": {
            "role": core.ROLE_B,
            "worker_instance": core.INSTANCE_B1,
        },
        "principal_manual_relay_count": 0,
    }


def _write_record_fixture(tmp_path, *, expires_at, outcome):
    task_id = "ASSURE-RECORD"
    run_id = "run-record"
    queue_path = tmp_path / bridge.QUEUE_REL
    queue_path.parent.mkdir(parents=True)
    candidate_sha = "a" * 40
    repository = "market-predictions/control-engine"
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "lifecycle_model": core.PROTOCOL_ID,
                "task_id": task_id,
                "operation": "ASSURANCE",
                "role": core.ROLE_B,
                "repository": repository,
                "priority": 0,
                "candidate_sha": candidate_sha,
                "status": core.STATUS_EXECUTING,
                "outcome": None,
                "claim": {
                    "run_id": run_id,
                    "role": core.ROLE_B,
                    "worker_instance": core.INSTANCE_B1,
                    "backend": "test",
                    "started_at": "2026-08-28T06:00:00Z",
                    "expires_at": expires_at,
                },
                "result_ref": None,
                "terminal_run_id": None,
                "attempt_count": 1,
                "last_execution_error": None,
                "successor_by_outcome": {
                    "PASS": {
                        "task_id": f"{task_id}--INTEGRATE",
                        "operation": "PROJECT_INTEGRATION",
                        "role": core.ROLE_A,
                        "repository": repository,
                        "candidate_sha": candidate_sha,
                    },
                    "FAIL": {
                        "task_id": f"{task_id}--REPAIR",
                        "operation": "REPAIR",
                        "role": core.ROLE_A,
                        "repository": repository,
                        "candidate_sha": candidate_sha,
                    },
                },
                "principal_manual_relay_count": 0,
                "created_at": "2026-08-28T05:00:00Z",
                "updated_at": "2026-08-28T06:00:00Z",
            }
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    profile = tmp_path / bridge.LEGACY_B1_PROFILE_REL
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(json.dumps(_profile(bridge.LEGACY_B1_RETIRED_STATUS)), encoding="utf-8")
    result_path = tmp_path / bridge._result_ref(task_id, run_id)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "task_id": task_id,
                "run_id": run_id,
                "role": core.ROLE_B,
                "outcome": outcome,
                "candidate_sha": candidate_sha,
            }
        ),
        encoding="utf-8",
    )
    return task_id, queue_path


def _run_record_mutation(tmp_path, queue_path, monkeypatch, task_id):
    def fake_with_cas(token, mutate, *, message):
        value = mutate(tmp_path)
        return value, json.loads(queue_path.read_text(encoding="utf-8")), 1

    monkeypatch.setattr(bridge, "_with_cas", fake_with_cas)
    assert bridge.command_record("token", task_id) == 0
    return json.loads(queue_path.read_text(encoding="utf-8"))["tasks"][0]


def test_minimal_core_cutover_requires_explicit_valid_legacy_b1_retirement(tmp_path):
    profile = tmp_path / bridge.LEGACY_B1_PROFILE_REL
    queue = {"tasks": [{"lifecycle_model": core.PROTOCOL_ID, "task_id": "CORE"}]}

    with pytest.raises(RuntimeError, match="profile is required"):
        bridge._assert_cutover_safe(tmp_path, queue)

    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps(_profile("ACTIVE")), encoding="utf-8")
    with pytest.raises(RuntimeError, match="valid and RETIRED"):
        bridge._assert_cutover_safe(tmp_path, queue)

    profile.write_text(json.dumps(_profile("CANDIDATE_GATE8")), encoding="utf-8")
    with pytest.raises(RuntimeError, match="valid and RETIRED"):
        bridge._assert_cutover_safe(tmp_path, queue)

    profile.write_text(json.dumps(_profile(bridge.LEGACY_B1_RETIRED_STATUS)), encoding="utf-8")
    bridge._assert_cutover_safe(tmp_path, queue)


def test_invalid_retired_profile_still_fails_closed(tmp_path):
    profile = tmp_path / bridge.LEGACY_B1_PROFILE_REL
    profile.parent.mkdir(parents=True)
    queue = {"tasks": [{"lifecycle_model": core.PROTOCOL_ID, "task_id": "CORE"}]}

    for invalid_relay in (1, False, 0.0, "0", None):
        invalid = _profile(bridge.LEGACY_B1_RETIRED_STATUS)
        invalid["principal_manual_relay_count"] = invalid_relay
        profile.write_text(json.dumps(invalid), encoding="utf-8")
        with pytest.raises(RuntimeError, match="valid and RETIRED"):
            bridge._assert_cutover_safe(tmp_path, queue)

    assert bridge._exact_integer_zero(0) is True
    assert bridge._exact_integer_zero(False) is False


def test_legacy_b1_workflow_uses_existing_profile_as_kill_switch():
    workflow = Path(".github/workflows/canonical-b1-dual-executor-v1.yml").read_text(encoding="utf-8")
    assert 'if [ "$status" != ACTIVE ]; then' in workflow
    assert "CANONICAL_B1=IDLE_PROFILE_" in workflow


def test_persisted_result_discovery_is_scoped_to_active_task_and_run(tmp_path):
    task_id = "CONTROL-204-ASSURE"
    queue = {
        "tasks": [
            {
                "lifecycle_model": core.PROTOCOL_ID,
                "task_id": task_id,
                "status": core.STATUS_EXECUTING,
                "claim": {"run_id": "run-new"},
            }
        ]
    }
    stale_ref = bridge._result_ref(task_id, "run-old")
    stale_path = tmp_path / stale_ref
    stale_path.parent.mkdir(parents=True)
    stale_path.write_text(json.dumps({"task_id": task_id, "run_id": "run-old"}), encoding="utf-8")
    assert bridge._persisted_results(tmp_path, queue) == {}

    current_ref = bridge._result_ref(task_id, "run-new")
    current_path = tmp_path / current_ref
    current_path.write_text(json.dumps({"task_id": task_id, "run_id": "run-new"}), encoding="utf-8")
    found = bridge._persisted_results(tmp_path, queue)
    assert list(found) == [(task_id, "run-new")]
    assert found[(task_id, "run-new")][1] == current_ref


def test_malformed_current_run_result_is_discovered_as_invalid_not_raised(tmp_path):
    task_id = "CONTROL-204-ASSURE"
    run_id = "run-bad-json"
    queue = {
        "tasks": [
            {
                "lifecycle_model": core.PROTOCOL_ID,
                "task_id": task_id,
                "status": core.STATUS_EXECUTING,
                "claim": {"run_id": run_id},
            }
        ]
    }
    ref = bridge._result_ref(task_id, run_id)
    path = tmp_path / ref
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")
    found = bridge._persisted_results(tmp_path, queue)
    assert found[(task_id, run_id)] == (None, ref)


def test_record_schema_invalid_object_requeues_current_claim(tmp_path, monkeypatch):
    task_id, queue_path = _write_record_fixture(
        tmp_path,
        expires_at="2099-08-28T07:00:00Z",
        outcome="NOT_A_VERDICT",
    )
    current = _run_record_mutation(tmp_path, queue_path, monkeypatch, task_id)
    assert current["status"] == core.STATUS_QUEUED
    assert current["claim"] is None
    assert current["last_execution_error"] == "INVALID_PERSISTED_RESULT"


def test_record_valid_result_after_expiry_requeues_as_lease_expired(tmp_path, monkeypatch):
    task_id, queue_path = _write_record_fixture(
        tmp_path,
        expires_at="2026-08-28T06:00:01Z",
        outcome="PASS",
    )
    current = _run_record_mutation(tmp_path, queue_path, monkeypatch, task_id)
    assert current["status"] == core.STATUS_QUEUED
    assert current["claim"] is None
    assert current["last_execution_error"] == "LEASE_EXPIRED"


def test_cas_returns_only_value_from_winning_attempt(monkeypatch):
    attempts = {"mutate": 0, "persist": 0}

    monkeypatch.setattr(bridge, "_init_state", lambda state_dir: None)
    monkeypatch.setattr(bridge.integration, "_reset_state", lambda token, state_dir: None)
    monkeypatch.setattr(bridge.integration, "_identity", lambda state_dir: ("ref", "blob"))
    monkeypatch.setattr(
        bridge,
        "_load",
        lambda path: {"version": "1.0", "principal_manual_relay_count": 0, "tasks": []},
    )

    def fake_mutate(state_dir):
        attempts["mutate"] += 1
        return {"idle": attempts["mutate"] == 1, "attempt": attempts["mutate"]}

    def fake_persist(token, state_dir, observed, message):
        attempts["persist"] += 1
        return attempts["persist"] == 2

    monkeypatch.setattr(bridge, "_persist", fake_persist)
    value, _, attempt = bridge._with_cas("token", fake_mutate, message="test")
    assert attempt == 2
    assert value == {"idle": False, "attempt": 2}
