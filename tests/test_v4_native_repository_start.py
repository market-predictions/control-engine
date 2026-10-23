"""A native start can target engineering without claiming unrelated client work."""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_contracts import V4ValidationError
from scripts import control_v4_queue_open_gap as materialize
from scripts import control_v4_runtime_carrier as carrier
from test_v4_auto_replenish import bundle, queue


NOW = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
CLIENT = "solidprivacy-nl/solidsecurity"
ETF = "market-predictions/weekly-etf"


def two_projects():
    original = bundle()
    missions, authorities, mission_shas, authority_shas = [], [], {}, {}
    for index, (repo, mission_id) in enumerate(((CLIENT, "SOLIDSECURITY"), (ETF, "WEEKLY_REVIEW_OS"))):
        mission = deepcopy(original.missions[0])
        mission.update(mission_id=mission_id, repository=repo)
        mission["gaps"][0].update(gap_id="G1", repository=repo)
        authority = {**original.authorities[0], "repository": repo}
        missions.append(mission)
        authorities.append(authority)
        mission_shas[mission_id] = str(index + 1) * 40
        authority_shas[repo] = str(index + 3) * 40
    return V4AuthorityBundle(tuple(missions), tuple(authorities), mission_shas, authority_shas)


def test_selected_native_repository_controls_both_append_and_actual_claim(monkeypatch):
    b = two_projects()
    # Existing client engagement is first in the queue and cannot be done by code.
    q, client_id = materialize.plan_one(queue(), b, now=NOW, requested_repository=CLIENT)
    saved_client = deepcopy(q["tasks"][0])
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("CONTROL_V4_CORE_FLOW", "true")
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", "  Market-Predictions/Weekly-ETF  ")
    state = {"queue": q, "main_sha": "a" * 40, "runtime_enabled": True, "integration_enabled": False}
    writes = []

    def write(state, next_queue, **kw):
        writes.append(deepcopy(next_queue))
        return {**state, "queue": next_queue}

    monkeypatch.setattr(carrier, "_load_current", lambda: state)
    monkeypatch.setattr(carrier, "_load_authority_bundle", lambda sha: b)
    monkeypatch.setattr(carrier, "_write_queue_exact", write)
    assert materialize.main() == 0
    q = writes.pop()
    etf_id = q["tasks"][-1]["task_id"]
    assert q["tasks"][-1]["repository"] == ETF
    monkeypatch.setattr(carrier, "_assert_target_repository", lambda repo: None)
    state = {"queue": q, "runtime_enabled": True, "integration_enabled": False}
    updated, result = carrier._tick({"kind": "TICK", "run_id": "v41:control-go:39130000000"}, state, now=NOW)
    assert result["result"] == "WORK"
    assert result["repository"] == ETF
    assert updated["queue"]["execution_lock"]["task_id"] == etf_id
    assert updated["queue"]["tasks"][0] == saved_client
    assert client_id != etf_id
    assert materialize.plan_one(updated["queue"], b, now=NOW, requested_repository=ETF) is None


def test_unknown_repository_cannot_create_work():
    q = queue()
    with pytest.raises(V4ValidationError, match="current Mission"):
        materialize.plan_one(q, two_projects(), now=NOW, requested_repository="unknown/project")
    assert q == queue()


@pytest.mark.parametrize("event,core", [("issue_comment", "true"), ("schedule", "true"), ("workflow_dispatch", "false")])
def test_repository_input_cannot_change_legacy_or_background_selection(monkeypatch, event, core):
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setenv("CONTROL_V4_CORE_FLOW", core)
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", ETF)
    assert carrier._native_start_repository() is None


def test_native_repository_input_is_only_data_and_keeps_agent_excluded(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    monkeypatch.setenv("CONTROL_V4_CORE_FLOW", "true")
    for invalid in ("$(touch /tmp/not-a-command)", "market-predictions/agent"):
        monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", invalid)
        with pytest.raises(carrier.RuntimeProtocolError):
            carrier._native_start_repository()
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text()
    job = workflow.split("\n  interactive-control-start:\n", 1)[1]
    assert "CONTROL_V4_START_REPOSITORY: ${{ inputs.repository }}" in job
    assert "inputs.repository" not in workflow.split("\n  interactive-control-start:\n", 1)[0].split("jobs:", 1)[1]
