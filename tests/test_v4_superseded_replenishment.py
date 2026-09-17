from datetime import datetime, timezone

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_contracts import V4ValidationError
from scripts.control_v4_owner_admin import (
    activate_root_candidate_v4,
    activation_key_v4,
    replenishment_approval_payload_v4,
)


NOW = datetime(2026, 9, 17, 18, 45, tzinfo=timezone.utc)
TARGET_REPO = "market-predictions/weekly-etf-eu"
TARGET_MISSION = "WEEKLY_ETF_EU"
OLD_REVISION = "2026-09-15-r5"
CURRENT_REVISION = "2026-09-16-r6"
CURRENT_GAP = "WEEU-CORE-TRUTH-10"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40


def _candidate(sha: str, pr_number: int, branch: str) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": pr_number,
        "candidate_head_branch": branch,
        "expected_base_branch": "main",
        "expected_base_sha": "c" * 40,
    }


def _stale_task(*, repository: str = TARGET_REPO, mission_id: str = TARGET_MISSION) -> dict:
    candidate = _candidate("d" * 40, 125, "control/old-r5")
    return {
        "task_id": f"MISSION--{mission_id}--{OLD_REVISION}--OLD-GAP",
        "mission_id": mission_id,
        "mission_revision": OLD_REVISION,
        "mission_contract_blob_sha": "e" * 40,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": "OLD-GAP",
        "repository": repository,
        "acceptance": ["Old acceptance."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "BLOCKED",
        "phase": None,
        "candidate": candidate,
        "last_review": None,
        "external_review": None,
        "blocker": "REPAIR_MADE_NO_CANDIDATE_PROGRESS",
        "created_at": "2026-09-15T06:21:48Z",
        "updated_at": "2026-09-15T21:34:28Z",
    }


def _mission(repository: str = TARGET_REPO, mission_id: str = TARGET_MISSION) -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": mission_id,
        "mission_revision": CURRENT_REVISION,
        "repository": repository,
        "desired_outcome": "Restore one current product truth path.",
        "gaps": [
            {
                "gap_id": "OLD-GAP",
                "gap_state": "RETIRED",
                "depends_on": [],
                "repository": repository,
                "acceptance": ["Old acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "EXTERNAL",
            },
            {
                "gap_id": CURRENT_GAP,
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": repository,
                "acceptance": ["Current acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "EXTERNAL",
            },
        ],
        "authority_boundaries": ["No delivery authority."],
        "supersedes_revision": OLD_REVISION,
        "principal_manual_relay_count": 0,
    }


def _bundle(*, include_unrelated: bool = False) -> V4AuthorityBundle:
    target = _mission()
    missions = [target]
    authorities = [
        {
            "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
            "repository": TARGET_REPO,
            "required_check_runs": [],
            "principal_manual_relay_count": 0,
        }
    ]
    mission_shas = {TARGET_MISSION: MISSION_SHA}
    authority_shas = {TARGET_REPO: AUTHORITY_SHA}
    if include_unrelated:
        other_repo = "market-predictions/other"
        other_id = "OTHER"
        missions.append(_mission(other_repo, other_id))
        authorities.append(
            {
                "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
                "repository": other_repo,
                "required_check_runs": [],
                "principal_manual_relay_count": 0,
            }
        )
        mission_shas[other_id] = "1" * 40
        authority_shas[other_repo] = "2" * 40
    return V4AuthorityBundle(
        missions=tuple(missions),
        authorities=tuple(authorities),
        mission_blob_shas=mission_shas,
        authority_blob_shas=authority_shas,
    )


def _queue(*tasks: dict) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": list(tasks),
    }


def _command(bundle: V4AuthorityBundle) -> dict:
    mission = next(m for m in bundle.missions if m["mission_id"] == TARGET_MISSION)
    gap = next(g for g in mission["gaps"] if g["gap_id"] == CURRENT_GAP)
    return {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "approval_comment_id": 1,
        "approval_body_sha256": "3" * 64,
        "activation_key": activation_key_v4(mission, gap, bundle),
        "repository": TARGET_REPO,
        "candidate_pr_number": 127,
        "candidate_sha": "4" * 40,
        "candidate_head_branch": "recovery/v6-core-truth-10",
        "expected_base_branch": "main",
        "expected_base_sha": "c" * 40,
    }


def test_replenishment_retires_only_directly_superseded_nonterminal_project_task():
    bundle = _bundle()
    queue = _queue(_stale_task())
    approval = replenishment_approval_payload_v4(queue, bundle, TARGET_REPO)
    command = _command(bundle)

    assert command["activation_key"] in approval["eligible_activation_keys"]
    result = activate_root_candidate_v4(queue, bundle, command, approval, now=NOW)

    assert [task["gap_id"] for task in result["tasks"]] == [CURRENT_GAP]
    task = result["tasks"][0]
    assert task["mission_revision"] == CURRENT_REVISION
    assert task["status"] == "ACTIVE"
    assert task["phase"] == "REVIEW"


def test_replenishment_does_not_hide_unrelated_stale_authority_drift():
    bundle = _bundle(include_unrelated=True)
    unrelated = _stale_task(repository="market-predictions/other", mission_id="OTHER")
    queue = _queue(unrelated)

    with pytest.raises(V4ValidationError, match="revision differs"):
        replenishment_approval_payload_v4(queue, bundle, TARGET_REPO)
