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
