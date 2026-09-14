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
    format_replenishment_approval_v4,
    parse_owner_admin_command,
    parse_replenishment_approval,
    replenishment_approval_payload_v4,
    validate_public_target,
)


REPO = "market-predictions/agent"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40
CANDIDATE = "c" * 40
BASE = "d" * 40
APPROVAL_COMMENT_ID = 123456
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


def approval(queue_value=None, bundle_value=None):
    q = queue_value or empty_queue()
    b = bundle_value or bundle()
    return replenishment_approval_payload_v4(q, b, REPO)


def activation_command(bundle_value=None, gap_value=None, *, approval_comment_id=APPROVAL_COMMENT_ID):
    b = bundle_value or bundle()
    m = b.missions[0]
    g = gap_value or m["gaps"][0]
    return {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "approval_comment_id": approval_comment_id,
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
    q = empty_queue()
    return activate_root_candidate_v4(q, b, activation_command(b), approval(q, b), now=NOW)


def test_activation_command_uses_opaque_key_and_approval_comment_without_private_identity_fields():
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

    with pytest.raises(OwnerAdminError, match="approval comment id invalid"):
        parse_owner_admin_command(raw.replace(str(APPROVAL_COMMENT_ID), "0", 1))


def test_replenishment_approval_is_exact_sorted_opaque_current_eligible_set():
    m = mission(gaps=[gap("GAP-B"), gap("GAP-A")])
    b = bundle(mission_value=m)
    payload = replenishment_approval_payload_v4(empty_queue(), b, REPO)
    assert payload["repository"] == REPO
    assert len(payload["authority_key"]) == 64
    assert payload["eligible_activation_keys"] == sorted(payload["eligible_activation_keys"])
    assert set(payload["eligible_activation_keys"]) == {
        activation_key_v4(m, m["gaps"][0], b),
        activation_key_v4(m, m["gaps"][1], b),
    }
    body = format_replenishment_approval_v4(payload)
    assert parse_replenishment_approval(body) == payload


def test_finalize_command_remains_backward_compatible_without_replenishment_fields():
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


def test_multiple_eligible_gaps_are_selected_exactly_by_approved_activation_key():
    m = mission(gaps=[gap("GAP-A"), gap("GAP-B")])
    b = bundle(mission_value=m)
    q = empty_queue()
    approved = approval(q, b)
    eligible = eligible_unmaterialized_gaps_v4(q, b, REPO)
    assert [g["gap_id"] for _, g in eligible] == ["GAP-A", "GAP-B"]

    cmd = activation_command(b, m["gaps"][1])
    result = activate_root_candidate_v4(q, b, cmd, approved, now=NOW)
    assert len(result["tasks"]) == 1
    assert result["tasks"][0]["gap_id"] == "GAP-B"


def test_later_eligible_gap_cannot_borrow_older_project_approval_snapshot():
    m = mission(gaps=[gap("GAP-A"), gap("GAP-B", depends_on=["GAP-A"])])
    b = bundle(mission_value=m)
    before = empty_queue()
    approved_before = approval(before, b)
    assert approved_before["eligible_activation_keys"] == [activation_key_v4(m, m["gaps"][0], b)]

    after = empty_queue()
    after["tasks"].append(reviewed_done_task("GAP-A"))
    assert [g["gap_id"] for _, g in eligible_unmaterialized_gaps_v4(after, b, REPO)] == ["GAP-B"]

    later_gap_command = activation_command(b, m["gaps"][1])
    with pytest.raises(OwnerAdminError, match="not in the owner-approved replenishment snapshot"):
        activate_root_candidate_v4(after, b, later_gap_command, approved_before, now=NOW)

    approved_after = approval(after, b)
    result = activate_root_candidate_v4(after, b, later_gap_command, approved_after, now=NOW)
    assert result["tasks"][-1]["gap_id"] == "GAP-B"


def test_activation_key_and_approval_are_authority_bound_and_stale_authority_fails_closed():
    old = bundle()
    q = empty_queue()
    cmd = activation_command(old)
    approved = approval(q, old)
    changed = bundle(mission_sha="e" * 40)
    with pytest.raises(OwnerAdminError, match="approval authority is stale"):
        activate_root_candidate_v4(q, changed, cmd, approved, now=NOW)


def test_activation_requires_no_live_execution_lock():
    b = bundle()
    q = empty_queue()
    # A schema-valid lock needs one ACTIVE holder, so first activate then add its lock.
    q = activate_root_candidate_v4(q, b, activation_command(b), approval(q, b), now=NOW)
    task = q["tasks"][0]
    task["status"] = "ACTIVE"
    task["phase"] = "REVIEW"
    q["execution_lock"] = {
        "run_id": "v4:test",
        "task_id": task["task_id"],
        "started_at": "2026-09-14T20:00:00Z",
        "expires_at": "2026-09-14T21:30:00Z",
    }
    with pytest.raises(OwnerAdminError, match="requires no execution lock"):
        activate_root_candidate_v4(q, b, activation_command(b), approval(empty_queue(), b), now=NOW)


def test_activation_rejects_existing_logical_task_and_reused_public_pr():
    b = bundle()
    q = activated_queue()
    with pytest.raises(OwnerAdminError, match="candidate PR is already materialized"):
        activate_root_candidate_v4(q, b, activation_command(b), approval(empty_queue(), b), now=NOW)


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


def test_public_owner_replenishment_approval_comment_is_exactly_bound(monkeypatch):
    b = bundle()
    payload = approval(empty_queue(), b)
    body = format_replenishment_approval_v4(payload)
    monkeypatch.setattr(
        owner_admin,
        "_public_get",
        lambda path: {
            "issue_url": "https://api.github.com/repos/market-predictions/control-engine/issues/106",
            "user": {"login": "market-predictions"},
            "author_association": "OWNER",
            "body": body,
        },
    )
    assert owner_admin._public_replenishment_approval(APPROVAL_COMMENT_ID) == payload

    monkeypatch.setattr(
        owner_admin,
        "_public_get",
        lambda path: {
            "issue_url": "https://api.github.com/repos/market-predictions/control-engine/issues/106",
            "user": {"login": "someone-else"},
            "author_association": "NONE",
            "body": body,
        },
    )
    with pytest.raises(OwnerAdminError, match="not owner-authored"):
        owner_admin._public_replenishment_approval(APPROVAL_COMMENT_ID)


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
