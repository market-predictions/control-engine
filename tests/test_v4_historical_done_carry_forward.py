from copy import deepcopy

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle, assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import V4ValidationError, canonical_task_sha256


REPO = "market-predictions/weekly-etf-eu"
MISSION_ID = "WEEKLY_ETF_EU"
OLD_REVISION = "2026-09-12-r4"
NEW_REVISION = "2026-09-15-r5"
OLD_GAP = "WEEU-RECOVERY-10"
NEW_GAP = "WEEU-FRESH-REPORT-20"
OLD_MISSION_SHA = "a" * 40
NEW_MISSION_SHA = "b" * 40
AUTHORITY_SHA = "c" * 40


def old_done_task():
    candidate = {
        "candidate_sha": "1" * 40,
        "candidate_pr_number": 123,
        "candidate_head_branch": "recovery/122-truthful-report-pricing-semantics",
        "expected_base_branch": "main",
        "expected_base_sha": "2" * 40,
    }
    return {
        "task_id": f"MISSION--{MISSION_ID}--{OLD_REVISION}--{OLD_GAP}",
        "mission_id": MISSION_ID,
        "mission_revision": OLD_REVISION,
        "mission_contract_blob_sha": OLD_MISSION_SHA,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": OLD_GAP,
        "repository": REPO,
        "acceptance": ["Recovery acceptance."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
        "convergence_required": False,
        "status": "DONE",
        "phase": None,
        "candidate": candidate,
        "last_review": {
            "candidate_sha": candidate["candidate_sha"],
            "expected_base_branch": candidate["expected_base_branch"],
            "expected_base_sha": candidate["expected_base_sha"],
            "verdict": "PASS",
            "reviewed_at": "2026-09-13T20:30:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-11T22:15:09Z",
        "updated_at": "2026-09-13T20:36:19Z",
    }


def current_mission(task):
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": MISSION_ID,
        "mission_revision": NEW_REVISION,
        "repository": REPO,
        "desired_outcome": "Generate one fresh NO EMAIL Weekly ETF EU report package.",
        "gaps": [
            {
                "gap_id": OLD_GAP,
                "gap_state": "RETIRED",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Recovery acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            },
            {
                "gap_id": NEW_GAP,
                "gap_state": "OPEN",
                "depends_on": [OLD_GAP],
                "repository": REPO,
                "acceptance": ["Fresh report acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "EXTERNAL",
            },
        ],
        "done_carry_forward": [
            {
                "protocol_id": "DONE_CARRY_FORWARD",
                "target_gap_id": OLD_GAP,
                "source_mission_revision": OLD_REVISION,
                "source_gap_id": OLD_GAP,
                "source_fact_kind": "V4_DONE",
                "source_fact_ref": task["task_id"],
                "source_task_sha256": canonical_task_sha256(task),
            }
        ],
        "authority_boundaries": ["No report delivery authority."],
        "supersedes_revision": OLD_REVISION,
        "principal_manual_relay_count": 0,
    }


def bundle(task):
    mission = current_mission(task)
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": REPO,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    return V4AuthorityBundle(
        missions=(mission,),
        authorities=(authority,),
        mission_blob_shas={MISSION_ID: NEW_MISSION_SHA},
        authority_blob_shas={REPO: AUTHORITY_SHA},
    )


def queue(task):
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [task],
    }


def test_exact_historical_done_task_may_back_current_v4_done_carry_forward():
    task = old_done_task()
    assert_v4_queue_bound_to_authority(queue(task), bundle(task))


def test_historical_non_done_task_still_fails_closed():
    task = old_done_task()
    task["status"] = "READY"
    with pytest.raises(V4ValidationError, match="revision differs"):
        assert_v4_queue_bound_to_authority(queue(task), bundle(old_done_task()))


def test_historical_done_task_without_exact_carry_forward_digest_fails_closed():
    task = old_done_task()
    mission_bundle = bundle(task)
    bad_mission = deepcopy(mission_bundle.missions[0])
    bad_mission["done_carry_forward"][0]["source_task_sha256"] = "f" * 64
    bad_bundle = V4AuthorityBundle(
        missions=(bad_mission,),
        authorities=mission_bundle.authorities,
        mission_blob_shas=mission_bundle.mission_blob_shas,
        authority_blob_shas=mission_bundle.authority_blob_shas,
    )
    with pytest.raises(V4ValidationError, match="revision differs"):
        assert_v4_queue_bound_to_authority(queue(task), bad_bundle)
