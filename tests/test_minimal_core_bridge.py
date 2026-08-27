import json

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
