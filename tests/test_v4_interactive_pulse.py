from __future__ import annotations

from copy import deepcopy

import pytest

from control_engine.v4_contracts import V4ValidationError
from control_engine.v4_runtime_protocol import (
    RuntimeProtocolError, plan_interactive_pulse_v4, validate_v41_human_start_probe,
)
from datetime import datetime, timezone
from pathlib import Path


SHA = "a" * 40
BASE = "b" * 40
CANDIDATE = {
    "candidate_sha": SHA,
    "candidate_pr_number": 3,
    "candidate_head_branch": "candidate",
    "expected_base_branch": "main",
    "expected_base_sha": BASE,
}


def queue(*, candidate=True, locked=False):
    task = {
        "task_id": "MISSION--DEMO--2026-09-06-r1--G1",
        "mission_id": "DEMO",
        "mission_revision": "2026-09-06-r1",
        "mission_contract_blob_sha": "c" * 40,
        "repository_authority_blob_sha": "d" * 40,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["Never publish this private acceptance statement."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REPAIR",
        "candidate": deepcopy(CANDIDATE) if candidate else None,
        "last_review": None,
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-06T07:00:00Z",
        "updated_at": "2026-09-06T08:00:00Z",
    }
    if not candidate:
        task["phase"] = "BUILD"
        task["status"] = "QUEUED"
    lock = (
        {
            "run_id": "old-holder",
            "task_id": task["task_id"],
            "started_at": "2026-09-06T08:00:00Z",
            "expires_at": "2026-09-06T09:30:00Z",
        } if locked else None
    )
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": [],
        "tasks": [task],
    }


def plan(value, **kwargs):
    return plan_interactive_pulse_v4(
        value, runtime_enabled=True, integration_enabled=False, **kwargs
    )


def test_exact_target_is_read_only_and_not_runtime_authorization():
    original = queue()
    saved = deepcopy(original)
    observed = deepcopy(CANDIDATE)
    result = plan(original, live_candidate=observed)
    assert result["status"] == "TARGET_EXACT_INTERACTIVE_BINDING_REQUIRED"
    assert result["candidate"] == CANDIDATE
    assert result["control_event_authorized"] is False
    assert result["target_effect_authorized"] is False
    assert "acceptance" not in str(result)
    assert original == saved
    assert observed == CANDIDATE


def test_queue_candidate_drift_fails_closed_even_for_same_pr():
    observed = {**CANDIDATE, "candidate_sha": "e" * 40}
    result = plan(queue(), live_candidate=observed)
    assert result["status"] == "CANDIDATE_DRIFT_REQUIRES_GOVERNED_RECONCILIATION"
    assert result["control_event_authorized"] is False


def test_missing_fresh_target_observation_never_approves_work():
    assert plan(queue())["status"] == "FRESH_TARGET_READ_REQUIRED"


def test_holder_present_even_if_lease_expired_requires_canonical_recovery():
    result = plan(queue(locked=True), live_candidate=CANDIDATE)
    assert result["status"] == "HOLDER_PRESENT_NO_INTERACTIVE_ACQUISITION"
    assert result["control_event_authorized"] is False


def test_runtime_disabled_or_integration_enabled_blocks_planning():
    q = queue()
    assert plan_interactive_pulse_v4(
        q, runtime_enabled=False, integration_enabled=False, live_candidate=CANDIDATE
    )["status"] == "RUNTIME_DISABLED"
    assert plan_interactive_pulse_v4(
        q, runtime_enabled=True, integration_enabled=True, live_candidate=CANDIDATE
    )["status"] == "INTEGRATION_HOLD"


@pytest.mark.parametrize("runtime_enabled,integration_enabled", [(1, False), (True, 0), (None, False)])
def test_authority_flags_must_be_exact_booleans(runtime_enabled, integration_enabled):
    with pytest.raises(V4ValidationError):
        plan_interactive_pulse_v4(
            queue(), runtime_enabled=runtime_enabled, integration_enabled=integration_enabled
        )


def test_no_queued_task_does_not_invent_root_work():
    q = queue()
    q["tasks"] = []
    assert plan(q)["status"] == "NO_ELIGIBLE_QUEUED_TASK"


def test_build_without_candidate_does_not_manufacture_target():
    assert plan(queue(candidate=False))["status"] == "BUILD_REQUIRES_INTERACTIVE_BINDING"


def test_invalid_queue_fails_before_planning():
    q = queue()
    q["principal_manual_relay_count"] = 1
    with pytest.raises(V4ValidationError):
        plan(q, live_candidate=CANDIDATE)


def test_nonstrict_target_candidate_evidence_does_not_match():
    out = plan(queue(), live_candidate={**CANDIDATE, "unexpected": "yes"})
    assert out["status"] == "CANDIDATE_DRIFT_REQUIRES_GOVERNED_RECONCILIATION"
    with pytest.raises(V4ValidationError):
        plan(queue(), live_candidate=42)


def test_selected_task_matches_existing_v4_priority_not_custom_schedule():
    q = queue()
    queued = deepcopy(q["tasks"][0])
    queued["status"] = "QUEUED"
    queued["phase"] = "BUILD"
    queued["candidate"] = None
    queued["task_id"] = "MISSION--DEMO--2026-09-06-r1--G0"
    queued["gap_id"] = "G0"
    q["tasks"] = [queued, deepcopy(q["tasks"][0])]
    result = plan(q, live_candidate=CANDIDATE)
    assert result["status"] == "TARGET_EXACT_INTERACTIVE_BINDING_REQUIRED"
    assert result["task_id"] == "MISSION--DEMO--2026-09-06-r1--G1"


PROBE_NOW = datetime(2026, 10, 10, 15, 50, tzinfo=timezone.utc)


def github_owner_probe():
    return {
        "id": 1234,
        "body": "CONTROL_V41_HUMAN_START_PROBE",
        "user": {"login": "market-predictions"},
        "issue_url": "https://api.github.com/repos/market-predictions/control-engine/issues/106",
        "created_at": "2026-10-10T15:49:30Z",
        "performed_via_github_app": None,
    }


def test_owner_origin_probe_is_read_only_and_scoped_to_exact_live_evidence():
    data = github_owner_probe()
    before = deepcopy(data)
    assert validate_v41_human_start_probe(data, expected_comment_id=1234, now=PROBE_NOW) is None
    assert data == before


@pytest.mark.parametrize("change", [
    {"id": 1235},
    {"id": True},
    {"body": "CONTROL_V41_HUMAN_START_PROBE\\nCONTROL_V4_RUNTIME_TICK"},
    {"body": "CONTROL_V41_HUMAN_START_PROBE "},
    {"user": {"login": "github-actions[bot]"}},
    {"user": {"login": "other"}},
    {"issue_url": "https://api.github.com/repos/market-predictions/control-engine/issues/107"},
    {"issue_url": "https://api.github.com/repos/market-predictions/control-plane/issues/106"},
    {"performed_via_github_app": {"slug": "chatgpt-codex-connector"}},
    {"performed_via_github_app": {"slug": "other-app"}},
    {"created_at": "2026-10-10T15:47:00Z"},
    {"created_at": "2026-10-10T15:50:01Z"},
    {"created_at": "not a timestamp"},
])
def test_probe_rejects_spoofing_staleness_and_wrong_referent(change):
    data = {**github_owner_probe(), **change}
    with pytest.raises(RuntimeProtocolError):
        validate_v41_human_start_probe(data, expected_comment_id=1234, now=PROBE_NOW)


def test_probe_requires_explicit_app_attribution_and_exact_webhook_identity():
    data = github_owner_probe()
    del data["performed_via_github_app"]
    with pytest.raises(RuntimeProtocolError):
        validate_v41_human_start_probe(data, expected_comment_id=1234, now=PROBE_NOW)
    with pytest.raises(RuntimeProtocolError):
        validate_v41_human_start_probe(github_owner_probe(), expected_comment_id=True, now=PROBE_NOW)


def test_human_start_diagnostic_has_no_private_token_or_mutating_ingress():
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text()
    assert "  human-start-probe:" in workflow
    probe = workflow.split("  human-start-probe:", 1)[1]
    assert "github.event.comment.body == 'CONTROL_V41_HUMAN_START_PROBE'" in probe
    assert "      issues: read" in probe
    assert "CONTROL_V41_CONTROL_EVENT_AUTHORIZED=false" in probe
    for unsafe in ("create-github-app-token", "permission-contents: write", "CONTROL_PLANE_TOKEN", "CONTROL_V4_RUNTIME_EVENT", "_write_queue_exact", "workflow_dispatch:"):
        assert unsafe not in probe



def test_pilot_doc_never_publishes_private_live_queue_identity():
    doc = Path("control/CONTROL_V41_INTERACTIVE_PULSE_PILOT.md").read_text()
    assert "Live task \`" not in doc
    assert "queue candidate \`" not in doc
    assert "MISSION--" not in doc
