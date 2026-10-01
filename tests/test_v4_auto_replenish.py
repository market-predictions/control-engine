from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from scripts import control_v4_auto_replenish as auto
from scripts import control_v4_owner_admin as owner_admin
from scripts import control_v4_runtime_carrier as carrier


REPO = "market-predictions/agent"
MISSION_SHA = "a" * 40
AUTHORITY_SHA = "b" * 40
HEAD = "c" * 40
BASE = "d" * 40


def gap(gap_id="AGENT-R1-GAP-05"):
    return {
        "gap_id": gap_id,
        "gap_state": "OPEN",
        "depends_on": [],
        "repository": REPO,
        "acceptance": ["bounded acceptance"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
    }


def mission(gaps=None):
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "AGENT_FRAMEWORK",
        "mission_revision": "2026-09-10-r2",
        "repository": REPO,
        "desired_outcome": "Bounded agent carrier.",
        "gaps": list(gaps or [gap()]),
        "authority_boundaries": ["No production authority."],
        "principal_manual_relay_count": 0,
    }


def bundle(mission_value=None):
    value = mission_value or mission()
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": REPO,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    return V4AuthorityBundle(
        missions=(value,),
        authorities=(authority,),
        mission_blob_shas={"AGENT_FRAMEWORK": MISSION_SHA},
        authority_blob_shas={REPO: AUTHORITY_SHA},
    )


def queue():
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [],
    }


def target():
    return {
        "repository": REPO,
        "state": "open",
        "merged": False,
        "mergeable": True,
        "head_sha": HEAD,
        "head_branch": "control/mission-agent-r2-gap-05",
        "base_branch": "main",
        "base_sha": BASE,
        "current_base_sha": BASE,
        "candidate_in_current_base": False,
    }


def public_pr(number=3, body=None):
    return {
        "number": number,
        "state": "open",
        "merged_at": None,
        "mergeable": True,
        "body": body
        or "Mission: `AGENT_FRAMEWORK` revision `2026-09-10-r2`\nGap: `AGENT-R1-GAP-05`",
        "head": {"sha": HEAD, "ref": "control/mission-agent-r2-gap-05"},
        "base": {"sha": BASE, "ref": "main"},
    }


def test_exact_current_mission_gap_candidate_is_discovered_and_target_revalidated(monkeypatch):
    b = bundle()
    m = b.missions[0]
    g = m["gaps"][0]
    pr = public_pr()

    def fake_get(path):
        if path == f"repos/{REPO}":
            return {"full_name": REPO, "private": False}
        if path.startswith(f"repos/{REPO}/pulls?state=open"):
            return [pr]
        if path == f"repos/{REPO}/pulls/3":
            return pr
        if path == f"repos/{REPO}/branches/main":
            return {"commit": {"sha": BASE}}
        raise AssertionError(path)

    monkeypatch.setattr(owner_admin, "_public_get", fake_get)
    command = auto._candidate_command(m, g, b)
    assert command is not None
    assert command["candidate_pr_number"] == 3
    assert command["candidate_sha"] == HEAD
    assert command["expected_base_sha"] == BASE
    assert command["activation_key"] == owner_admin.activation_key_v4(m, g, b)


def test_candidate_discovery_requires_exact_mission_and_gap_markers(monkeypatch):
    b = bundle()
    m = b.missions[0]
    g = m["gaps"][0]
    wrong = public_pr(body="Mission: `OTHER` revision `2026-09-10-r2`\nGap: `AGENT-R1-GAP-05`")

    def fake_get(path):
        if path == f"repos/{REPO}":
            return {"full_name": REPO, "private": False}
        if path.startswith(f"repos/{REPO}/pulls?state=open"):
            return [wrong]
        raise AssertionError(path)

    monkeypatch.setattr(owner_admin, "_public_get", fake_get)
    assert auto._candidate_command(m, g, b) is None


def test_duplicate_exact_candidates_fail_closed(monkeypatch):
    b = bundle()
    m = b.missions[0]
    g = m["gaps"][0]

    def fake_get(path):
        if path == f"repos/{REPO}":
            return {"full_name": REPO, "private": False}
        if path.startswith(f"repos/{REPO}/pulls?state=open"):
            return [public_pr(3), public_pr(4)]
        raise AssertionError(path)

    monkeypatch.setattr(owner_admin, "_public_get", fake_get)
    with pytest.raises(auto.AutoReplenishError, match="multiple exact replenishment candidates"):
        auto._candidate_command(m, g, b)


def test_materialization_reuses_existing_eligibility_and_runtime_cas_and_stops_after_one(monkeypatch):
    b = bundle()
    q = queue()
    m = b.missions[0]
    g = m["gaps"][0]
    command = {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "activation_key": owner_admin.activation_key_v4(m, g, b),
        "repository": REPO,
        "candidate_pr_number": 3,
        "candidate_sha": HEAD,
        "candidate_head_branch": "control/mission-agent-r2-gap-05",
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
    }
    state = {
        "main_sha": "1" * 40,
        "runtime_sha": "2" * 40,
        "queue_blob": "3" * 40,
        "queue": q,
        "repository_node_id": "repo-node",
    }
    writes = []
    monkeypatch.setattr(auto, "_candidate_command", lambda mission_value, gap_value, bundle_value: command)
    monkeypatch.setattr(owner_admin, "_public_target", lambda command_value: target())
    monkeypatch.setattr(carrier, "_write_queue_exact", lambda state_value, next_queue, reason: writes.append((next_queue, reason)))

    result = auto._materialize_one(state, b)
    assert result == command
    assert len(writes) == 1
    next_queue, reason = writes[0]
    assert reason == "auto-replenish"
    assert len(next_queue["tasks"]) == 1
    task = next_queue["tasks"][0]
    assert task["status"] == "ACTIVE"
    assert task["phase"] == "REVIEW"
    assert task["candidate"]["candidate_pr_number"] == 3
    assert task["mission_contract_blob_sha"] == MISSION_SHA
    assert task["repository_authority_blob_sha"] == AUTHORITY_SHA


def test_no_exact_candidate_means_no_queue_write(monkeypatch):
    b = bundle()
    state = {"queue": queue()}
    monkeypatch.setattr(auto, "_candidate_command", lambda *args: None)
    monkeypatch.setattr(carrier, "_write_queue_exact", lambda *args, **kwargs: pytest.fail("must not write"))
    assert auto._materialize_one(state, b) is None


def test_workflow_reuses_admitted_private_write_capability_and_current_tick_fences():
    text = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text(encoding="utf-8")
    step = text.split("Auto-materialize governed exact candidate after NO_WORK", 1)[1].split(
        "Publish public-safe carrier result", 1
    )[0]
    assert "Create read-only private replenishment capability" not in text
    assert "CONTROL_PLANE_TOKEN: ${{ steps.private-token.outputs.token }}" in step
    assert "CONTROL_ENGINE_TOKEN: ${{ github.token }}" in step
    assert "CONTROL_V4_PUBLIC_COMMAND: ${{ github.event.comment.body }}" in step
    assert "CONTROL_V4_PUBLIC_COMMAND_ID: ${{ github.event.comment.id }}" in step
    assert "CONTROL_V4_PUBLIC_COMMAND_CREATED_AT: ${{ github.event.comment.created_at }}" in step
    assert "python scripts/control_v4_auto_replenish.py" in step
