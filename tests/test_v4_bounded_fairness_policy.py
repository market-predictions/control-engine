from __future__ import annotations

from control_engine.v4_runtime_protocol import select_task_id_v4


CANDIDATE = {
    "candidate_sha": "a" * 40,
    "candidate_pr_number": 1,
    "candidate_head_branch": "candidate",
    "expected_base_branch": "main",
    "expected_base_sha": "b" * 40,
}


def _task(task_id: str, *, review_policy: str = "INTERNAL", external_status: str | None = None) -> dict:
    external = None
    if external_status is not None:
        external = {
            "candidate_sha": CANDIDATE["candidate_sha"],
            "expected_base_branch": "main",
            "expected_base_sha": CANDIDATE["expected_base_sha"],
            "request_key": task_id,
            "status": external_status,
            "request_ref": "https://github.com/example/repo/pull/1#issuecomment-1",
            "evidence_ref": None,
        }
    return {
        "task_id": task_id,
        "mission_id": task_id,
        "mission_revision": "2026-09-18-r1",
        "mission_contract_blob_sha": ("c" if task_id.endswith("WAIT") else "d") * 40,
        "repository_authority_blob_sha": ("e" if task_id.endswith("WAIT") else "f") * 40,
        "gap_id": task_id,
        "repository": "example/repo",
        "acceptance": ["deterministic"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": review_policy,
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": dict(CANDIDATE),
        "last_review": ({
            "candidate_sha": CANDIDATE["candidate_sha"],
            "expected_base_branch": "main",
            "expected_base_sha": CANDIDATE["expected_base_sha"],
            "verdict": "PASS",
            "reviewed_at": "2026-09-18T20:00:00Z",
        } if review_policy == "EXTERNAL" else None),
        "external_review": external,
        "blocker": None,
        "created_at": "2026-09-18T20:00:00Z",
        "updated_at": "2026-09-18T20:00:00Z",
    }


def _queue(tasks: list[dict]) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": tasks,
    }


def test_pending_external_review_is_demoted_below_productive_active_work() -> None:
    waiting = _task("WAIT", review_policy="EXTERNAL", external_status="PENDING")
    productive = _task("WORK")
    selected = select_task_id_v4(_queue([waiting, productive]), run_id="fairness", integration_enabled=False)
    assert selected == productive["task_id"]


def test_pending_external_review_remains_retryable_when_it_is_only_work() -> None:
    waiting = _task("WAIT", review_policy="EXTERNAL", external_status="PENDING")
    selected = select_task_id_v4(_queue([waiting]), run_id="fairness", integration_enabled=False)
    assert selected == waiting["task_id"]


def test_indeterminate_external_review_uses_same_wait_priority() -> None:
    waiting = _task("WAIT", review_policy="EXTERNAL", external_status="INDETERMINATE")
    productive = _task("WORK")
    selected = select_task_id_v4(_queue([waiting, productive]), run_id="fairness", integration_enabled=False)
    assert selected == productive["task_id"]
