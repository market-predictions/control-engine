from __future__ import annotations

"""Bounded V4 Mission-revision queue convergence.

The transform exists for exactly one post-live authority-evolution case: a newly
trusted Mission revision directly supersedes the previous revision while the
runtime queue still contains non-terminal work from that previous revision.
It removes only that directly superseded non-DONE projection, preserves durable
DONE evidence, creates no successor work, and succeeds only when the resulting
queue is valid against both the previous and next trusted authority bundles.
"""

from copy import deepcopy
from typing import Any, Mapping

from control_engine.v4_authority_io import V4AuthorityBundle, assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import V4ValidationError, validate_queue_v4


class MissionConvergenceError(V4ValidationError):
    pass


def _mission(bundle: V4AuthorityBundle, mission_id: str) -> Mapping[str, Any]:
    matches = [mission for mission in bundle.missions if mission.get("mission_id") == mission_id]
    if len(matches) != 1:
        raise MissionConvergenceError("Mission identity does not resolve exactly")
    return matches[0]


def converge_direct_supersession_v4(
    queue: Mapping[str, Any],
    previous_bundle: V4AuthorityBundle,
    next_bundle: V4AuthorityBundle,
    mission_id: str,
) -> dict[str, Any]:
    """Remove only non-DONE work from one directly superseded Mission revision.

    The source queue must be valid under the previous authority. The output must
    be valid under both previous and next authority. This makes the transform
    safe both as a pre-adoption preparation and as a bounded recovery after an
    authority ref moved before its runtime projection was converged.
    """

    validate_queue_v4(queue)
    if queue.get("principal_manual_relay_count") != 0:
        raise MissionConvergenceError("mission convergence requires relay zero")
    if queue.get("execution_lock") is not None:
        raise MissionConvergenceError("mission convergence requires no execution lock")

    assert_v4_queue_bound_to_authority(queue, previous_bundle)
    previous = _mission(previous_bundle, mission_id)
    next_mission = _mission(next_bundle, mission_id)

    previous_revision = previous.get("mission_revision")
    next_revision = next_mission.get("mission_revision")
    if not isinstance(previous_revision, str) or not isinstance(next_revision, str):
        raise MissionConvergenceError("Mission revision identity invalid")
    if next_mission.get("supersedes_revision") != previous_revision:
        raise MissionConvergenceError("next Mission does not directly supersede previous revision")
    if next_revision == previous_revision:
        raise MissionConvergenceError("next Mission revision did not advance")
    if next_mission.get("repository") != previous.get("repository"):
        raise MissionConvergenceError("Mission repository changed across direct supersession")

    removable_ids: set[str] = set()
    for task in queue["tasks"]:
        if task.get("mission_id") != mission_id:
            continue
        task_revision = task.get("mission_revision")
        if task_revision == previous_revision:
            if task.get("status") != "DONE":
                removable_ids.add(task["task_id"])
            continue
        if task_revision != next_revision and task.get("status") != "DONE":
            raise MissionConvergenceError("Mission contains unsupported non-DONE stale lineage")

    if not removable_ids:
        raise MissionConvergenceError("no directly superseded non-DONE Mission work requires convergence")

    result = deepcopy(queue)
    result["tasks"] = [task for task in result["tasks"] if task["task_id"] not in removable_ids]

    validate_queue_v4(result)
    if result.get("principal_manual_relay_count") != 0 or result.get("execution_lock") is not None:
        raise MissionConvergenceError("mission convergence changed protected runtime invariants")

    # Absence of an OPEN task is legal, so the prepared queue must remain valid
    # before adoption as well as after adoption. Historical DONE evidence survives
    # only when the next Mission explicitly binds it through DONE_CARRY_FORWARD.
    assert_v4_queue_bound_to_authority(result, previous_bundle)
    assert_v4_queue_bound_to_authority(result, next_bundle)
    return result
