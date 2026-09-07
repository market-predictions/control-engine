from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import inspect
from pathlib import Path

import scripts.control_v4_runtime_carrier as carrier


NOW = datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc)
WORKFLOW = Path('.github/workflows/control-v4-runtime-carrier.yml')


def _task() -> dict:
    return {
        "task_id": "T1",
        "repository": "example/repo",
        "candidate": None,
        "phase": "BUILD",
    }


def _state(*, lock: dict | None) -> dict:
    return {
        "runtime_enabled": True,
        "integration_enabled": False,
        "queue": {"execution_lock": lock, "tasks": [_task()]},
    }


def _patch_public_work(monkeypatch) -> None:
    monkeypatch.setattr(carrier, "_assert_public_target_repository", lambda repository: None)
    monkeypatch.setattr(
        carrier,
        "safe_work_capsule",
        lambda queue, *, task_id, run_id, live_candidate=None: {
            "protocol": "CONTROL_V4_RUNTIME_RESULT_V1",
            "result": "WORK",
            "run_id": run_id,
            "task_token": "a" * 64,
            "repository": "example/repo",
            "action": "BUILD",
        },
    )


def test_fresh_tick_resumes_current_live_holder_without_busy_or_second_tick(monkeypatch) -> None:
    _patch_public_work(monkeypatch)
    state = _state(
        lock={
            "run_id": "holder-old",
            "task_id": "T1",
            "started_at": "2026-09-06T08:00:00Z",
            "expires_at": "2026-09-06T09:30:00Z",
        }
    )

    _, result = carrier._tick({"run_id": "wake-new", "yielded_task_tokens": []}, state, now=NOW)

    assert result["result"] == "WORK"
    assert result["run_id"] == "holder-old"
    assert result["acquired_now"] is False
    assert "BUSY" not in inspect.getsource(carrier._tick)


def test_fresh_tick_acquires_when_no_live_holder(monkeypatch) -> None:
    _patch_public_work(monkeypatch)
    state = _state(lock=None)

    monkeypatch.setattr(carrier, "select_task_id_v4", lambda *args, **kwargs: "T1")

    def fake_acquire(queue, *, task_id, run_id, **kwargs):
        updated = deepcopy(queue)
        updated["execution_lock"] = {
            "run_id": run_id,
            "task_id": task_id,
            "started_at": "2026-09-06T08:30:00Z",
            "expires_at": "2026-09-06T10:00:00Z",
        }
        return updated

    monkeypatch.setattr(carrier, "acquire_task_v4", fake_acquire)
    monkeypatch.setattr(
        carrier,
        "_write_queue_exact",
        lambda current, next_queue, *, reason: {**current, "queue": deepcopy(next_queue)},
    )

    _, result = carrier._tick({"run_id": "wake-new", "yielded_task_tokens": []}, state, now=NOW)

    assert result["result"] == "WORK"
    assert result["run_id"] == "wake-new"
    assert result["acquired_now"] is True


def test_expired_holder_is_recovered_then_current_work_is_freshly_acquired(monkeypatch) -> None:
    _patch_public_work(monkeypatch)
    state = _state(
        lock={
            "run_id": "holder-expired",
            "task_id": "T1",
            "started_at": "2026-09-06T06:00:00Z",
            "expires_at": "2026-09-06T08:00:00Z",
        }
    )
    writes: list[str] = []

    def fake_recover(queue, *, now):
        recovered = deepcopy(queue)
        recovered["execution_lock"] = None
        return recovered, True

    def fake_acquire(queue, *, task_id, run_id, **kwargs):
        acquired = deepcopy(queue)
        acquired["execution_lock"] = {
            "run_id": run_id,
            "task_id": task_id,
            "started_at": "2026-09-06T08:30:00Z",
            "expires_at": "2026-09-06T10:00:00Z",
        }
        return acquired

    def fake_write(current, next_queue, *, reason):
        writes.append(reason)
        return {**current, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "recover_expired_lock_v4", fake_recover)
    monkeypatch.setattr(carrier, "select_task_id_v4", lambda *args, **kwargs: "T1")
    monkeypatch.setattr(carrier, "acquire_task_v4", fake_acquire)
    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)

    _, result = carrier._tick({"run_id": "wake-new", "yielded_task_tokens": []}, state, now=NOW)

    assert writes == ["expired-lock-recovery", "acquire"]
    assert result["run_id"] == "wake-new"
    assert result["acquired_now"] is True


def test_workflow_correlates_each_result_to_the_triggering_command_comment() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert "COMMAND_COMMENT_ID: ${{ github.event.comment.id }}" in text
    assert "command_comment_id = int(os.environ['COMMAND_COMMENT_ID'])" in text
    assert "payload['command_comment_id'] = command_comment_id" in text
    assert "'command_comment_id' in payload" in text


def test_workflow_remains_raw_transport_not_a_second_runtime_parser() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    carrier_step = text.split('Execute bounded typed V4 runtime carrier', 1)[1].split(
        'Publish public-safe carrier result', 1
    )[0]
    assert 'CONTROL_V4_PUBLIC_COMMAND: ${{ github.event.comment.body }}' in carrier_step
    assert 'run: python scripts/control_v4_runtime_carrier.py' in carrier_step
    assert 'Normalize observed V4 Runner compatibility envelope' not in text
    assert 'unresolved EVENT' not in text
    assert 'recovery replay' not in text
