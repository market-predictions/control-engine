from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import scripts.control_v4_runtime_carrier as carrier


NOW = datetime(2026, 9, 7, 21, 30, tzinfo=timezone.utc)
SHA = "a" * 40
BASE = "b" * 40
MISSION_BLOB = "c" * 40
AUTHORITY_BLOB = "d" * 40


def _candidate() -> dict:
    return {
        "candidate_sha": SHA,
        "candidate_pr_number": 135,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
    }


def _review_pass() -> dict:
    return {
        "candidate_sha": SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
        "verdict": "PASS",
        "reviewed_at": "2026-09-07T20:00:00Z",
    }


def _task(*, status="ACTIVE", phase="REVIEW", candidate=None) -> dict:
    return {
        "task_id": "MISSION--M--2026-09-07-r1--G1",
        "mission_id": "M",
        "mission_revision": "2026-09-07-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["done"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL" if phase == "REVIEW" else "INTERNAL",
        "convergence_required": False,
        "status": status,
        "phase": phase,
        "candidate": candidate,
        "last_review": _review_pass() if phase == "REVIEW" and candidate else None,
        "external_review": (
            {
                "candidate_sha": SHA,
                "expected_base_branch": "main",
                "expected_base_sha": BASE,
                "request_key": "G1--request",
                "status": "PENDING",
                "request_ref": "https://github.com/example/repo/pull/135#issuecomment-1",
                "evidence_ref": None,
            }
            if phase == "REVIEW" and candidate
            else None
        ),
        "blocker": None,
        "created_at": "2026-09-07T19:00:00Z",
        "updated_at": "2026-09-07T20:00:00Z",
    }


def _queue(task: dict, *, run_id: str | None, expires_at="2026-09-07T22:30:00Z") -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": (
            None
            if run_id is None
            else {
                "run_id": run_id,
                "task_id": task["task_id"],
                "started_at": "2026-09-07T20:00:00Z",
                "expires_at": expires_at,
            }
        ),
        "migration_facts": [],
        "tasks": [task],
    }


def _state(queue: dict) -> dict:
    return {
        "queue": queue,
        "runtime_enabled": True,
        "integration_enabled": False,
        "main_sha": "e" * 40,
        "runtime_sha": "f" * 40,
        "queue_blob": "1" * 40,
        "repository_node_id": "repo-node",
    }


def test_fresh_tick_acquires_current_work_and_marks_acquired_now(monkeypatch) -> None:
    task = _task(status="QUEUED", phase="BUILD", candidate=None)
    state = _state(_queue(task, run_id=None))

    def fake_write(current, next_queue, *, reason):
        return {**current, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)
    monkeypatch.setattr(carrier, "_assert_public_target_repository", lambda repository: None)

    _, result = carrier._tick({"run_id": "fresh-run", "yielded_task_tokens": []}, state, now=NOW)

    assert result["result"] == "WORK"
    assert result["run_id"] == "fresh-run"
    assert result["acquired_now"] is True
    assert result["action"] == "BUILD"


def test_live_foreign_holder_is_returned_directly_without_busy_or_resume_roundtrip(monkeypatch) -> None:
    task = _task(candidate=_candidate())
    state = _state(_queue(task, run_id="existing-holder"))
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: _candidate())

    _, result = carrier._tick({"run_id": "new-scheduler-run", "yielded_task_tokens": []}, state, now=NOW)

    assert result["result"] == "WORK"
    assert result["run_id"] == "existing-holder"
    assert result["acquired_now"] is False
    assert result["action"] == "RECONCILE_EXTERNAL_REVIEW"
    assert "resume_run_id" not in result


def test_same_holder_revalidation_is_not_misclassified_as_fresh_acquisition(monkeypatch) -> None:
    task = _task(candidate=_candidate())
    state = _state(_queue(task, run_id="holder-run"))
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: _candidate())

    _, result = carrier._tick({"run_id": "holder-run", "yielded_task_tokens": []}, state, now=NOW)

    assert result["result"] == "WORK"
    assert result["run_id"] == "holder-run"
    assert result["acquired_now"] is False


def test_expired_holder_is_recovered_then_freshly_acquired(monkeypatch) -> None:
    task = _task(candidate=_candidate())
    state = _state(_queue(task, run_id="expired-run", expires_at="2026-09-07T21:00:00Z"))
    reasons = []

    def fake_write(current, next_queue, *, reason):
        reasons.append(reason)
        return {**current, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: _candidate())

    _, result = carrier._tick({"run_id": "fresh-after-expiry", "yielded_task_tokens": []}, state, now=NOW)

    assert reasons[:2] == ["expired-lock-recovery", "acquire"]
    assert result["run_id"] == "fresh-after-expiry"
    assert result["acquired_now"] is True


def test_output_is_bound_to_exact_triggering_command_comment(tmp_path, monkeypatch) -> None:
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    carrier._set_outputs(
        {"protocol": carrier.RESULT_PROTOCOL_ID, "result": "NO_WORK", "run_id": "r"},
        ok=True,
        command_comment_id=123456,
    )

    line = output.read_text(encoding="utf-8").splitlines()[0]
    payload = json.loads(line.split("=", 1)[1])
    assert payload["command_comment_id"] == 123456
    assert payload["result"] == "NO_WORK"


def test_workflow_passes_exact_triggering_comment_id_and_contains_no_history_recovery() -> None:
    text = open(".github/workflows/control-v4-runtime-carrier.yml", encoding="utf-8").read()
    assert "CONTROL_V4_COMMAND_COMMENT_ID: ${{ github.event.comment.id }}" in text
    assert "CONTROL_V4_PUBLIC_COMMAND: ${{ github.event.comment.body }}" in text
    assert "recovery replay" not in text
    assert "unresolved EVENT" not in text
