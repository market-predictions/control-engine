from datetime import datetime, timezone

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from scripts import control_v4_owner_admin as owner_admin
from scripts.control_v4_owner_admin import (
    OwnerAdminError,
    parse_owner_admin_command,
    rebind_ready_candidate_v4,
    reconcile_integrated_v4,
    validate_public_target,
)


REPO = "example/project"
MISSION_ID = "EXAMPLE"
REVISION = "2026-09-16-r1"
GAP_ID = "GAP-01"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40
OLD_SHA = "1" * 40
OLD_BASE = "2" * 40
NEW_SHA = "3" * 40
NEW_BASE = "4" * 40
CURRENT_BASE = "5" * 40
PR = 7
REVIEW_COMMENT = 1234
NOW = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)


def bundle(*, review_policy="INTERNAL"):
    mission = {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": MISSION_ID,
        "mission_revision": REVISION,
        "repository": REPO,
        "desired_outcome": "Keep one canonical queue aligned with target truth.",
        "gaps": [
            {
                "gap_id": GAP_ID,
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": REPO,
                "acceptance": ["Queue truth matches the governed target."],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": review_policy,
            }
        ],
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
        mission_blob_shas={MISSION_ID: MISSION_SHA},
        authority_blob_shas={REPO: AUTHORITY_SHA},
    )


def queue(*, review_policy="INTERNAL"):
    candidate = {
        "candidate_sha": OLD_SHA,
        "candidate_pr_number": PR,
        "candidate_head_branch": "control/example",
        "expected_base_branch": "main",
        "expected_base_sha": OLD_BASE,
    }
    task = {
        "task_id": f"MISSION--{MISSION_ID}--{REVISION}--{GAP_ID}",
        "mission_id": MISSION_ID,
        "mission_revision": REVISION,
        "mission_contract_blob_sha": MISSION_SHA,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": GAP_ID,
        "repository": REPO,
        "acceptance": ["Queue truth matches the governed target."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": review_policy,
        "convergence_required": False,
        "status": "READY",
        "phase": None,
        "candidate": candidate,
        "last_review": {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": OLD_BASE,
            "verdict": "PASS",
            "reviewed_at": "2026-09-15T20:00:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-15T19:00:00Z",
        "updated_at": "2026-09-15T20:00:00Z",
    }
    if review_policy == "EXTERNAL":
        task["external_review"] = {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": OLD_BASE,
            "request_key": f"{GAP_ID}--{OLD_SHA}--main--{OLD_BASE}",
            "status": "PASS",
            "request_ref": "https://example.invalid/request",
            "evidence_ref": "https://example.invalid/evidence",
        }
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [task],
    }


def rebind_command():
    return {
        "operation": "REBIND_READY_CANDIDATE",
        "repository": REPO,
        "candidate_pr_number": PR,
        "candidate_sha": NEW_SHA,
        "candidate_head_branch": "control/example",
        "expected_base_branch": "main",
        "expected_base_sha": NEW_BASE,
    }


def reconcile_command():
    return {
        "operation": "RECONCILE_INTEGRATED",
        "internal_review_comment_id": REVIEW_COMMENT,
        "repository": REPO,
        "candidate_pr_number": PR,
        "candidate_sha": NEW_SHA,
        "candidate_head_branch": "control/example",
        "expected_base_branch": "main",
        "expected_base_sha": NEW_BASE,
    }


def open_target():
    return {
        "repository": REPO,
        "state": "open",
        "merged": False,
        "mergeable": True,
        "head_sha": NEW_SHA,
        "head_branch": "control/example",
        "base_branch": "main",
        "base_sha": NEW_BASE,
        "current_base_sha": NEW_BASE,
        "candidate_in_current_base": False,
    }


def merged_target():
    return {
        "repository": REPO,
        "state": "closed",
        "merged": True,
        "mergeable": False,
        "head_sha": NEW_SHA,
        "head_branch": "control/example",
        "base_branch": "main",
        "base_sha": NEW_BASE,
        "current_base_sha": CURRENT_BASE,
        "candidate_in_current_base": True,
    }


def review_evidence():
    return {
        "candidate_sha": NEW_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": NEW_BASE,
        "verdict": "PASS",
        "reviewed_at": "2026-09-15T20:30:00Z",
    }


def test_parser_accepts_only_exact_new_operation_fields():
    for command in (rebind_command(), reconcile_command()):
        raw = owner_admin.PREFIX + owner_admin.json.dumps(command, separators=(",", ":"))
        assert parse_owner_admin_command(raw) == command

    polluted = dict(rebind_command(), unexpected=True)
    raw = owner_admin.PREFIX + owner_admin.json.dumps(polluted, separators=(",", ":"))
    with pytest.raises(OwnerAdminError, match="fields invalid"):
        parse_owner_admin_command(raw)


def test_rebind_ready_candidate_clears_all_stale_review_evidence_and_returns_to_review():
    q = queue(review_policy="EXTERNAL")
    result = rebind_ready_candidate_v4(
        q, bundle(review_policy="EXTERNAL"), rebind_command(), now=NOW
    )
    task = result["tasks"][0]
    assert task["status"] == "ACTIVE"
    assert task["phase"] == "REVIEW"
    assert task["candidate"]["candidate_sha"] == NEW_SHA
    assert task["candidate"]["expected_base_sha"] == NEW_BASE
    assert task["last_review"] is None
    assert task["external_review"] is None
    assert task["blocker"] is None


def test_rebind_is_not_a_noop_and_requires_ready_lock_free_state():
    q = queue()
    q["tasks"][0]["candidate"] = owner_admin.candidate_identity(rebind_command())
    q["tasks"][0]["last_review"] = {
        "candidate_sha": NEW_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": NEW_BASE,
        "verdict": "PASS",
        "reviewed_at": "2026-09-15T20:00:00Z",
    }
    with pytest.raises(OwnerAdminError, match="did not change"):
        rebind_ready_candidate_v4(q, bundle(), rebind_command(), now=NOW)


def test_integrated_reconciliation_rebinds_exact_public_pass_and_records_done():
    result = reconcile_integrated_v4(
        queue(), bundle(), reconcile_command(), review_evidence(), now=NOW
    )
    task = result["tasks"][0]
    assert task["status"] == "DONE"
    assert task["phase"] is None
    assert task["candidate"] == owner_admin.candidate_identity(reconcile_command())
    assert task["last_review"] == review_evidence()
    assert task["external_review"] is None


def test_integrated_reconciliation_refuses_external_policy_or_mismatched_review():
    with pytest.raises(OwnerAdminError, match="INTERNAL review only"):
        reconcile_integrated_v4(
            queue(review_policy="EXTERNAL"),
            bundle(review_policy="EXTERNAL"),
            reconcile_command(),
            review_evidence(),
            now=NOW,
        )
    bad = dict(review_evidence(), candidate_sha=OLD_SHA)
    with pytest.raises(OwnerAdminError, match="review evidence invalid"):
        reconcile_integrated_v4(queue(), bundle(), reconcile_command(), bad, now=NOW)


def test_public_target_rules_fail_closed_for_ready_rebind_and_integrated_reconciliation():
    validate_public_target(rebind_command(), open_target())
    validate_public_target(reconcile_command(), merged_target())

    moved = dict(open_target(), current_base_sha=CURRENT_BASE)
    with pytest.raises(OwnerAdminError, match="base branch moved"):
        validate_public_target(rebind_command(), moved)

    wrong_base = dict(merged_target(), base_sha=OLD_BASE)
    with pytest.raises(OwnerAdminError, match="target base drifted"):
        validate_public_target(reconcile_command(), wrong_base)

    not_contained = dict(merged_target(), candidate_in_current_base=False)
    with pytest.raises(OwnerAdminError, match="not contained"):
        validate_public_target(reconcile_command(), not_contained)


def test_public_internal_review_comment_is_exact_pr_task_identity_and_unedited(monkeypatch):
    command = reconcile_command()
    body = (
        f"CONTROL_V4_INTERNAL_REVIEW PASS\n\n"
        f"Fresh source-based exact-candidate review of `{NEW_SHA}` against `main@{NEW_BASE}` "
        f"for current Mission `{MISSION_ID}@{REVISION} / {GAP_ID}`."
    )
    comment = {
        "issue_url": f"{owner_admin.API}/repos/{REPO}/issues/{PR}",
        "user": {"login": "market-predictions"},
        "author_association": "OWNER",
        "created_at": "2026-09-15T20:30:00Z",
        "updated_at": "2026-09-15T20:30:00Z",
        "body": body,
    }
    monkeypatch.setattr(owner_admin, "_public_get", lambda path: dict(comment))
    assert owner_admin._public_internal_review(command, queue()) == review_evidence()

    edited = dict(comment, updated_at="2026-09-15T20:31:00Z")
    monkeypatch.setattr(owner_admin, "_public_get", lambda path: edited)
    with pytest.raises(OwnerAdminError, match="was edited"):
        owner_admin._public_internal_review(command, queue())

    wrong_task = dict(comment, body=body.replace(GAP_ID, "GAP-OTHER"))
    monkeypatch.setattr(owner_admin, "_public_get", lambda path: wrong_task)
    with pytest.raises(OwnerAdminError, match="identity does not match"):
        owner_admin._public_internal_review(command, queue())
