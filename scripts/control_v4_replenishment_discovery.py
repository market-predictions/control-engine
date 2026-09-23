from __future__ import annotations

"""Read-only Control V4 replenishment discovery after a trusted NO_WORK result.

This helper does not create candidates, tasks, approvals, queue mutations, Mission
changes, or new runtime authority. It reuses the existing project replenishment
eligibility and opaque approval-snapshot primitives. The existing owner approval
and ACTIVATE_ROOT_CANDIDATE path remain the only task-materialization boundary.
"""

import json
import os
from typing import Any, Mapping

from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_contracts import V4ValidationError
from control_engine.v4_runtime_protocol import RESULT_PROTOCOL_ID, assert_public_safe, strict_json_object
from scripts.control_v4_owner_admin import (
    OwnerAdminError,
    _load_private_state,
    _public_get,
    eligible_unmaterialized_gaps_v4,
    replenishment_approval_payload_v4,
)


OBSERVABILITY_INCOMPLETE = "INCOMPLETE"
RUNNABLE_PROJECT_PHASES = {"BUILD", "REVIEW", "REPAIR"}
# Keep generous headroom below GitHub's issue-comment body limit for the public
# result prefix, command correlation field and future small envelope additions.
MAX_ADVISORY_RESULT_BYTES = 48_000


def project_has_runnable_current_work_v4(
    queue: Mapping[str, Any],
    mission: Mapping[str, Any],
) -> bool:
    """Conservatively detect current project work that should finish before replenishment.

    In particular, an invocation-local YIELD leaves the canonical task ACTIVE. A
    later same-invocation NO_WORK must not be misread as project-level exhaustion.
    """

    return any(
        task.get("mission_id") == mission.get("mission_id")
        and task.get("mission_revision") == mission.get("mission_revision")
        and task.get("repository") == mission.get("repository")
        and task.get("status") == "ACTIVE"
        and task.get("phase") in RUNNABLE_PROJECT_PHASES
        for task in queue.get("tasks", [])
        if isinstance(task, Mapping)
    )


def repository_is_publicly_supported_v4(repository: str) -> bool:
    """Return true only for the already-supported public target boundary."""

    value = _public_get(f"repos/{repository}")
    return (
        isinstance(value, Mapping)
        and value.get("full_name") == repository
        and value.get("private") is False
    )


def discover_replenishment_proposals_v4(
    queue: Mapping[str, Any],
    bundle: V4AuthorityBundle,
) -> tuple[list[dict[str, Any]], bool]:
    """Return public-safe opaque project snapshots and whether any project was unreadable.

    Discovery is best-effort per project. A malformed/stale/unsupported project
    cannot hide a valid proposal for another project, but it is surfaced only as a
    generic observability marker; private Mission/gap details never enter output.
    """

    repositories = sorted(
        {
            repository
            for mission in bundle.missions
            if isinstance((repository := mission.get("repository")), str) and repository
        }
    )
    proposals: list[dict[str, Any]] = []
    incomplete = False
    for repository in repositories:
        missions = [mission for mission in bundle.missions if mission.get("repository") == repository]
        if len(missions) != 1:
            incomplete = True
            continue
        mission = missions[0]
        if project_has_runnable_current_work_v4(queue, mission):
            continue
        try:
            if not repository_is_publicly_supported_v4(repository):
                incomplete = True
                continue
            eligible = eligible_unmaterialized_gaps_v4(queue, bundle, repository)
            if not eligible:
                continue
            proposals.append(replenishment_approval_payload_v4(queue, bundle, repository))
        except (OwnerAdminError, V4ValidationError):
            incomplete = True

    for proposal in proposals:
        assert_public_safe(proposal)
    return proposals, incomplete


def _serialized_public_result_size(result: Mapping[str, Any]) -> int:
    return len(
        json.dumps(dict(result), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )


def enrich_carrier_result_v4(
    result: Mapping[str, Any],
    *,
    queue: Mapping[str, Any] | None = None,
    bundle: V4AuthorityBundle | None = None,
    observability_incomplete: bool = False,
) -> dict[str, Any]:
    """Enrich only a trusted NO_WORK projection; all other carrier results pass through."""

    enriched = dict(result)
    if enriched.get("protocol") != RESULT_PROTOCOL_ID or enriched.get("result") != "NO_WORK":
        assert_public_safe(enriched)
        return enriched

    if queue is not None and bundle is not None:
        proposals, partial = discover_replenishment_proposals_v4(queue, bundle)
        if proposals:
            enriched["replenishment_proposals"] = proposals
        observability_incomplete = observability_incomplete or partial
    if observability_incomplete:
        enriched["replenishment_observability"] = OBSERVABILITY_INCOMPLETE

    assert_public_safe(enriched)
    if _serialized_public_result_size(enriched) > MAX_ADVISORY_RESULT_BYTES:
        # A partial eligible-key set must never look like an exact project snapshot.
        # Drop advisory proposals completely and retain only generic observability.
        bounded = dict(result)
        bounded["replenishment_observability"] = OBSERVABILITY_INCOMPLETE
        assert_public_safe(bounded)
        return bounded
    return enriched


def _write_output(result: Mapping[str, Any]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        raise SystemExit("GITHUB_OUTPUT unavailable")
    payload = json.dumps(dict(result), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"result_json={payload}\n")


def main() -> int:
    raw = os.environ.get("CONTROL_V4_CARRIER_RESULT_JSON", "")
    try:
        result = strict_json_object(raw)
    except Exception as exc:
        raise SystemExit("trusted carrier result JSON invalid") from exc

    if result.get("protocol") != RESULT_PROTOCOL_ID or result.get("result") != "NO_WORK":
        enriched = enrich_carrier_result_v4(result)
        _write_output(enriched)
        print("CONTROL_V4_REPLENISHMENT_DISCOVERY=BYPASS")
        return 0

    try:
        state = _load_private_state(allow_replenishment_reconciliation=True)
        enriched = enrich_carrier_result_v4(
            result,
            queue=state["queue"],
            bundle=state["bundle"],
        )
    except (OwnerAdminError, V4ValidationError):
        enriched = enrich_carrier_result_v4(result, observability_incomplete=True)

    _write_output(enriched)
    if enriched.get("replenishment_proposals"):
        print("CONTROL_V4_REPLENISHMENT_DISCOVERY=PROPOSED")
    elif enriched.get("replenishment_observability") == OBSERVABILITY_INCOMPLETE:
        print("CONTROL_V4_REPLENISHMENT_DISCOVERY=INCOMPLETE")
    else:
        print("CONTROL_V4_REPLENISHMENT_DISCOVERY=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
