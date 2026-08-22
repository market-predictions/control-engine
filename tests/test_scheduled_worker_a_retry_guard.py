from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from control_engine import scheduled_worker_a_retry_guard as guard


def _write_intake(path: Path, *, task_id: str, revision: str, candidate: str, supersedes: str | None = None) -> None:
    intent = {
        "task_id": task_id,
        "revision": revision,
        "operation": "ASSURANCE",
        "candidate_sha": candidate,
        "handover_id": "H2",
    }
    if supersedes is not None:
        intent["supersedes_revision"] = supersedes
    path.write_text(json.dumps({"queue_intent": intent}), encoding="utf-8")


def _task(task_id: str, revision: str, candidate: str, *, maximum: int = 3) -> dict:
    return {
        "task_id": task_id,
        "intake_revision": revision,
        "operation": "ASSURANCE",
        "candidate_sha": candidate,
        "handover_id": "H2",
        "last_verdict": "NONE",
        "assurance_result_ref": None,
        "max_attempts": maximum,
    }


def test_one_shot_assurance_never_synthesizes_retry(tmp_path: Path) -> None:
    queue = tmp_path / "DISPATCH_QUEUE.json"
    intake = tmp_path / "project-intake"
    intake.mkdir()
    candidate = "a" * 40
    _write_intake(intake / "source.json", task_id="ONE-SHOT", revision="ONE-SHOT-R1", candidate=candidate)
    task = _task("ONE-SHOT", "ONE-SHOT-R1", candidate, maximum=1)
    called = False

    def original(_queue_path, _task):
        nonlocal called
        called = True
        return "ONE-SHOT-R2"

    result = guard._guarded_retry_factory(original)(str(queue), task)
    assert result is None
    assert called is False


def test_explicit_successor_suppresses_parallel_auto_retry(tmp_path: Path) -> None:
    queue = tmp_path / "DISPATCH_QUEUE.json"
    intake = tmp_path / "project-intake"
    intake.mkdir()
    candidate = "b" * 40
    _write_intake(intake / "source.json", task_id="SOURCE", revision="SOURCE-R1", candidate=candidate)
    _write_intake(
        intake / "explicit.json",
        task_id="SOURCE-COMPLETION-DIAG",
        revision="SOURCE-COMPLETION-DIAG",
        supersedes="SOURCE-R1",
        candidate=candidate,
    )
    task = _task("SOURCE", "SOURCE-R1", candidate)
    called = False

    def original(_queue_path, _task):
        nonlocal called
        called = True
        return "SOURCE-R2"

    result = guard._guarded_retry_factory(original)(str(queue), task)
    assert result is None
    assert called is False


def test_multiple_explicit_successors_fail_closed(tmp_path: Path) -> None:
    queue = tmp_path / "DISPATCH_QUEUE.json"
    intake = tmp_path / "project-intake"
    intake.mkdir()
    candidate = "c" * 40
    _write_intake(intake / "source.json", task_id="SOURCE", revision="SOURCE-R1", candidate=candidate)
    for name in ("A", "B"):
        _write_intake(
            intake / f"{name}.json",
            task_id=f"EXPLICIT-{name}",
            revision=f"EXPLICIT-{name}",
            supersedes="SOURCE-R1",
            candidate=candidate,
        )
    task = _task("SOURCE", "SOURCE-R1", candidate)

    with pytest.raises(guard.base.ActuatorContractError, match="multiple explicit assurance successors"):
        guard._guarded_retry_factory(lambda *_: "SOURCE-R2")(str(queue), task)


def test_existing_parallel_auto_retry_is_blocked_in_favor_of_explicit_successor(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "DISPATCH_QUEUE.json"
    intake = tmp_path / "project-intake"
    intake.mkdir()
    candidate = "d" * 40
    _write_intake(intake / "source.json", task_id="SOURCE", revision="SOURCE-R1", candidate=candidate)
    _write_intake(
        intake / "auto.json",
        task_id="SOURCE-R2",
        revision="SOURCE-R2",
        supersedes="SOURCE-R1",
        candidate=candidate,
    )
    _write_intake(
        intake / "explicit.json",
        task_id="SOURCE-COMPLETION-DIAG",
        revision="SOURCE-COMPLETION-DIAG",
        supersedes="SOURCE-R1",
        candidate=candidate,
    )
    queue = {
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "SOURCE-R2",
                "intake_revision": "SOURCE-R2",
                "state": "ASSURANCE_QUEUED",
                "candidate_sha": candidate,
                "handover_id": "H2",
                "last_findings": [],
                "active_run_id": None,
                "active_role": None,
                "active_worker_instance": None,
                "claim_started_at": None,
                "claim_expires_at": None,
            }
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    class Dispatcher:
        @staticmethod
        def transition(task, state):
            updated = dict(task)
            updated["state"] = state
            return updated

    parallel = SimpleNamespace(validate_parallel_queue=lambda _queue: None)
    monkeypatch.setattr(
        guard.base,
        "_private_modules",
        lambda _code_dir: (parallel, SimpleNamespace(), Dispatcher),
    )

    blocked = guard._block_parallel_auto_successors("unused", str(queue_path))
    after = json.loads(queue_path.read_text(encoding="utf-8"))["tasks"][0]
    assert blocked == ["SOURCE-R2"]
    assert after["state"] == "BLOCKED"
    assert after["active_run_id"] is None
    assert after["last_findings"] == [
        "Auto-generated assurance retry superseded by explicit canonical successor SOURCE-COMPLETION-DIAG."
    ]
