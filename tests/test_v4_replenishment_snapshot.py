from copy import deepcopy

from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_runtime_protocol import RESULT_PROTOCOL_ID, assert_public_safe
from scripts.control_v4_replenishment_snapshot import enrich_no_work_result_v4


REPO = "market-predictions/agent"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40


def _gap(gap_id: str, *, state: str = "OPEN") -> dict:
    return {
        "gap_id": gap_id,
        "gap_state": state,
        "depends_on": [],
        "repository": REPO,
        "acceptance": [f"{gap_id} acceptance."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
    }


def _bundle(*, gaps: list[dict]) -> V4AuthorityBundle:
    mission = {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "AGENT_FRAMEWORK",
        "mission_revision": "2026-09-23-r3",
        "repository": REPO,
        "desired_outcome": "Finish the governed project outcome.",
        "gaps": gaps,
        "authority_boundaries": ["No production authority."],
        "principal_manual_relay_count": 0,
    }
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": REPO,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    return V4AuthorityBundle(
        missions=(mission,),
        authorities=(authority,),
        mission_blob_shas={"AGENT_FRAMEWORK": MISSION_SHA},
        authority_blob_shas={REPO: AUTHORITY_SHA},
    )


def _queue() -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [],
    }


def _no_work() -> dict:
    return {"protocol": RESULT_PROTOCOL_ID, "result": "NO_WORK", "run_id": "v4:test"}


def test_no_work_exposes_only_opaque_replenishment_snapshot_without_mutation():
    queue = _queue()
    before = deepcopy(queue)
    result = enrich_no_work_result_v4(_no_work(), queue, _bundle(gaps=[_gap("GAP-01"), _gap("GAP-02")]))

    assert queue == before
    proposals = result["replenishment_proposals"]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["repository"] == REPO
    assert len(proposal["authority_key"]) == 64
    assert len(proposal["eligible_activation_keys"]) == 2
    assert proposal["eligible_activation_keys"] == sorted(proposal["eligible_activation_keys"])
    assert proposal["approval_command"].startswith("CONTROL_V4_REPLENISH_APPROVAL ")
    assert "AGENT_FRAMEWORK" not in proposal["approval_command"]
    assert "GAP-01" not in proposal["approval_command"]
    assert "GAP-02" not in proposal["approval_command"]
    assert_public_safe(result)


def test_no_work_without_eligible_open_gap_stays_backward_compatible():
    result = enrich_no_work_result_v4(_no_work(), _queue(), _bundle(gaps=[_gap("GAP-01", state="RETIRED")]))
    assert result == _no_work()


def test_non_no_work_result_is_not_changed_or_replenished():
    work = {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "BUSY",
        "run_id": "v4:test",
    }
    result = enrich_no_work_result_v4(work, _queue(), _bundle(gaps=[_gap("GAP-01")]))
    assert result == work
