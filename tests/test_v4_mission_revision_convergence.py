from copy import deepcopy

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle, assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import V4ValidationError, canonical_task_sha256
from control_engine.v4_mission_convergence import MissionConvergenceError, converge_direct_supersession_v4
from scripts import control_v4_mission_convergence as carrier
from scripts import control_v4_owner_admin as owner_admin


REPO = "market-predictions/weekly-etf-eu"
MISSION_ID = "WEEKLY_ETF_EU"
R4 = "2026-09-12-r4"
R5 = "2026-09-15-r5"
R6 = "2026-09-16-r6"
RECOVERY = "WEEU-RECOVERY-10"
FRESH = "WEEU-FRESH-REPORT-20"
CORE = "WEEU-CORE-TRUTH-10"
R4_SHA = "a" * 40
R5_SHA = "b" * 40
R6_SHA = "c" * 40
AUTHORITY_SHA = "d" * 40


def done_r4():
    candidate = {
        "candidate_sha": "1" * 40,
        "candidate_pr_number": 123,
        "candidate_head_branch": "recovery/122-truthful-report-pricing-semantics",
        "expected_base_branch": "main",
        "expected_base_sha": "2" * 40,
    }
    return {
        "task_id": f"MISSION--{MISSION_ID}--{R4}--{RECOVERY}",
        "mission_id": MISSION_ID,
        "mission_revision": R4,
        "mission_contract_blob_sha": R4_SHA,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": RECOVERY,
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
            "expected_base_branch": "main",
            "expected_base_sha": candidate["expected_base_sha"],
            "verdict": "PASS",
            "reviewed_at": "2026-09-13T20:30:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-11T22:15:09Z",
        "updated_at": "2026-09-13T20:36:19Z",
    }


def blocked_r5():
    candidate = {
        "candidate_sha": "3" * 40,
        "candidate_pr_number": 125,
        "candidate_head_branch": "control/weeu-r5-fresh-report-20",
        "expected_base_branch": "main",
        "expected_base_sha": "4" * 40,
    }
    return {
        "task_id": f"MISSION--{MISSION_ID}--{R5}--{FRESH}",
        "mission_id": MISSION_ID,
        "mission_revision": R5,
        "mission_contract_blob_sha": R5_SHA,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": FRESH,
        "repository": REPO,
        "acceptance": ["Fresh report acceptance."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "BLOCKED",
        "phase": None,
        "candidate": candidate,
        "last_review": {
            "candidate_sha": candidate["candidate_sha"],
            "expected_base_branch": "main",
            "expected_base_sha": candidate["expected_base_sha"],
            "verdict": "REPAIR_REQUIRED",
            "reviewed_at": "2026-09-15T21:34:28Z",
        },
        "external_review": None,
        "blocker": "REPAIR_MADE_NO_CANDIDATE_PROGRESS",
        "created_at": "2026-09-15T06:21:48Z",
        "updated_at": "2026-09-15T21:34:28Z",
    }


def carry(task):
    return {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": RECOVERY,
        "source_mission_revision": R4,
        "source_gap_id": RECOVERY,
        "source_fact_kind": "V4_DONE",
        "source_fact_ref": task["task_id"],
        "source_task_sha256": canonical_task_sha256(task),
    }


def mission_r5(done_task):
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": MISSION_ID,
        "mission_revision": R5,
        "repository": REPO,
        "desired_outcome": "Generate a fresh report.",
        "gaps": [
            {
                "gap_id": RECOVERY,
                "gap_state": "RETIRED",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Recovery acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            },
            {
                "gap_id": FRESH,
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Fresh report acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "EXTERNAL",
            },
        ],
        "done_carry_forward": [carry(done_task)],
        "authority_boundaries": ["NO EMAIL."],
        "supersedes_revision": R4,
        "principal_manual_relay_count": 0,
    }


def mission_r6(done_task):
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": MISSION_ID,
        "mission_revision": R6,
        "repository": REPO,
        "desired_outcome": "Recover one canonical pricing truth path.",
        "gaps": [
            {
                "gap_id": RECOVERY,
                "gap_state": "RETIRED",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Recovery acceptance."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            },
            {
                "gap_id": FRESH,
                "gap_state": "RETIRED",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Fresh report is historical only."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            },
            {
                "gap_id": CORE,
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["One canonical pricing truth path."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "EXTERNAL",
            },
        ],
        "done_carry_forward": [carry(done_task)],
        "authority_boundaries": ["NO EMAIL."],
        "supersedes_revision": R5,
        "principal_manual_relay_count": 0,
    }


def bundle(mission, sha):
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": REPO,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    return V4AuthorityBundle(
        missions=(mission,),
        authorities=(authority,),
        mission_blob_shas={MISSION_ID: sha},
        authority_blob_shas={REPO: AUTHORITY_SHA},
    )


def queue():
    done = done_r4()
    return (
        {
            "version": "4.0",
            "principal_manual_relay_count": 0,
            "execution_lock": None,
            "migration_facts": [],
            "tasks": [done, blocked_r5()],
        },
        done,
    )


def test_direct_supersession_removes_only_stale_non_done_and_preserves_done_carry_forward():
    source, done = queue()
    previous = bundle(mission_r5(done), R5_SHA)
    next_bundle = bundle(mission_r6(done), R6_SHA)
    assert_v4_queue_bound_to_authority(source, previous)
    with pytest.raises(V4ValidationError, match="revision differs"):
        assert_v4_queue_bound_to_authority(source, next_bundle)

    result = converge_direct_supersession_v4(source, previous, next_bundle, MISSION_ID)

    assert [task["task_id"] for task in result["tasks"]] == [done["task_id"]]
    assert result["principal_manual_relay_count"] == 0
    assert result["execution_lock"] is None
    assert_v4_queue_bound_to_authority(result, previous)
    assert_v4_queue_bound_to_authority(result, next_bundle)
    assert len(source["tasks"]) == 2  # pure transform


def test_convergence_refuses_live_execution_lock():
    source, done = queue()
    source["execution_lock"] = {
        "run_id": "v4:test",
        "task_id": source["tasks"][1]["task_id"],
        "started_at": "2026-09-16T20:00:00Z",
        "expires_at": "2026-09-16T21:30:00Z",
    }
    with pytest.raises(MissionConvergenceError, match="no execution lock"):
        converge_direct_supersession_v4(
            source,
            bundle(mission_r5(done), R5_SHA),
            bundle(mission_r6(done), R6_SHA),
            MISSION_ID,
        )


def test_convergence_requires_exact_direct_supersedes_chain():
    source, done = queue()
    bad_next = mission_r6(done)
    bad_next["supersedes_revision"] = R4
    with pytest.raises(MissionConvergenceError, match="directly supersede"):
        converge_direct_supersession_v4(
            source,
            bundle(mission_r5(done), R5_SHA),
            bundle(bad_next, R6_SHA),
            MISSION_ID,
        )


def test_convergence_does_not_delete_done_evidence_that_next_authority_does_not_bind():
    source, done = queue()
    next_mission = mission_r6(done)
    next_mission["done_carry_forward"] = []
    with pytest.raises(V4ValidationError, match="revision differs"):
        converge_direct_supersession_v4(
            source,
            bundle(mission_r5(done), R5_SHA),
            bundle(next_mission, R6_SHA),
            MISSION_ID,
        )


def test_convergence_is_not_a_generic_noop_queue_editor():
    source, done = queue()
    source["tasks"] = [done]
    with pytest.raises(MissionConvergenceError, match="no directly superseded"):
        converge_direct_supersession_v4(
            source,
            bundle(mission_r5(done), R5_SHA),
            bundle(mission_r6(done), R6_SHA),
            MISSION_ID,
        )


def test_public_command_contains_only_opaque_authority_and_exact_commit_identities():
    done = done_r4()
    next_bundle = bundle(mission_r6(done), R6_SHA)
    authority_key = owner_admin.authority_key_v4(next_bundle.missions[0], next_bundle)
    command = {
        "operation": carrier.OPERATION,
        "mode": "RECOVER_CURRENT",
        "previous_authority_sha": "5" * 40,
        "next_authority_sha": "6" * 40,
        "authority_key": authority_key,
    }
    raw = owner_admin.PREFIX + carrier.json.dumps(command, separators=(",", ":"))
    assert carrier.parse_command(raw) == command
    assert MISSION_ID not in raw and FRESH not in raw and CORE not in raw

    polluted = dict(command, mission_id=MISSION_ID)
    with pytest.raises(carrier.MissionConvergenceCarrierError, match="fields invalid"):
        carrier.parse_command(owner_admin.PREFIX + carrier.json.dumps(polluted, separators=(",", ":")))
