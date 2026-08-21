from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_engine import scheduled_worker_a as worker_a
from control_engine import scheduled_worker_b as worker_b


class FakeDispatcherState:
    @staticmethod
    def resume_unavailable(task):
        result = dict(task)
        if result.get("attempt", 0) >= result.get("max_attempts", 0):
            result["state"] = "BLOCKED"
        else:
            result["state"] = result["resume_state"]
        result["resume_state"] = None
        return result

    @staticmethod
    def transition(task, new_state):
        result = dict(task)
        result["state"] = new_state
        return result


class FakeParallel:
    INSTANCE_A1 = "A1"
    INSTANCE_B1 = "B1"

    @staticmethod
    def validate_parallel_queue(queue):
        return None


def _task(task_id: str, state: str, attempt: int, maximum: int) -> dict:
    return {
        "task_id": task_id,
        "state": state,
        "attempt": attempt,
        "max_attempts": maximum,
        "resume_state": None,
        "active_run_id": None,
        "active_role": None,
        "active_worker_instance": None,
        "claim_started_at": None,
        "claim_expires_at": None,
        "last_findings": [],
    }


def test_a_reconciliation_blocks_all_inactive_exhausted_queued_roles(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            _task("a-impl", "IMPLEMENTATION_QUEUED", 3, 3),
            _task("a-repair", "REPAIR_QUEUED", 4, 4),
            _task("b-assure", "ASSURANCE_QUEUED", 3, 3),
            _task("retryable", "ASSURANCE_QUEUED", 2, 3),
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    queue_mod = SimpleNamespace(ROLE_A="implementation_operations")
    monkeypatch.setattr(
        worker_a,
        "_private_modules",
        lambda _code_dir: (FakeParallel, queue_mod, FakeDispatcherState),
    )

    report = tmp_path / "report.json"
    worker_a.resume_a_unavailable("unused", str(queue_path), str(report))

    after = json.loads(queue_path.read_text(encoding="utf-8"))
    states = {task["task_id"]: task["state"] for task in after["tasks"]}
    assert states == {
        "a-impl": "BLOCKED",
        "a-repair": "BLOCKED",
        "b-assure": "BLOCKED",
        "retryable": "ASSURANCE_QUEUED",
    }
    for task in after["tasks"][:3]:
        assert task["last_findings"][-1] == "Attempt budget exhausted during scheduled reconciliation."
    assert json.loads(report.read_text(encoding="utf-8"))["blocked"] == [
        "a-impl",
        "a-repair",
        "b-assure",
    ]


def test_b_selection_fails_closed_if_private_selector_returns_exhausted(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps({"tasks": []}), encoding="utf-8")
    exhausted = {
        "task_id": "b-exhausted",
        "attempt": 3,
        "max_attempts": 3,
        "repository": "example/repo",
        "candidate_sha": "a" * 40,
        "candidate_pr": 1,
        "governance_issue": 1,
        "state": "ASSURANCE_QUEUED",
    }
    parallel = SimpleNamespace(
        INSTANCE_B1="B1",
        select_task_for_instance=lambda queue, role, worker: exhausted,
    )
    queue_mod = SimpleNamespace(ROLE_B="governance_release_assurance")
    monkeypatch.setattr(worker_b, "_private_modules", lambda _code_dir: (parallel, queue_mod))

    with pytest.raises(worker_b.ActuatorContractError, match="attempt-exhausted B task"):
        worker_b.select_b1("unused", str(queue_path), str(tmp_path / "selection.json"))
