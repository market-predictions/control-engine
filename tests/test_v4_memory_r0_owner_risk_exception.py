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
