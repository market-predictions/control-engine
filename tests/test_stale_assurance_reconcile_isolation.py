from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from control_engine import scheduled_worker_a as worker_a


class FakeDispatcherState:
    @staticmethod
    def transition(task, new_state):
        updated = dict(task)
        updated["state"] = new_state
        return updated


class FakeParallel:
    @staticmethod
    def validate_parallel_queue(_queue):
        return None


def _task(task_id: str, candidate: str) -> dict:
    return {
        "task_id": task_id,
        "state": "BLOCKED",
        "attempt": 1,
        "max_attempts": 1,
        "resume_state": None,
        "active_run_id": None,
        "active_role": None,
        "active_worker_instance": None,
        "claim_started_at": None,
        "claim_expires_at": None,
        "operation": "ASSURANCE",
        "candidate_sha": candidate,
        "last_verdict": "NONE",
        "assurance_result_ref": None,
        "last_findings": ["Attempt budget exhausted during scheduled reconciliation."],
    }


def _intake(task_id: str, candidate: str) -> dict:
    return {
        "version": "1.0",
        "project_id": task_id.replace("-", "_"),
        "repository": "example/repo",
        "managed": True,
        "status": "ASSURANCE_READY",
        "principal_manual_relay_count": 0,
        "queue_intent": {
            "revision": f"{task_id}-R1",
            "supersedes_revision": None,
            "task_id": task_id,
            "workpackage_id": "WP",
            "operation": "ASSURANCE",
            "instruction": "Perform bounded independent assurance.",
            "acceptance_criteria": ["One verdict"],
            "priority": 0,
            "candidate_sha": candidate,
            "handover_id": f"{task_id}-H1",
            "max_attempts": 1,
            "last_verdict": "NONE",
            "last_findings": [],
            "current_blocker": None,
        },
    }


def test_missing_historical_intake_is_isolated_and_valid_retry_continues(monkeypatch, tmp_path: Path) -> None:
    queue_path = tmp_path / "DISPATCH_QUEUE.json"
    intake_dir = tmp_path / "project-intake"
    intake_dir.mkdir()

    stale = _task("STALE-ASSURE", "a" * 40)
    stale["intake_revision"] = "STALE-ASSURE-R1"
    valid = _task("VALID-ASSURE", "b" * 40)
    valid["intake_revision"] = "VALID-ASSURE-R1"
    queue_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "principal_manual_relay_count": 0,
                "tasks": [stale, valid],
            }
        ),
        encoding="utf-8",
    )
    (intake_dir / "VALID_ASSURE.json").write_text(
        json.dumps(_intake("VALID-ASSURE", "b" * 40)), encoding="utf-8"
    )

    queue_mod = SimpleNamespace(ROLE_A="implementation_operations")
    monkeypatch.setattr(
        worker_a,
        "_private_modules",
        lambda _code_dir: (FakeParallel, queue_mod, FakeDispatcherState),
    )

    report_path = tmp_path / "report.json"
    worker_a.resume_a_unavailable("unused", str(queue_path), str(report_path))

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["generated_assurance_retries"] == ["VALID-ASSURE-R2"]
    assert report["retry_reconciliation_blockers"][0]["task_id"] == "STALE-ASSURE"
    assert report["retry_reconciliation_blockers"][0]["reason"].startswith(
        "expected one authoritative project intake for exhausted assurance task"
    )
    assert (intake_dir / "VALID_ASSURE_R2.json").exists()
    assert not (intake_dir / "STALE_ASSURE_R2.json").exists()
