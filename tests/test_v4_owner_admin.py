from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from scripts.control_v4_owner_admin import (
    OwnerAdminError,
    activate_root_candidate_v4,
    finalize_integrated_v4,
    parse_owner_admin_command,
    validate_public_target,
)


REPO = "market-predictions/agent"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40
CANDIDATE = "c" * 40
BASE = "d" * 40
NOW = datetime(2026, 9, 13, 20, 40, tzinfo=timezone.utc)


def mission(*, integration_policy="AUTO_AFTER_PASS", review_policy="EXTERNAL"):
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "AGENT_FRAMEWORK",
        "mission_revision": "2026-09-10-r2",
        "repository": REPO,
        "desired_outcome": "Prove the bounded carrier.",
        "gaps": [
            {
                "gap_id": "AGENT-R1-GAP-01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Exact candidate is reviewed."],
                "integration_policy": integration_policy,
                "review_policy": review_policy,
            }
        ],
        "authority_boundaries": ["No production authority."],
        "principal_manual_relay_count": 0,
    }


def bundle():
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": REPO,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    return V4AuthorityBundle(
        missions=(mission(),),
        authorities=(authority,),
        mission_blob_shas={"AGENT_FRAMEWORK": MISSION_SHA},
        authority_blob_shas={REPO: AUTHORITY_SHA},
    )


def empty_queue():
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [],
    }


def command(operation):
    return {
        "operation": operation,
        "repository": REPO,
        "candidate_pr_number": 1,
        "candidate_sha": CANDIDATE,
        "candidate_head_branch": "bootstrap/agent-r1-gap-01",
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
    }


def activated_queue():
    return activate_root_candidate_v4(
        empty_queue(), bundle(), command("ACTIVATE_ROOT_CANDIDATE"), now=NOW
    )


def test_command_is_exact_public_identity_only():
    raw = (
        'CONTROL_V4_OWNER_ADMIN '
        '{"operation":"ACTIVATE_ROOT_CANDIDATE","repository":"market-predictions/agent",'
        '"candidate_pr_number":1,"candidate_sha":"' + CANDIDATE + '",'
        '"candidate_head_branch":"bootstrap/agent-r1-gap-01","expected_base_branch":"main",'
        '"expected_base_sha":"' + BASE + '"}'
    )
    parsed = parse_owner_admin_command(raw)
    assert parsed == command("ACTIVATE_ROOT_CANDIDATE")

    with pytest.raises(OwnerAdminError):
        parse_owner_admin_command(raw[:-1] + ',"gap_id":"secret"}')


def test_activation_materializes_exact_one_root_candidate_directly_to_review():
    result = activated_queue()
    assert result["execution_lock"] is None
    assert len(result["tasks"]) == 1
    task = result["tasks"][0]
    assert task["task_id"] == "MISSION--AGENT_FRAMEWORK--2026-09-10-r2--AGENT-R1-GAP-01"
    assert task["mission_contract_blob_sha"] == MISSION_SHA
    assert task["repository_authority_blob_sha"] == AUTHORITY_SHA
    assert task["status"] == "ACTIVE"
    assert task["phase"] == "REVIEW"
    assert task["candidate"]["candidate_sha"] == CANDIDATE
    assert task["last_review"] is None
    assert task["external_review"] is None


def test_activation_fails_closed_on_ambiguity_or_lock():
    q = empty_queue()
    q["execution_lock"] = {
        "run_id": "v4:test",
        "task_id": "missing",
        "started_at": "2026-09-13T20:00:00Z",
        "expires_at": "2026-09-13T21:30:00Z",
    }
    with pytest.raises(Exception):
        activate_root_candidate_v4(q, bundle(), command("ACTIVATE_ROOT_CANDIDATE"), now=NOW)

    two = mission()
    two["gaps"].append({
        "gap_id": "OTHER-ROOT",
        "gap_state": "OPEN",
        "depends_on": [],
        "repository": REPO,
        "acceptance": ["Other root."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
    })
    b = bundle()
    ambiguous = V4AuthorityBundle(
        missions=(two,),
        authorities=b.authorities,
        mission_blob_shas=b.mission_blob_shas,
        authority_blob_shas=b.authority_blob_shas,
    )
    with pytest.raises(OwnerAdminError, match="exactly one"):
        activate_root_candidate_v4(empty_queue(), ambiguous, command("ACTIVATE_ROOT_CANDIDATE"), now=NOW)


def test_activation_rejects_same_public_pr_after_base_drift():
    q = activated_queue()
    two = mission()
    two["gaps"].append({
        "gap_id": "OTHER-ROOT",
        "gap_state": "OPEN",
        "depends_on": [],
        "repository": REPO,
        "acceptance": ["Other root."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
    })
    b = bundle()
    two_root_bundle = V4AuthorityBundle(
        missions=(two,),
        authorities=b.authorities,
        mission_blob_shas=b.mission_blob_shas,
        authority_blob_shas=b.authority_blob_shas,
    )
    drifted = command("ACTIVATE_ROOT_CANDIDATE")
    drifted["expected_base_sha"] = "e" * 40

    with pytest.raises(OwnerAdminError, match="candidate PR is already materialized"):
        activate_root_candidate_v4(q, two_root_bundle, drifted, now=NOW)


def test_finalize_requires_exact_ready_pass_and_preserves_review_evidence():
    q = activated_queue()
    task = q["tasks"][0]
    task["status"] = "READY"
    task["phase"] = None
    task["last_review"] = {
        "candidate_sha": CANDIDATE,
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
        "verdict": "PASS",
        "reviewed_at": "2026-09-13T20:00:00Z",
    }
    task["external_review"] = {
        "candidate_sha": CANDIDATE,
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
        "request_key": "external-1",
        "status": "PASS",
        "request_ref": "https://github.com/example/request",
        "evidence_ref": "https://github.com/example/evidence",
    }
    before_review = dict(task["last_review"])
    result = finalize_integrated_v4(
        q, bundle(), command("FINALIZE_INTEGRATED"), now=NOW
    )
    finished = result["tasks"][0]
    assert finished["status"] == "DONE"
    assert finished["phase"] is None
    assert finished["last_review"] == before_review
    assert finished["external_review"]["status"] == "PASS"


def test_public_target_rules_distinguish_activation_from_finalization():
    activate = command("ACTIVATE_ROOT_CANDIDATE")
    open_target = {
        "repository": REPO,
        "state": "open",
        "merged": False,
        "mergeable": True,
        "head_sha": CANDIDATE,
        "head_branch": "bootstrap/agent-r1-gap-01",
        "base_branch": "main",
        "base_sha": BASE,
        "current_base_sha": BASE,
        "candidate_in_current_base": False,
    }
    validate_public_target(activate, open_target)

    drifted_open_target = dict(open_target)
    drifted_open_target["base_sha"] = "e" * 40
    with pytest.raises(OwnerAdminError, match="base drifted"):
        validate_public_target(activate, drifted_open_target)

    finalize = command("FINALIZE_INTEGRATED")
    merged_target = dict(open_target)
    merged_target.update(
        state="closed",
        merged=True,
        base_sha="e" * 40,
        current_base_sha="e" * 40,
        candidate_in_current_base=True,
    )
    validate_public_target(finalize, merged_target)

    merged_target["candidate_in_current_base"] = False
    with pytest.raises(OwnerAdminError):
        validate_public_target(finalize, merged_target)


def test_existing_adoption_workflow_keeps_admin_and_adoption_commands_separate():
    text = Path(".github/workflows/control-v4-authority-adoption.yml").read_text(encoding="utf-8")
    assert "startsWith(github.event.comment.body, 'CONTROL_PRIVATE_V4_ADOPT ')" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_V4_OWNER_ADMIN ')" in text
    assert "python scripts/control_v4_owner_admin.py" in text
    assert "permission-contents: write" in text
    assert "CONTROL_V4_OWNER_COMMAND" in text