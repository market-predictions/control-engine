from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from control_engine.v4_contracts import (
    V4ValidationError,
    _exact_memory_r0_owner_risk_accepted,
    validate_queue_v4,
)
from scripts import control_v4_owner_admin as admin
from scripts import control_v4_review_resume as review


HEAD = "ec6c8fabe2f35927e7f6f3e11e3f496e49e26cf6"
BASE = "c407a9c8dfc5617f1a0adc6997a40ddd602ac011"
OWNER_REF = "https://github.com/market-predictions/control-engine/issues/106#issuecomment-6836000001"
TASK_ID = "MISSION--MEMORY_SECOND_BRAIN--2026-11-12-r2--MEM-R0-RECOVER"


def _task():
    return {
        "task_id": TASK_ID,
        "mission_id": "MEMORY_SECOND_BRAIN",
        "mission_revision": "2026-11-12-r2",
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "gap_id": "MEM-R0-RECOVER",
        "repository": "market-predictions/memory",
        "acceptance": ["Risk-accepted one-time exact-head recovery"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": {
            "candidate_sha": HEAD,
            "candidate_pr_number": 2,
            "candidate_head_branch": "import/historical-context-phase-1",
            "expected_base_branch": "main",
            "expected_base_sha": BASE,
        },
        "last_review": {
            "candidate_sha": HEAD, "expected_base_branch": "main",
            "expected_base_sha": BASE, "verdict": "PASS",
            "reviewed_at": "2026-11-02T20:16:18Z",
        },
        "external_review": {
            "candidate_sha": HEAD, "expected_base_branch": "main",
            "expected_base_sha": BASE,
            "request_key": f"MEM-R0-RECOVER--{HEAD}--main--{BASE}",
            "status": "PENDING",
            "request_ref": "https://github.com/market-predictions/memory/pull/2#issuecomment-6625962600",
            "evidence_ref": None,
        },
        "blocker": None,
        "created_at": "2026-10-20T07:51:59Z",
        "updated_at": "2026-11-04T18:07:33Z",
    }


def _queue(task):
    return {"version": "4.0", "principal_manual_relay_count": 0,
            "execution_lock": None, "migration_facts": [], "tasks": [task]}


def _accepted():
    task = _task()
    task["status"] = "READY"
    task["phase"] = None
    task["external_review"]["status"] = "OWNER_RISK_ACCEPTED"
    task["external_review"]["evidence_ref"] = OWNER_REF
    return task


def test_owner_risk_is_not_semantic_pass():
    original = _task()
    validate_queue_v4(_queue(original))
    assert not _exact_memory_r0_owner_risk_accepted(original)
    assert not review.memory_h6_semantic_coverage(
        "Codex Review: Didn't find any major issues. Reviewed commit: ec6c8fabe2", HEAD
    )
    accepted = _accepted()
    validate_queue_v4(_queue(accepted))
    assert _exact_memory_r0_owner_risk_accepted(accepted)
    assert accepted["external_review"]["status"] != "PASS"


@pytest.mark.parametrize("path,value", [
    (("task_id",), "MISSION--OTHER--2026-10-20-r1--MEM-R0-RECOVER"),
    (("repository",), "other/repo"),
    (("candidate", "candidate_sha"), "f" * 40),
    (("candidate", "candidate_pr_number"), 3),
    (("candidate", "expected_base_sha"), "f" * 40),
    (("external_review", "status"), "PENDING"),
    (("external_review", "request_ref"), "https://example.org/review"),
    (("external_review", "evidence_ref"), "https://example.org/owner-approval"),
    (("integration_policy",), "AUTO_AFTER_PASS"),
    (("status",), "ACTIVE"),
])
def test_any_scope_drift_invalidates_exception(path, value):
    task = _accepted()
    cell = task
    for field in path[:-1]:
        cell = cell[field]
    cell[path[-1]] = value
    assert not _exact_memory_r0_owner_risk_accepted(task)
    if task["external_review"]["status"] == "OWNER_RISK_ACCEPTED":
        with pytest.raises(V4ValidationError):
            validate_queue_v4(_queue(task))


def test_one_time_exception_survives_done_but_cannot_create_other_ready():
    task = _accepted()
    task["status"] = "DONE"
    validate_queue_v4(_queue(task))
    arbitrary = deepcopy(task)
    arbitrary["task_id"] = "other-task"
    with pytest.raises(V4ValidationError):
        validate_queue_v4(_queue(arbitrary))


def test_owner_admin_command_requires_explicit_risk_ack():
    task = _task()
    command = {
        "operation": "OWNER_ACCEPT_MEMORY_R0_RISK",
        "repository": task["repository"],
        **task["candidate"],
        "risk_acknowledgement": "SEMANTIC_ASSURANCE_NOT_ESTABLISHED",
    }
    raw = admin.PREFIX + json.dumps(command, separators=(",", ":"))
    assert admin.parse_owner_admin_command(raw) == command
    for bad in (
        {**command, "risk_acknowledgement": "PASS"},
        {**command, "candidate_sha": "0" * 40, "risk_acknowledgement": "PASS"},
        {**command, "extra": True},
    ):
        with pytest.raises(admin.OwnerAdminError):
            admin.parse_owner_admin_command(admin.PREFIX + json.dumps(bad))


def test_transition_is_lock_free_and_preserves_original_evidence(monkeypatch):
    monkeypatch.setattr(admin, "assert_v4_queue_bound_to_authority", lambda *args: None)
    task = _task()
    queue = _queue(task)
    command = admin.parse_owner_admin_command(admin.PREFIX + json.dumps({
        "operation": "OWNER_ACCEPT_MEMORY_R0_RISK", "repository": task["repository"],
        **task["candidate"], "risk_acknowledgement": "SEMANTIC_ASSURANCE_NOT_ESTABLISHED",
    }))
    result = admin.accept_memory_r0_owner_risk_v4(
        queue, object(), command, {"evidence_ref": OWNER_REF},
        now=datetime(2026, 11, 12, tzinfo=timezone.utc),
    )
    assert result["tasks"][0]["status"] == "READY"
    assert result["tasks"][0]["phase"] is None
    assert result["tasks"][0]["external_review"]["status"] == "OWNER_RISK_ACCEPTED"
    assert queue["tasks"][0]["external_review"]["status"] == "PENDING"
    assert result["tasks"][0]["last_review"] == queue["tasks"][0]["last_review"]
    assert result["execution_lock"] is None
    with pytest.raises(admin.OwnerAdminError):
        admin.accept_memory_r0_owner_risk_v4(
            result, object(), command, {"evidence_ref": OWNER_REF},
            now=datetime(2026, 11, 12, tzinfo=timezone.utc),
        )


def test_workflow_binds_existing_owner_identity_and_private_cas():
    text = (Path(__file__).resolve().parents[1]
            / ".github/workflows/control-v4-authority-adoption.yml").read_text()
    assert "CONTROL_V4_OWNER_COMMENT_ID: ${{ github.event.comment.id }}" in text
    assert "github.actor == 'market-predictions'" in text
    assert "github.triggering_actor == 'market-predictions'" in text
    assert "github.event.issue.number == 106" in text
    source = (Path(__file__).resolve().parents[1]
              / "scripts/control_v4_owner_admin.py").read_text()
    assert '"beforeOid": state["runtime_sha"]' in source
    assert '"force": False' in source
    assert "MEMORY_R0_POLICY_BLOB" in source


def _mission_pair():
    from control_engine.v4_authority_io import V4AuthorityBundle
    from scripts import control_v4_paired_authority_adoption as paired
    gaps = [
        {"gap_id": "MEM-R0-RECOVER", "acceptance": ["old semantic review"],
         "description": "historic H6", "integration_policy": "HOLD_AFTER_PASS",
         "review_policy": "EXTERNAL", "gap_state": "OPEN", "depends_on": [],
         "repository": "market-predictions/memory"},
    ] + [
        {"gap_id": f"MEM-R{i}-GAP", "acceptance": ["stable"],
         "integration_policy": "HOLD_AFTER_PASS", "review_policy": "EXTERNAL",
         "gap_state": "OPEN", "depends_on": [], "repository": "market-predictions/memory"}
        for i in range(1, 6)
    ]
    base = {"mission_id": "MEMORY_SECOND_BRAIN", "mission_revision": "2026-10-20-r1",
            "repository": "market-predictions/memory", "gaps": gaps,
            "authority_boundaries": ["strict H6"], "terminal_conditions": ["H6 complete"],
            "principal_manual_relay_count": 0}
    amended = deepcopy(base)
    amended["supersedes_revision"] = base["mission_revision"]
    amended["mission_revision"] = "2026-11-12-r2"
    amended["gaps"][0]["acceptance"] = ["OWNER_RISK_ACCEPTED is not a semantic PASS"]
    amended["gaps"][0]["description"] = "one-time owner risk"
    amended["authority_boundaries"] = ["risk accepted narrowly"]
    amended["terminal_conditions"] = ["owner exception verified"]
    old = V4AuthorityBundle(
        missions=(base,), authorities=(), mission_blob_shas={"MEMORY_SECOND_BRAIN": "a" * 40},
        authority_blob_shas={"market-predictions/memory": "2" * 40})
    new = V4AuthorityBundle(
        missions=(amended,), authorities=(), mission_blob_shas={"MEMORY_SECOND_BRAIN": "b" * 40},
        authority_blob_shas={"market-predictions/memory": "2" * 40})
    return old, new


def test_risk_mission_pair_rebinds_single_task_without_touching_others(monkeypatch):
    from scripts import control_v4_paired_authority_adoption as paired
    old, new = _mission_pair()
    monkeypatch.setattr(paired, "validate_queue_v4", lambda q: None)
    monkeypatch.setattr(paired, "assert_v4_queue_bound_to_authority", lambda *args: None)
    task = _task()
    task["task_id"] = paired.MEMORY_TASK
    task["mission_revision"] = paired.MEMORY_R1_REVISION
    task["mission_contract_blob_sha"] = "a" * 40
    task["acceptance"] = ["old semantic review"]
    others = [{"task_id": f"unrelated-{i}", "preserve": i} for i in range(21)]
    source = {"version": "4.0", "tasks": others + [task], "execution_lock": None,
              "principal_manual_relay_count": 0, "migration_facts": []}
    result = paired.plan_risk_mission_binding(source, old, new)
    assert len(result["tasks"]) == 22
    assert result["tasks"][:21] == others
    assert source["tasks"][-1]["task_id"] == paired.MEMORY_TASK
    assert result["tasks"][-1]["task_id"] == paired.MEMORY_R2_TASK
    assert result["tasks"][-1]["mission_contract_blob_sha"] == "b" * 40
    assert result["tasks"][-1]["acceptance"] == ["OWNER_RISK_ACCEPTED is not a semantic PASS"]
    assert result["tasks"][-1]["external_review"] == source["tasks"][-1]["external_review"]


def test_risk_mission_pair_rejects_unrelated_mission_and_queue_drift(monkeypatch):
    from scripts import control_v4_paired_authority_adoption as paired
    old, new = _mission_pair()
    monkeypatch.setattr(paired, "validate_queue_v4", lambda q: None)
    monkeypatch.setattr(paired, "assert_v4_queue_bound_to_authority", lambda *args: None)
    bad_mission = deepcopy(new.missions[0])
    bad_mission["gaps"][2]["acceptance"] = ["quietly changed"]
    from control_engine.v4_authority_io import V4AuthorityBundle
    bad_new = V4AuthorityBundle(missions=(bad_mission,), authorities=new.authorities,
        mission_blob_shas=new.mission_blob_shas, authority_blob_shas=new.authority_blob_shas)
    with pytest.raises(paired.PairedAdoptionRejected):
        paired._assert_risk_mission_delta(old, bad_new)
    task = _task()
    task["task_id"] = paired.MEMORY_TASK
    task["mission_revision"] = paired.MEMORY_R1_REVISION
    q = {"version": "4.0", "execution_lock": {"do_not_change": True},
         "tasks": [{"task_id": f"other-{i}"} for i in range(21)] + [task]}
    with pytest.raises(paired.PairedAdoptionRejected):
        paired.plan_risk_mission_binding(q, old, new)


def test_risk_adoption_command_is_distinct_and_existing_command_retained():
    from scripts import control_v4_paired_authority_adoption as paired
    suffix = "1" * 40 + " " + "2" * 40 + " " + "3" * 40
    cmd1 = f"{paired.COMMAND} {suffix} {paired.CONFIRM}"
    cmd2 = f"{paired.COMMAND} {suffix} {paired.RISK_CONFIRM}"
    assert paired.parse_command(cmd1) == paired.parse_command(cmd2)
    with pytest.raises(paired.PairedAdoptionRejected):
        paired.parse_command(cmd2.replace(paired.RISK_CONFIRM, "ADOPT_UNVERIFIED"))


@pytest.mark.parametrize("injection", [
    "new_issue_finding",
    "new_issue_without_reviewed_head",
    "commented_review_finding",
    "inline_finding",
    "ci_failed",
    "policy_not_adopted",
    "owner_comment_edited",
])
def test_owner_risk_evidence_fails_closed_on_review_and_authority_drift(monkeypatch, injection):
    task = _task()
    command = admin.parse_owner_admin_command(admin.PREFIX + json.dumps({
        "operation": "OWNER_ACCEPT_MEMORY_R0_RISK",
        "repository": task["repository"], **task["candidate"],
        "risk_acknowledgement": "SEMANTIC_ASSURANCE_NOT_ESTABLISHED",
    }))
    raw = admin.PREFIX + json.dumps(command, separators=(",", ":"))
    monkeypatch.setenv("CONTROL_V4_OWNER_COMMENT_ID", "900")
    monkeypatch.setenv("CONTROL_V4_OWNER_COMMAND", raw)
    policy_blob = admin.MEMORY_R0_POLICY_BLOB if injection != "policy_not_adopted" else "0" * 40
    monkeypatch.setattr(admin, "_private_file",
        lambda path, ref: ("### 6.2 One-time Memory R0 owner-risk acceptance", policy_blob))
    monkeypatch.setattr(admin, "_public_external_review_receipt", lambda c: {"id": c["external_review_comment_id"]})
    bot = {"login": admin.EXTERNAL_REVIEW_BOT_LOGIN, "id": admin.EXTERNAL_REVIEW_BOT_USER_ID}
    receipts = [
        {"id": rid, "user": bot, "created_at": "2026-11-12T18:50:00Z",
         "updated_at": "2026-11-12T18:50:00Z",
         "body": f"Codex Review: Didn't find any major issues.\nReviewed commit: `ec6c8fabe2`"}
        for rid in admin.MEMORY_R0_RECEIPTS
    ]
    if injection == "new_issue_finding":
        receipts.append({"id": 9991, "user": bot, "created_at": "2026-11-12T18:51:00Z",
                         "updated_at": "2026-11-12T18:51:00Z",
                         "body": "Reviewed commit: `ec6c8fabe2`\nP1 unresolved"})
    if injection == "new_issue_without_reviewed_head":
        receipts.append({"id": 9992, "user": bot, "created_at": "2026-11-12T18:51:00Z",
                         "updated_at": "2026-11-12T18:51:00Z",
                         "body": "<!-- codex-code-review-finding:v1 --> P1"})
    reviews = []
    inline = []
    if injection == "commented_review_finding":
        reviews = [{"user": bot, "commit_id": HEAD, "state": "COMMENTED", "body": "P1 issue found"}]
    if injection == "inline_finding":
        inline = [{"user": bot, "original_commit_id": HEAD, "body": "P1 issue found"}]
    owner = {"id": 900, "issue_url": f"{admin.API}/repos/{admin.PUBLIC_REPOSITORY}/issues/106",
             "user": {"login": admin.PRINCIPAL_LOGIN, "id": admin.PRINCIPAL_USER_ID},
             "author_association": "OWNER", "created_at": "2026-11-12T21:25:00Z",
             "updated_at": "2026-11-12T21:25:00Z", "body": raw}
    if injection == "owner_comment_edited":
        owner["updated_at"] = "2026-11-12T21:25:01Z"
    check = {"name": "validate", "head_sha": HEAD, "status": "completed",
             "conclusion": "failure" if injection == "ci_failed" else "success",
             "app": {"id": 15368, "slug": "github-actions"}}
    def public(path):
        if path.endswith("/issues/comments/900"):
            return owner
        if path.endswith("/issues/2/comments?per_page=100"):
            return receipts
        if path.endswith("/pulls/2/reviews?per_page=100"):
            return reviews
        if path.endswith("/pulls/2/comments?per_page=100"):
            return inline
        if "/check-runs?" in path:
            return {"total_count": 1, "check_runs": [check]}
        raise AssertionError(path)
    monkeypatch.setattr(admin, "_public_get", public)
    with pytest.raises(admin.OwnerAdminError):
        admin._memory_r0_owner_risk_evidence(command, {"main_sha": "f" * 40, "queue": _queue(task)})
