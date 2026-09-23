from copy import deepcopy

from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_contracts import V4ValidationError
from control_engine.v4_runtime_protocol import RESULT_PROTOCOL_ID, assert_public_safe
from scripts import control_v4_replenishment_snapshot as snapshot


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
    result = snapshot.enrich_no_work_result_v4(
        _no_work(), queue, _bundle(gaps=[_gap("GAP-01"), _gap("GAP-02")])
    )

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
    result = snapshot.enrich_no_work_result_v4(
        _no_work(), _queue(), _bundle(gaps=[_gap("GAP-01", state="RETIRED")])
    )
    assert result == _no_work()


def test_non_no_work_result_is_not_changed_or_replenished():
    work = {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "BUSY",
        "run_id": "v4:test",
    }
    result = snapshot.enrich_no_work_result_v4(work, _queue(), _bundle(gaps=[_gap("GAP-01")]))
    assert result == work


def test_proposal_repository_is_verified_public_before_publication(monkeypatch):
    result = snapshot.enrich_no_work_result_v4(_no_work(), _queue(), _bundle(gaps=[_gap("GAP-01")]))
    observed: list[str] = []

    def verify(repository: str) -> None:
        observed.append(repository)

    monkeypatch.setattr(snapshot.runtime_carrier, "_assert_public_target_repository", verify)
    snapshot.assert_replenishment_targets_public_v4(result)
    assert observed == [REPO]


def test_private_or_unavailable_proposal_repository_fails_closed(monkeypatch):
    result = snapshot.enrich_no_work_result_v4(_no_work(), _queue(), _bundle(gaps=[_gap("GAP-01")]))

    def reject(_repository: str) -> None:
        raise snapshot.RuntimeProtocolError("target repository is not publicly readable")

    monkeypatch.setattr(snapshot.runtime_carrier, "_assert_public_target_repository", reject)
    try:
        snapshot.assert_replenishment_targets_public_v4(result)
    except snapshot.RuntimeProtocolError:
        pass
    else:  # pragma: no cover
        raise AssertionError("private/unavailable repository must fail closed")


def test_main_catches_private_validation_error_without_emitting_result(monkeypatch, tmp_path):
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CONTROL_V4_CARRIER_RESULT", snapshot.json.dumps(_no_work()))

    def invalid_private_state():
        raise V4ValidationError("private validation failed")

    monkeypatch.setattr(snapshot.runtime_carrier, "_load_current", invalid_private_state)
    assert snapshot.main() == 1
    assert not output.exists()
