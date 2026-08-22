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


def _install_fake_private_modules(monkeypatch) -> None:
    queue_mod = SimpleNamespace(ROLE_A="implementation_operations")
    monkeypatch.setattr(
        worker_a,
        "_private_modules",
        lambda _code_dir: (FakeParallel, queue_mod, FakeDispatcherState),
    )


def test_a_reconciliation_blocks_all_inactive_exhausted_queued_roles(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "queue.json"
    b_assure = _task("b-assure", "ASSURANCE_QUEUED", 3, 3)
    b_assure.update({"operation": "ASSURANCE", "last_verdict": "PASS"})
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            _task("a-impl", "IMPLEMENTATION_QUEUED", 3, 3),
            _task("a-repair", "REPAIR_QUEUED", 4, 4),
            b_assure,
            _task("retryable", "ASSURANCE_QUEUED", 2, 3),
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    _install_fake_private_modules(monkeypatch)

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


def test_already_blocked_verdictless_r2_materializes_r3_intake_and_handover(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "DISPATCH_QUEUE.json"
    intake_dir = tmp_path / "project-intake"
    handover_dir = tmp_path / "handovers"
    intake_dir.mkdir()
    handover_dir.mkdir()
    source_task_id = "CONTROL-193-PR194-ASSURE-R2"
    candidate = "e9ec2ba1f4339a44e15d70548317bddacb8e7faf"
    source = _task(source_task_id, "BLOCKED", 3, 3)
    source.update(
        {
            "operation": "ASSURANCE",
            "candidate_pr": 194,
            "candidate_sha": candidate,
            "last_verdict": "NONE",
            "assurance_result_ref": None,
            "last_findings": ["Attempt budget exhausted during scheduled reconciliation."],
        }
    )
    queue_path.write_text(
        json.dumps({"version": "1.0", "principal_manual_relay_count": 0, "tasks": [source]}),
        encoding="utf-8",
    )
    intake = {
        "version": "1.0",
        "project_id": "CONTROL_193_PR194_ASSURE_R2",
        "repository": "market-predictions/control-plane",
        "managed": True,
        "status": "ASSURANCE_READY",
        "principal_manual_relay_count": 0,
        "queue_intent": {
            "revision": source_task_id,
            "supersedes_revision": "CONTROL-193-PR194-ASSURE-R1",
            "task_id": source_task_id,
            "workpackage_id": "CONTROL-WP_EXECUTION_UNAVAILABLE_RESUME_STATE_V1",
            "operation": "ASSURANCE",
            "instruction": f"Assure {source_task_id} independently.",
            "acceptance_criteria": [f"Fresh B1 claim on {source_task_id} before review"],
            "priority": -21,
            "governance_issue": 193,
            "candidate_pr": 194,
            "candidate_sha": candidate,
            "target_branch": "main",
            "work_branch": "control/193-preserve-execution-unavailable-resume-state-v1",
            "handover_id": "CONTROL-193-PR194-H2",
            "merge_policy": "AFTER_PASS_EXACT_HEAD",
            "principal_decision_required": False,
            "paused": False,
            "current_blocker": None,
            "max_attempts": 3,
            "last_verdict": "NONE",
            "last_findings": [],
            "depends_on": [],
            "created_at": "2026-08-21T23:14:30Z",
            "updated_at": "2026-08-21T23:22:00Z",
        },
    }
    (intake_dir / "CONTROL_193_PR194_ASSURE_R2.json").write_text(json.dumps(intake), encoding="utf-8")
    handover = {
        "version": "1.0",
        "handover_id": "CONTROL-193-PR194-H2",
        "task_id": source_task_id,
        "repository": "market-predictions/control-plane",
        "handover_type": "ASSURANCE_REQUEST",
        "from_role": "implementation_operations",
        "to_role": "governance_release_assurance",
        "next_action": "ASSURE_FROZEN_CANDIDATE",
        "candidate_sha": candidate,
        "candidate_pr": 194,
        "created_at": "2026-08-21T23:14:30Z",
        "work_contract_ref": "https://github.com/market-predictions/control-plane/issues/193",
        "context_refs": [],
        "actionable_findings": [],
        "assurance_result_ref": None,
        "predecessor_handover_id": None,
    }
    (handover_dir / "CONTROL-193-PR194-H2.json").write_text(json.dumps(handover), encoding="utf-8")
    _install_fake_private_modules(monkeypatch)

    report = tmp_path / "report.json"
    worker_a.resume_a_unavailable("unused", str(queue_path), str(report))

    after = json.loads(queue_path.read_text(encoding="utf-8"))
    predecessor = after["tasks"][0]
    assert predecessor["state"] == "BLOCKED"
    assert predecessor["last_verdict"] == "NONE"
    assert predecessor["active_run_id"] is None
    assert predecessor["last_findings"][-1].endswith("CONTROL-193-PR194-ASSURE-R3.")

    successor = json.loads((intake_dir / "CONTROL_193_PR194_ASSURE_R3.json").read_text(encoding="utf-8"))
    intent = successor["queue_intent"]
    assert successor["project_id"] == "CONTROL_193_PR194_ASSURE_R3"
    assert intent["task_id"] == "CONTROL-193-PR194-ASSURE-R3"
    assert intent["revision"] == "CONTROL-193-PR194-ASSURE-R3"
    assert intent["supersedes_revision"] == source_task_id
    assert intent["candidate_sha"] == candidate
    assert intent["handover_id"] == "CONTROL-193-PR194-H3"
    assert intent["priority"] == -22
    assert intent["last_verdict"] == "NONE"
    assert intent["last_findings"] == []

    successor_handover = json.loads((handover_dir / "CONTROL-193-PR194-H3.json").read_text(encoding="utf-8"))
    assert successor_handover["handover_id"] == "CONTROL-193-PR194-H3"
    assert successor_handover["task_id"] == "CONTROL-193-PR194-ASSURE-R3"
    assert successor_handover["candidate_sha"] == candidate
    assert successor_handover["candidate_pr"] == 194
    assert successor_handover["predecessor_handover_id"] == "CONTROL-193-PR194-H2"
    assert successor_handover["assurance_result_ref"] is None
    assert successor_handover["actionable_findings"] == []

    assert json.loads(report.read_text(encoding="utf-8"))["generated_assurance_retries"] == [
        "CONTROL-193-PR194-ASSURE-R3"
    ]

    worker_a.resume_a_unavailable("unused", str(queue_path), str(report))
    assert len(list(intake_dir.glob("CONTROL_193_PR194_ASSURE_R3.json"))) == 1
    assert len(list(handover_dir.glob("CONTROL-193-PR194-H3.json"))) == 1


def test_exhausted_r3_is_terminal_and_does_not_create_r4(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "DISPATCH_QUEUE.json"
    (tmp_path / "project-intake").mkdir()
    r3 = _task("CONTROL-193-PR194-ASSURE-R3", "ASSURANCE_QUEUED", 3, 3)
    r3.update(
        {
            "operation": "ASSURANCE",
            "candidate_sha": "e9ec2ba1f4339a44e15d70548317bddacb8e7faf",
            "last_verdict": "NONE",
            "assurance_result_ref": None,
        }
    )
    queue_path.write_text(
        json.dumps({"version": "1.0", "principal_manual_relay_count": 0, "tasks": [r3]}),
        encoding="utf-8",
    )
    _install_fake_private_modules(monkeypatch)

    worker_a.resume_a_unavailable("unused", str(queue_path), None)

    after = json.loads(queue_path.read_text(encoding="utf-8"))
    assert after["tasks"][0]["state"] == "BLOCKED"
    assert not (tmp_path / "project-intake" / "CONTROL_193_PR194_ASSURE_R4.json").exists()


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
    parallel = SimpleNamespace(INSTANCE_B1="B1", select_task_for_instance=lambda queue, role, worker: exhausted)
    queue_mod = SimpleNamespace(ROLE_B="governance_release_assurance")
    monkeypatch.setattr(worker_b, "_private_modules", lambda _code_dir: (parallel, queue_mod))

    with pytest.raises(worker_b.ActuatorContractError, match="attempt-exhausted B task"):
        worker_b.select_b1("unused", str(queue_path), str(tmp_path / "selection.json"))
