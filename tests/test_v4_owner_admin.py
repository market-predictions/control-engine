from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from scripts import control_v4_owner_admin as owner_admin
from scripts.control_v4_owner_admin import (
    OwnerAdminError,
    activate_root_candidate_v4,
    activation_key_v4,
    eligible_unmaterialized_gaps_v4,
    finalize_integrated_v4,
    parse_owner_admin_command,
    validate_public_target,
)


REPO = "market-predictions/agent"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40
CANDIDATE = "c" * 40
BASE = "d" * 40
NOW = datetime(2026, 9, 14, 20, 40, tzinfo=timezone.utc)


def gap(gap_id, *, depends_on=(), integration_policy="HOLD_AFTER_PASS", review_policy="INTERNAL"):
    return {
        "gap_id": gap_id,
        "gap_state": "OPEN",
        "depends_on": list(depends_on),
        "repository": REPO,
        "acceptance": [f"{gap_id} acceptance."],
        "integration_policy": integration_policy,
        "review_policy": review_policy,
    }


def mission(*, gaps=None):
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "AGENT_FRAMEWORK",
        "mission_revision": "2026-09-10-r2",
        "repository": REPO,
        "desired_outcome": "Prove the bounded carrier.",
        "gaps": list(gaps or [gap("AGENT-R1-GAP-01")]),
        "authority_boundaries": ["No production authority."],
        "principal_manual_relay_count": 0,
    }


def bundle(*, mission_value=None, mission_sha=MISSION_SHA):
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": REPO,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    value = mission_value or mission()
    return V4AuthorityBundle(
        missions=(value,),
        authorities=(authority,),
        mission_blob_shas={"AGENT_FRAMEWORK": mission_sha},
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


def reviewed_done_task(gap_id):
    candidate = {
        "candidate_sha": "1" * 40,
        "candidate_pr_number": 99,
        "candidate_head_branch": f"control/{gap_id.lower()}",
        "expected_base_branch": "main",
        "expected_base_sha": "2" * 40,
    }
    return {
        "task_id": f"MISSION--AGENT_FRAMEWORK--2026-09-10-r2--{gap_id}",
        "mission_id": "AGENT_FRAMEWORK",
        "mission_revision": "2026-09-10-r2",
        "mission_contract_blob_sha": MISSION_SHA,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": gap_id,
        "repository": REPO,
        "acceptance": [f"{gap_id} acceptance."],
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
            "reviewed_at": "2026-09-14T19:00:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-14T18:00:00Z",
        "updated_at": "2026-09-14T19:00:00Z",
    }


def activation_command(bundle_value=None, gap_value=None):
    b = bundle_value or bundle()
    m = b.missions[0]
    g = gap_value or m["gaps"][0]
    return {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "activation_key": activation_key_v4(m, g, b),
        "repository": REPO,
        "candidate_pr_number": 1,
        "candidate_sha": CANDIDATE,
        "candidate_head_branch": "bootstrap/agent-r1-gap",
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
    }


def finalize_command():
    return {
        "operation": "FINALIZE_INTEGRATED",
        "repository": REPO,
        "candidate_pr_number": 1,
        "candidate_sha": CANDIDATE,
        "candidate_head_branch": "bootstrap/agent-r1-gap",
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
    }


def activated_queue():
    b = bundle()
    return activate_root_candidate_v4(empty_queue(), b, activation_command(b), now=NOW)


def test_activation_command_uses_opaque_key_and_rejects_private_identity_fields():
    cmd = activation_command()
    raw = "CONTROL_V4_OWNER_ADMIN " + owner_admin.json.dumps(cmd, separators=(",", ":"))
    assert parse_owner_admin_command(raw) == cmd
    assert "mission_id" not in cmd and "gap_id" not in cmd

    polluted = dict(cmd, gap_id="AGENT-R1-GAP-01")
    with pytest.raises(OwnerAdminError, match="fields invalid"):
        parse_owner_admin_command(
            "CONTROL_V4_OWNER_ADMIN " + owner_admin.json.dumps(polluted, separators=(",", ":"))
        )

    with pytest.raises(OwnerAdminError, match="activation key invalid"):
        parse_owner_admin_command(raw.replace(cmd["activation_key"], "not-a-key"))


def test_finalize_command_remains_backward_compatible_without_activation_key():
    cmd = finalize_command()
    raw = "CONTROL_V4_OWNER_ADMIN " + owner_admin.json.dumps(cmd, separators=(",", ":"))
    assert parse_owner_admin_command(raw) == cmd


def test_activation_materializes_exact_candidate_directly_to_review():
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


def test_multiple_currently_eligible_gaps_are_selected_exactly_by_activation_key():
    m = mission(gaps=[gap("GAP-A"), gap("GAP-B")])
    b = bundle(mission_value=m)
    eligible = eligible_unmaterialized_gaps_v4(empty_queue(), b, REPO)
    assert [g["gap_id"] for _, g in eligible] == ["GAP-A", "GAP-B"]

    cmd = activation_command(b, m["gaps"][1])
    result = activate_root_candidate_v4(empty_queue(), b, cmd, now=NOW)
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["gap_id"] == "GAP-B"


def test_dependent_gap_becomes_eligible_only_after_dependency_is_done():
    m = mission(gaps=[gap("GAP-A"), gap("GAP-B", depends_on=["GAP-A"])])
    b = bundle(mission_value=m)
    assert [g["gap_id"] for _, g in eligible_unmaterialized_gaps_v4(empty_queue(), b, REPO)] == ["GAP-A"]

    q = empty_queue()
    q["tasks"].append(reviewed_done_task("GAP-A"))
    assert [g["gap_id"] for _, g in eligible_unmaterialized_gaps_v4(q, b, REPO)] == ["GAP-B"]

    cmd = activation_command(b, m["gaps"][1])
    result = activate_root_candidate_v4(q, b, cmd, now=NOW)
    assert result["tasks"][-1]["gap_id"] == "GAP-B"
    assert result["tasks"][-1]["status"] == "ACTIVE"
    assert result["tasks"][-1]["phase"] == "REVIEW"


def test_activation_key_is_authority_bound_and_stale_key_fails_closed():
    old = bundle()
    cmd = activation_command(old)
    changed = bundle(mission_sha="e" * 40)
    with pytest.raises(OwnerAdminError, match="activation key does not resolve"):
        activate_root_candidate_v4(empty_queue(), changed, cmd, now=NOW)


def test_activation_rejects_existing_logical_task_and_reused_public_pr():
    b = bundle()
    q = activated_queue()
    with pytest.raises(OwnerAdminError, match="candidate PR is already materialized"):
        activate_root_candidate_v4(q, b, activation_command(b), now=NOW)


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
        "reviewed_at": "2026-09-14T20:00:00Z",
    }
    before_review = dict(task["last_review"])
    result = finalize_integrated_v4(q, bundle(), finalize_command(), now=NOW)
    finished = result["tasks"][0]
    assert finished["status"] == "DONE"
    assert finished["phase"] is None
    assert finished["last_review"] == before_review


def test_public_target_rules_distinguish_activation_from_finalization():
    activate = activation_command()
    open_target = {
        "repository": REPO,
        "state": "open",
        "merged": False,
        "mergeable": True,
        "head_sha": CANDIDATE,
        "head_branch": "bootstrap/agent-r1-gap",
        "base_branch": "main",
        "base_sha": BASE,
        "current_base_sha": BASE,
        "candidate_in_current_base": False,
    }
    validate_public_target(activate, open_target)

    drifted = dict(open_target, current_base_sha="e" * 40)
    with pytest.raises(OwnerAdminError, match="base branch moved"):
        validate_public_target(activate, drifted)

    finalize = finalize_command()
    merged_target = dict(open_target)
    merged_target.update(
        state="closed",
        merged=True,
        base_sha="e" * 40,
        current_base_sha="e" * 40,
        candidate_in_current_base=True,
    )
    validate_public_target(finalize, merged_target)


def test_queue_write_revalidates_public_target_after_commit_before_graphql_cas(monkeypatch):
    q = activated_queue()
    b = bundle()
    main_sha = "1" * 40
    runtime_sha = "2" * 40
    events = []
    state = {
        "repository_node_id": "repo-node",
        "main_sha": main_sha,
        "runtime_sha": runtime_sha,
        "queue": q,
        "bundle": b,
    }

    monkeypatch.setattr(
        owner_admin,
        "_branch_head",
        lambda repository, branch, private: main_sha if branch == "main" else runtime_sha,
    )
    monkeypatch.setattr(owner_admin, "_private_get", lambda path: {"tree": {"sha": "6" * 40}})

    def private_post(path, payload):
        if path.endswith("/git/blobs"):
            return {"sha": "3" * 40}
        if path.endswith("/git/trees"):
            return {"sha": "4" * 40}
        if path.endswith("/git/commits"):
            events.append("commit")
            return {"sha": "5" * 40}
        raise AssertionError(path)

    open_target = {
        "repository": REPO,
        "state": "open",
        "merged": False,
        "mergeable": True,
        "head_sha": CANDIDATE,
        "head_branch": "bootstrap/agent-r1-gap",
        "base_branch": "main",
        "base_sha": BASE,
        "current_base_sha": BASE,
        "candidate_in_current_base": False,
    }

    def public_target(cmd):
        events.append("public_target")
        return open_target

    def request_json(url, **kwargs):
        events.append("graphql")
        return {"data": {"updateRefs": {"clientMutationId": "ok"}}}

    monkeypatch.setattr(owner_admin, "_private_post", private_post)
    monkeypatch.setattr(owner_admin, "_public_target", public_target)
    monkeypatch.setattr(owner_admin, "_private_headers", lambda: {})
    monkeypatch.setattr(owner_admin, "_request_json", request_json)

    result = owner_admin._write_queue_exact(state, q, activation_command(b))
    assert result == "5" * 40
    assert events == ["commit", "public_target", "graphql"]


def test_existing_adoption_workflow_keeps_admin_and_adoption_commands_separate():
    text = Path(".github/workflows/control-v4-authority-adoption.yml").read_text(encoding="utf-8")
    assert "startsWith(github.event.comment.body, 'CONTROL_PRIVATE_V4_ADOPT ')" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_V4_OWNER_ADMIN ')" in text
    assert "python scripts/control_v4_owner_admin.py" in text
    assert "permission-contents: write" in text
    assert "CONTROL_V4_OWNER_COMMAND" in text
