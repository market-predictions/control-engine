from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_runtime_protocol import RESULT_PROTOCOL_ID
from scripts.control_v4_replenishment_discovery import (
    OBSERVABILITY_INCOMPLETE,
    discover_replenishment_proposals_v4,
    enrich_carrier_result_v4,
)


REPO = "market-predictions/example"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40


def _gap(gap_id: str, *, state: str = "OPEN") -> dict:
    return {
        "gap_id": gap_id,
        "gap_state": state,
        "depends_on": [],
        "repository": REPO,
        "acceptance": ["Exact acceptance."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
    }


def _bundle(*, gap_state: str = "OPEN") -> V4AuthorityBundle:
    mission = {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "EXAMPLE",
        "mission_revision": "2026-09-23-r1",
        "repository": REPO,
        "desired_outcome": "Complete the governed example outcome.",
        "gaps": [_gap("EXAMPLE-GAP-10", state=gap_state)],
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
        mission_blob_shas={"EXAMPLE": MISSION_SHA},
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


def test_no_work_discovers_only_opaque_current_project_snapshot():
    proposals, incomplete = discover_replenishment_proposals_v4(_queue(), _bundle())
    assert incomplete is False
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["repository"] == REPO
    assert len(proposal["authority_key"]) == 64
    assert len(proposal["eligible_activation_keys"]) == 1
    assert len(proposal["eligible_activation_keys"][0]) == 64

    enriched = enrich_carrier_result_v4(_no_work(), queue=_queue(), bundle=_bundle())
    rendered = str(enriched)
    assert enriched["replenishment_proposals"] == proposals
    assert "mission_id" not in rendered
    assert "gap_id" not in rendered
    assert "acceptance" not in rendered
    assert "EXAMPLE-GAP-10" not in rendered


def test_no_eligible_gap_keeps_plain_no_work_result():
    result = _no_work()
    enriched = enrich_carrier_result_v4(result, queue=_queue(), bundle=_bundle(gap_state="RETIRED"))
    assert enriched == result


def test_non_no_work_result_is_not_enriched():
    work = {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "WORK",
        "run_id": "v4:test",
        "task_token": "1" * 64,
        "action": "REVIEW_INTERNAL",
        "repository": REPO,
    }
    assert enrich_carrier_result_v4(work, observability_incomplete=True) == work


def test_discovery_failure_is_generic_and_cannot_become_authority():
    enriched = enrich_carrier_result_v4(_no_work(), observability_incomplete=True)
    assert enriched == {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "NO_WORK",
        "run_id": "v4:test",
        "replenishment_observability": OBSERVABILITY_INCOMPLETE,
    }
    assert "replenishment_proposals" not in enriched
