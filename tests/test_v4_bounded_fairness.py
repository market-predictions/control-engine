from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from control_engine.v4_runtime_protocol import (
    bind_public_event_to_holder,
    safe_work_capsule,
    select_task_id_v4,
    task_token,
    yield_holder_v4,
)

NOW = datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)
BASE_SHA = "c" * 40
MISSION_BLOB = "d" * 40
AUTHORITY_BLOB = "e" * 40


def candidate(seed: str) -> dict:
    return {
        "candidate_sha": seed * 40,
        "candidate_pr_number": 1,
        "candidate_head_branch": f"candidate-{seed}",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def task(task_id: str, gap_id: str, updated_at: str, *, seed: str) -> dict:
    return {
        "task_id": task_id,
        "mission_id": "M",
        "mission_revision": "2026-09-19-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": gap_id,
        "repository": "example/repo",
        "acceptance": ["objective acceptance"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": candidate(seed),
        "last_review": None,
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-18T20:00:00Z",
        "updated_at": updated_at,
    }


def queue(tasks: list[dict], *, lock: dict | None = None) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": [],
        "tasks": tasks,
    }


def test_selection_is_oldest_updated_at_not_file_order() -> None:
    newer = task("TASK-B", "G2", "2026-09-18T22:00:00Z", seed="b")
    older = task("TASK-A", "G1", "2026-09-18T21:00:00Z", seed="a")
    q = queue([newer, older])

    assert select_task_id_v4(q, run_id="run-1", integration_enabled=False) == "TASK-A"


def test_selection_tie_breaks_by_exact_task_id() -> None:
    later_id = task("TASK-B", "G2", "2026-09-18T21:00:00Z", seed="b")
    earlier_id = task("TASK-A", "G1", "2026-09-18T21:00:00Z", seed="a")
    q = queue([later_id, earlier_id])

    assert select_task_id_v4(q, run_id="run-1", integration_enabled=False) == "TASK-A"


def test_yield_advances_only_holder_timestamp_and_releases_lock() -> None:
    held = task("TASK-A", "G1", "2026-09-18T21:00:00Z", seed="a")
    untouched = task("TASK-B", "G2", "2026-09-18T21:30:00Z", seed="b")
    q = queue(
        [held, untouched],
        lock={
            "run_id": "run-1",
            "task_id": "TASK-A",
            "started_at": "2026-09-18T22:30:00Z",
            "expires_at": "2026-09-19T00:00:00Z",
        },
    )
    capsule = safe_work_capsule(q, task_id="TASK-A", run_id="run-1")
    command = {
        "kind": "EVENT",
        "run_id": "run-1",
        "task_token": capsule["task_token"],
        "event": "YIELD",
        "repository": capsule["repository"],
        "action": capsule["action"],
        "candidate": capsule["candidate"],
    }
    bound = bind_public_event_to_holder(q, command)

    result = yield_holder_v4(q, bound, now=NOW)

    assert result["execution_lock"] is None
    assert result["tasks"][0]["updated_at"] == "2026-09-19T00:00:00Z"
    assert result["tasks"][1] == untouched
    assert q["tasks"][0]["updated_at"] == "2026-09-18T21:00:00Z"


def test_yield_rotation_and_invocation_token_exclusion_are_composable() -> None:
    first = task("TASK-A", "G1", "2026-09-18T21:00:00Z", seed="a")
    second = task("TASK-B", "G2", "2026-09-18T21:30:00Z", seed="b")
    q = queue(
        [first, second],
        lock={
            "run_id": "run-1",
            "task_id": "TASK-A",
            "started_at": "2026-09-18T22:30:00Z",
            "expires_at": "2026-09-19T00:00:00Z",
        },
    )
    capsule = safe_work_capsule(q, task_id="TASK-A", run_id="run-1")
    bound = bind_public_event_to_holder(
        q,
        {
            "kind": "EVENT",
            "run_id": "run-1",
            "task_token": capsule["task_token"],
            "event": "YIELD",
            "repository": capsule["repository"],
            "action": capsule["action"],
            "candidate": capsule["candidate"],
        },
    )
    released = yield_holder_v4(q, bound, now=NOW)

    assert select_task_id_v4(released, run_id="run-2", integration_enabled=False) == "TASK-B"

    token_b = task_token(second, "run-2")
    assert select_task_id_v4(
        released,
        run_id="run-2",
        yielded_task_tokens=[token_b],
        integration_enabled=False,
    ) == "TASK-A"


def test_selection_does_not_mutate_queue_schema_or_task_order() -> None:
    first = task("TASK-B", "G2", "2026-09-18T22:00:00Z", seed="b")
    second = task("TASK-A", "G1", "2026-09-18T21:00:00Z", seed="a")
    q = queue([first, second])
    before = deepcopy(q)

    assert select_task_id_v4(q, run_id="run-1", integration_enabled=False) == "TASK-A"
    assert q == before
    assert [item["task_id"] for item in q["tasks"]] == ["TASK-B", "TASK-A"]
