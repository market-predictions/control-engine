from __future__ import annotations

"""Pure safety predicates for Control V4 target/lifecycle boundaries.

No network access, queue writes, scheduler behavior, provider calls, or merge
execution live here. Callers supply already-read facts; these guards only reject
unsafe state before a governed mutation/effect.
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from control_engine.v4_contracts import V4ValidationError, validate_queue_v4


NO_PROGRESS_BLOCKER = "REPAIR_MADE_NO_CANDIDATE_PROGRESS"


def _ts(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise V4ValidationError("no-progress transition time must be timezone-aware")
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _task(queue: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    matches = [task for task in queue["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise V4ValidationError("no-progress task identity does not resolve exactly")
    return matches[0]


def _assert_holder(queue: Mapping[str, Any], *, task_id: str, run_id: str) -> None:
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping) or lock.get("task_id") != task_id or lock.get("run_id") != run_id:
        raise V4ValidationError("no-progress transition requires current holder")


def _candidate_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_sha": candidate["candidate_sha"],
        "candidate_pr_number": candidate["candidate_pr_number"],
        "candidate_head_branch": candidate["candidate_head_branch"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
    }


def mark_no_progress_recheck_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Turn a no-op REPAIR into one bounded blocker-admission recheck."""
    validate_queue_v4(queue)
    _assert_holder(queue, task_id=task_id, run_id=run_id)
    task = _task(queue, task_id)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REPAIR" or not isinstance(task.get("candidate"), Mapping):
        raise V4ValidationError("no-progress marker requires ACTIVE/REPAIR candidate")

    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == task_id)
    changed["phase"] = "REVIEW"
    changed["blocker"] = NO_PROGRESS_BLOCKER
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q


def clear_no_progress_recheck_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Clear the marker when the bounded recheck admits no blocking finding."""
    validate_queue_v4(queue)
    _assert_holder(queue, task_id=task_id, run_id=run_id)
    task = _task(queue, task_id)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW" or task.get("blocker") != NO_PROGRESS_BLOCKER:
        raise V4ValidationError("no-progress PASS recheck identity invalid")

    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == task_id)
    changed["blocker"] = None
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q


def block_no_progress_after_recheck_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    now: datetime,
) -> dict[str, Any]:
    """Park a repeated admitted finding instead of re-entering the same REPAIR."""
    validate_queue_v4(queue)
    _assert_holder(queue, task_id=task_id, run_id=run_id)
    task = _task(queue, task_id)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW" or task.get("blocker") != NO_PROGRESS_BLOCKER:
        raise V4ValidationError("no-progress BLOCK identity invalid")

    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == task_id)
    candidate = changed.get("candidate")
    if not isinstance(candidate, Mapping):
        raise V4ValidationError("no-progress BLOCK requires candidate")
    changed["last_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "verdict": "REPAIR_REQUIRED",
        "reviewed_at": _ts(now),
    }
    changed["status"] = "BLOCKED"
    changed["phase"] = None
    changed["blocker"] = NO_PROGRESS_BLOCKER
    changed["updated_at"] = _ts(now)
    q["execution_lock"] = None
    validate_queue_v4(q)
    return q


def reconcile_no_progress_candidate_drift_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    live_candidate: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    """Automatically resume a parked no-progress task only after real PR drift."""
    validate_queue_v4(queue)
    task = _task(queue, task_id)
    candidate = task.get("candidate")
    if task.get("status") != "BLOCKED" or task.get("blocker") != NO_PROGRESS_BLOCKER or not isinstance(candidate, Mapping):
        return deepcopy(queue), False
    if _candidate_identity(candidate) == dict(live_candidate):
        return deepcopy(queue), False

    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == task_id)
    changed["status"] = "ACTIVE"
    changed["phase"] = "REPAIR"
    changed["blocker"] = None
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q, True


def assert_authority_supersession_lock_free(queue: Mapping[str, Any], *, task_id: str) -> dict[str, Any]:
    """Prove lock-free class-4 supersession cannot steal a persisted holder lock."""
    validate_queue_v4(queue)
    if queue.get("execution_lock") is not None:
        raise V4ValidationError("authority supersession requires execution_lock=null")
    matches = [task for task in queue["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise V4ValidationError("supersession task identity does not resolve exactly")
    task = matches[0]
    if task["status"] in {"DONE", "SUPERSEDED"}:
        raise V4ValidationError("terminal/superseded task is not a live supersession target")
    return deepcopy(task)


def assert_integration_target_exact(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    live_candidate_sha: str,
    live_base_branch: str,
    live_base_sha: str,
    native_stale_base_guard: bool,
    runner_can_bypass_stale_base_guard: bool,
) -> dict[str, Any]:
    """Prove exact reviewed target identity and native atomic stale-base rejection."""
    validate_queue_v4(queue)
    matches = [task for task in queue["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise V4ValidationError("integration task identity does not resolve exactly")
    task = matches[0]
    if task["status"] != "ACTIVE" or task["phase"] != "INTEGRATE":
        raise V4ValidationError("integration target guard requires ACTIVE/INTEGRATE")
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise V4ValidationError("integration candidate is absent")
    if live_candidate_sha != candidate.get("candidate_sha"):
        raise V4ValidationError("live candidate head drifted from reviewed candidate")
    if live_base_branch != candidate.get("expected_base_branch"):
        raise V4ValidationError("live base branch drifted from reviewed candidate")
    if live_base_sha != candidate.get("expected_base_sha"):
        raise V4ValidationError("live base SHA drifted from reviewed candidate")
    if native_stale_base_guard is not True:
        raise V4ValidationError("native GitHub stale-base rejection is not proven")
    if runner_can_bypass_stale_base_guard is not False:
        raise V4ValidationError("Runner bypass of stale-base guard is not excluded")
    return deepcopy(task)