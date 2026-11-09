from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from scripts import control_v4_paired_authority_adoption as paired


OLD_MAIN = "1" * 40
NEW_MAIN = "2" * 40
OLD_RUNTIME = "3" * 40
COMMAND = (
    f"CONTROL_PRIVATE_V4_ADOPT_PAIR {OLD_MAIN} {NEW_MAIN} {OLD_RUNTIME} "
    "ADOPT_REVIEWED_PRIVATE_MAIN_AND_RUNTIME"
)


def _bundles():
    old = V4AuthorityBundle(
        missions=(),
        authorities=({"repository": paired.MEMORY, "required_check_runs": [],
                      "principal_manual_relay_count": 0},),
        mission_blob_shas={"MEMORY_SECOND_BRAIN": "d" * 40},
        authority_blob_shas={paired.MEMORY: "a" * 40},
    )
    new = V4AuthorityBundle(
        missions=(),
        authorities=({"repository": paired.MEMORY, "required_check_runs": ["validate"],
                      "principal_manual_relay_count": 0},),
        mission_blob_shas={"MEMORY_SECOND_BRAIN": "d" * 40},
        authority_blob_shas={paired.MEMORY: "b" * 40},
    )
    return old, new


def _queue():
    tasks = [{"task_id": f"other-{i}", "history": {"keep": i}} for i in range(21)]
    tasks.insert(5, {
        "task_id": paired.MEMORY_TASK,
        "repository": paired.MEMORY,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "repository_authority_blob_sha": "a" * 40,
        "candidate": {"candidate_sha": paired.MEMORY_HEAD,
                      "expected_base_sha": paired.MEMORY_BASE},
        "integration_policy": "HOLD_AFTER_PASS",
        "external_review": {"status": "PENDING"},
        "history": {"preserve": True},
    })
    return {"tasks": tasks, "execution_lock": None, "version": "4.0",
            "migration_facts": [{"keep": True}], "principal_manual_relay_count": 0}


def test_exact_owner_command():
    assert paired.parse_command(COMMAND) == (OLD_MAIN, NEW_MAIN, OLD_RUNTIME)
    for invalid in (
        "", "CONTROL_PRIVATE_V4_ADOPT_PAIR",
        COMMAND.replace("ADOPT_REVIEWED_PRIVATE_MAIN_AND_RUNTIME", "ADOPT"),
        COMMAND.replace(OLD_RUNTIME, NEW_MAIN),
        COMMAND.replace(OLD_MAIN, "x" * 40),
        COMMAND + " EXTRA",
    ):
        with pytest.raises(paired.PairedAdoptionRejected):
            paired.parse_command(invalid)


def test_plan_rebinds_one_field_only_without_mutating_input(monkeypatch):
    monkeypatch.setattr(paired, "validate_queue_v4", lambda queue: None)
    monkeypatch.setattr(paired, "assert_v4_queue_bound_to_authority", lambda *args: None)
    old, new = _bundles()
    queue = _queue()
    frozen = deepcopy(queue)
    planned = paired.plan_one_binding(queue, old, new)
    assert queue == frozen
    assert planned["execution_lock"] is None
    assert len(planned["tasks"]) == 22
    assert planned["tasks"][5]["repository_authority_blob_sha"] == "b" * 40
    planned["tasks"][5]["repository_authority_blob_sha"] = "a" * 40
    assert planned == queue


def test_rejects_any_authority_widening_or_queue_drift(monkeypatch):
    monkeypatch.setattr(paired, "validate_queue_v4", lambda queue: None)
    monkeypatch.setattr(paired, "assert_v4_queue_bound_to_authority", lambda *args: None)
    old, new = _bundles()
    altered = V4AuthorityBundle(
        missions=new.missions, authorities=({"repository": paired.MEMORY,
                                            "required_check_runs": ["validate"],
                                            "principal_manual_relay_count": 1},),
        mission_blob_shas=new.mission_blob_shas,
        authority_blob_shas=new.authority_blob_shas,
    )
    with pytest.raises(paired.PairedAdoptionRejected):
        paired.plan_one_binding(_queue(), old, altered)
    queue = _queue()
    queue["execution_lock"] = {"unexpected": "lock"}
    with pytest.raises(paired.PairedAdoptionRejected):
        paired.plan_one_binding(queue, old, new)
    queue = _queue()
    queue["tasks"][5]["candidate"]["candidate_sha"] = "c" * 40
    with pytest.raises(paired.PairedAdoptionRejected):
        paired.plan_one_binding(queue, old, new)


def test_workflow_keeps_owner_gate_and_requires_both_refs_atomically():
    workflow = (Path(__file__).resolve().parents[1]
                / ".github/workflows/control-v4-authority-adoption.yml").read_text()
    section = workflow.split("\n  memory-paired-authority-adoption:\n", 1)[1]
    assert "github.actor == 'market-predictions'" in section
    assert "github.triggering_actor == 'market-predictions'" in section
    assert "github.event.issue.number == 106" in section
    assert "github.event.issue.pull_request == null" in section
    assert "CONTROL_PRIVATE_V4_ADOPT_PAIR" in section
    assert "permission-contents: write" in section
    assert "python scripts/control_v4_paired_authority_adoption.py" in section
    script = (Path(__file__).resolve().parents[1]
              / "scripts/control_v4_paired_authority_adoption.py").read_text()
    assert '"beforeOid": expected_main' in script
    assert '"afterOid": candidate_main' in script
    assert '"beforeOid": expected_runtime' in script
    assert '"afterOid": new_runtime' in script
    assert "assert_v4_queue_bound_to_authority(actual_queue, new_bundle)" in script
