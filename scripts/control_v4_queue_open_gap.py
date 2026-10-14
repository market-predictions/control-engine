from __future__ import annotations

"""Materialize one already-authorized Mission OPEN gap as QUEUED/BUILD.

Executed only in the native owner-started control-go job. Existing private
authority, canonical queue validation, and atomic main/runtime CAS are reused.
No candidate PR, new Mission scope, secondary queue, or review verdict.
"""
from copy import deepcopy
from datetime import datetime, timezone

from control_engine.v4_contracts import (
    assert_v4_queue_bound_to_authority, validate_queue_v4, v4_root_task_id,
)
from scripts import control_v4_owner_admin as admin
from scripts import control_v4_runtime_carrier as carrier


def plan_one(queue, bundle, *, now):
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, bundle)
    if queue["execution_lock"] is not None:
        return None
    repositories = sorted({m["repository"] for m in bundle.missions})
    for repository in repositories:
        eligible = admin.eligible_unmaterialized_gaps_v4(queue, bundle, repository)
        if not eligible:
            continue
        mission, gap = eligible[0]
        created = admin._ts(now)
        task = {
            "task_id": v4_root_task_id(mission["mission_id"], mission["mission_revision"], gap["gap_id"]),
            "mission_id": mission["mission_id"],
            "mission_revision": mission["mission_revision"],
            "mission_contract_blob_sha": bundle.mission_blob_shas[mission["mission_id"]],
            "repository_authority_blob_sha": bundle.authority_blob_shas[repository.lower()],
            "gap_id": gap["gap_id"],
            "repository": repository,
            "acceptance": list(gap["acceptance"]),
            "integration_policy": gap["integration_policy"],
            "review_policy": gap["review_policy"],
            "convergence_required": bool(gap.get("convergence_required", False)),
            "status": "QUEUED",
            "phase": "BUILD",
            "candidate": None,
            "last_review": None,
            "external_review": None,
            "blocker": None,
            "created_at": created,
            "updated_at": created,
        }
        result = deepcopy(queue)
        result["tasks"].append(task)
        validate_queue_v4(result)
        assert_v4_queue_bound_to_authority(result, bundle)
        return result, task["task_id"]
    return None


def main():
    state = carrier._load_current()
    if state["runtime_enabled"] is not True or state["integration_enabled"] is True:
        raise SystemExit("Control materialization authority disabled")
    if state["queue"]["execution_lock"] is not None:
        print("CONTROL_MISSION_QUEUE=BUSY")
        return 0
    bundle = carrier._load_authority_bundle(state["main_sha"])
    proposed = plan_one(state["queue"], bundle, now=datetime.now(timezone.utc))
    if proposed is None:
        print("CONTROL_MISSION_QUEUE=NO_ELIGIBLE_OPEN_GAP")
        return 0
    next_queue, task_id = proposed
    # The existing private-main no-op plus runtime-ref CAS rejects concurrent
    # queue writes or changed Mission/repository authority.
    carrier._write_queue_exact(state, next_queue, reason="mission-open-build-queue")
    print("CONTROL_MISSION_QUEUE=QUEUED_ONE")
    print("CONTROL_MISSION_TASK=" + task_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
