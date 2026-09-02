from __future__ import annotations

"""Pure safety predicates for Control V4 target/lifecycle boundaries.

No network access, queue writes, scheduler behavior, provider calls, or merge
execution live here. Callers supply already-read facts; these guards only reject
unsafe state before a governed mutation/effect.
"""

from copy import deepcopy
from typing import Any, Mapping

from control_engine.v4_contracts import V4ValidationError, validate_queue_v4


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
) -> dict[str, Any]:
    """Prove live candidate/base facts still match the exact reviewed candidate."""
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
    return deepcopy(task)
