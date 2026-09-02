from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from control_engine import kernel_v31
from control_engine.v4_contracts import (
    PENDING_DRIFT_BLOCKER,
    V4ValidationError,
    acquire_task_v4,
    build_rollback_v31_queue,
    derive_rollback_missions_v31,
    derive_rollback_v31,
    finish_passed_review_v4,
    forward_transform_v31_to_v4,
    validate_carry_forward_evidence,
    validate_mission_v4,
    validate_queue_v4,
    validate_repository_authority_v4,
)


NOW = datetime(2026, 9, 2, 18, 0, tzinfo=timezone.utc)
SHA_A = "a" * 40
SHA_B = "b" * 40
CANDIDATE_SHA = "c" * 40
BASE_SHA = "d" * 40


def repo_authority(repo: str = "example/repo") -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": repo,
        "required_check_runs": ["CI"],
        "principal_manual_relay_count": 0,
    }


def gap(
    gap_id: str,
    *,
    state: str = "OPEN",
    depends_on: list[str] | None = None,
    repo: str = "example/repo",
    integration: str = "HOLD_AFTER_PASS",
    review: str = "INTERNAL",
) -> dict:
    return {
        "gap_id": gap_id,
        "gap_state": state,
        "depends_on": list(depends_on or []),
        "repository": repo,
        "acceptance": [f"accept {gap_id}"],
        "integration_policy": integration,
        "review_policy": review,
    }


def mission_v4(*gaps: dict, revision: str = "2026-09-02-r2", carry: list[dict] | None = None) -> dict:
    doc = {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "M",
        "mission_revision": revision,
        "repository": "example/repo",
        "desired_outcome": "bounded outcome",
        "gaps": list(gaps),
        "authority_boundaries": ["no production authority"],
        "principal_manual_relay_count": 0,
    }
    if carry is not None:
        doc["done_carry_forward"] = carry
    return doc


def candidate() -> dict:
    return {
        "candidate_sha": CANDIDATE_SHA,
        "candidate_pr_number": 7,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def review_pass() -> dict:
    return {
        "candidate_sha": CANDIDATE_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "verdict": "PASS",
        "reviewed_at": "2026-09-02T18:00:00Z",
    }


def task_v4(
    task_id: str = "T1",
    *,
    status: str = "QUEUED",
    phase: str | None = "BUILD",
    integration: str = "HOLD_AFTER_PASS",
    review_policy: str = "INTERNAL",
    with_candidate: bool = False,
    with_pass: bool = False,
    blocker: str | None = None,
) -> dict:
    cand = candidate() if with_candidate else None
    return {
        "task_id": task_id,
        "mission_id": "M",
        "mission_revision": "2026-09-02-r2",
        "mission_contract_blob_sha": SHA_A,
        "repository_authority_blob_sha": SHA_B,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["accept G1"],
        "integration_policy": integration,
        "review_policy": review_policy,
        "convergence_required": False,
        "status": status,
        "phase": phase,
        "candidate": cand,
        "last_review": review_pass() if with_pass else None,
        "external_review": None,
        "blocker": blocker,
        "created_at": "2026-09-02T17:00:00Z",
        "updated_at": "2026-09-02T17:00:00Z",
    }


def queue_v4(*tasks: dict, lock: dict | None = None, facts: list[dict] | None = None) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": list(facts or []),
        "tasks": list(tasks),
    }


def migration_fact(gap_id: str = "G0") -> dict:
    return {
        "protocol_id": "CONTROL_V3_1_MIGRATION_FACT",
        "fact": "LEGACY_PROJECT_INTEGRATION_COMPLETED",
        "mission_id": "M",
        "mission_revision": "2026-09-01-r1",
        "gap_id": gap_id,
        "repository": "example/repo",
        "source_task_id": f"legacy-{gap_id}",
        "source_result_ref": f"control/worker-results/{gap_id}.json",
        "imported_at": "2026-09-02T17:00:00Z",
        "principal_manual_relay_count": 0,
    }


def v31_task(gap_id: str = "G1", *, status: str = "QUEUED") -> dict:
    doc = {
        "lifecycle_model": kernel_v31.PROTOCOL_ID,
        "task_id": f"MISSION--M--2026-09-01-r1--{gap_id}",
        "operation": "IMPLEMENTATION",
        "role": kernel_v31.ROLE_A,
        "repository": "example/repo",
        "status": status,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "principal_manual_relay_count": 0,
        "created_at": "2026-09-02T17:00:00Z",
        "updated_at": "2026-09-02T17:00:00Z",
        "queued_at": "2026-09-02T17:00:00Z",
        "mission_id": "M",
        "mission_revision": "2026-09-01-r1",
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "gap_id": gap_id,
        "integration_policy": "HOLD_AFTER_PASS",
        "acceptance": [f"accept {gap_id}"],
    }
    return doc


def queue_v31(*tasks: dict, facts: list[dict] | None = None) -> dict:
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": list(facts or []),
        "tasks": list(tasks),
    }


def mission_v31() -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "M",
        "mission_revision": "2026-09-01-r1",
        "repository": "example/repo",
        "desired_outcome": "bounded outcome",
        "gaps": [
            {
                "gap_id": "G20",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/repo",
                "operation": "IMPLEMENTATION",
                "acceptance": ["accept G20"],
                "integration_policy": "HOLD_AFTER_PASS",
            },
            {
                "gap_id": "G30",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/repo",
                "operation": "IMPLEMENTATION",
                "acceptance": ["accept G30"],
                "integration_policy": "HOLD_AFTER_PASS",
            },
            {
                "gap_id": "G40",
                "gap_state": "OPEN",
                "depends_on": ["G20", "G30"],
                "repository": "example/repo",
                "operation": "IMPLEMENTATION",
                "acceptance": ["accept G40"],
                "integration_policy": "HOLD_AFTER_PASS",
            },
        ],
        "authority_boundaries": ["no production authority"],
        "supersedes_revision": None,
        "principal_manual_relay_count": 0,
    }


def test_v4_schemas_are_draft_2020_12_and_basic_docs_validate() -> None:
    root = Path(__file__).resolve().parents[1]
    for rel in (
        "schemas/mission_contract_v4.schema.json",
        "schemas/repository_authority_v4.schema.json",
        "schemas/dispatch_queue_v4.schema.json",
    ):
        schema = json.loads((root / rel).read_text(encoding="utf-8"))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        Draft202012Validator.check_schema(schema)

    validate_mission_v4(mission_v4(gap("G1")))
    validate_repository_authority_v4(repo_authority())
    validate_queue_v4(queue_v4(task_v4()))


def test_one_global_lock_and_multiple_unlocked_active_waits_are_valid() -> None:
    first = task_v4("T1", status="ACTIVE", phase="BUILD")
    second = deepcopy(first)
    second.update(task_id="T2", gap_id="G2")
    validate_queue_v4(queue_v4(first, second))

    lock = {
        "run_id": "run-1",
        "task_id": "T1",
        "started_at": "2026-09-02T18:00:00Z",
        "expires_at": "2026-09-02T19:30:00Z",
    }
    validate_queue_v4(queue_v4(first, second, lock=lock))

    bad = queue_v4(first, second, lock={**lock, "task_id": "missing"})
    with pytest.raises(V4ValidationError):
        validate_queue_v4(bad)


def test_atomic_acquisition_is_forbidden_when_runtime_disabled() -> None:
    before = queue_v4(task_v4())
    original = deepcopy(before)
    with pytest.raises(V4ValidationError, match="runtime disabled"):
        acquire_task_v4(
            before,
            task_id="T1",
            run_id="run-1",
            now=NOW,
            control_runtime_enabled=False,
            integration_enabled=False,
        )
    assert before == original


def test_auto_pass_with_integration_disabled_becomes_ready_and_clears_lock() -> None:
    active = task_v4(
        status="ACTIVE",
        phase="REVIEW",
        integration="AUTO_AFTER_PASS",
        with_candidate=True,
    )
    lock = {
        "run_id": "run-1",
        "task_id": "T1",
        "started_at": "2026-09-02T17:30:00Z",
        "expires_at": "2026-09-02T19:00:00Z",
    }
    after = finish_passed_review_v4(
        queue_v4(active, lock=lock),
        task_id="T1",
        run_id="run-1",
        now=NOW,
        control_runtime_enabled=True,
        integration_enabled=False,
    )
    assert after["execution_lock"] is None
    assert after["tasks"][0]["status"] == "READY"
    assert after["tasks"][0]["phase"] is None
    assert after["tasks"][0]["last_review"]["verdict"] == "PASS"
    assert after["tasks"][0]["last_review"]["expected_base_branch"] == "main"
    assert after["tasks"][0]["last_review"]["expected_base_sha"] == BASE_SHA


def test_review_pass_is_invalidated_by_base_only_drift() -> None:
    reviewed = task_v4(status="READY", phase=None, with_candidate=True, with_pass=True)
    validate_queue_v4(queue_v4(reviewed))

    changed_base = deepcopy(reviewed)
    changed_base["candidate"]["expected_base_sha"] = "e" * 40
    with pytest.raises(V4ValidationError, match="internal review candidate/base identity is stale"):
        validate_queue_v4(queue_v4(changed_base))


def test_ready_auto_requires_runtime_and_integration_for_integration_acquisition() -> None:
    ready = task_v4(
        status="READY",
        phase=None,
        integration="AUTO_AFTER_PASS",
        with_candidate=True,
        with_pass=True,
    )
    with pytest.raises(V4ValidationError):
        acquire_task_v4(
            queue_v4(ready),
            task_id="T1",
            run_id="run-1",
            now=NOW,
            control_runtime_enabled=True,
            integration_enabled=False,
        )

    after = acquire_task_v4(
        queue_v4(ready),
        task_id="T1",
        run_id="run-1",
        now=NOW,
        control_runtime_enabled=True,
        integration_enabled=True,
    )
    assert after["tasks"][0]["status"] == "ACTIVE"
    assert after["tasks"][0]["phase"] == "INTEGRATE"


def test_ready_drift_marker_survives_holder_loss_and_blocks_ordinary_review() -> None:
    ready = task_v4(status="READY", phase=None, with_candidate=True, with_pass=True)
    acquired = acquire_task_v4(
        queue_v4(ready),
        task_id="T1",
        run_id="run-1",
        now=NOW,
        control_runtime_enabled=True,
        integration_enabled=False,
        ready_drift_reconciliation=True,
    )
    assert acquired["tasks"][0]["blocker"] == PENDING_DRIFT_BLOCKER

    # Model objective expired-lock recovery: lock clears, task semantics remain.
    lost = deepcopy(acquired)
    lost["execution_lock"] = None
    validate_queue_v4(lost)
    reacquired = acquire_task_v4(
        lost,
        task_id="T1",
        run_id="run-2",
        now=NOW + timedelta(hours=2),
        control_runtime_enabled=True,
        integration_enabled=False,
    )
    assert reacquired["tasks"][0]["blocker"] == PENDING_DRIFT_BLOCKER
    with pytest.raises(V4ValidationError, match="ordinary REVIEW forbidden"):
        finish_passed_review_v4(
            reacquired,
            task_id="T1",
            run_id="run-2",
            now=NOW + timedelta(hours=2, minutes=1),
            control_runtime_enabled=True,
            integration_enabled=False,
        )


def test_carry_forward_requires_retired_target_and_exact_migration_evidence() -> None:
    fact = migration_fact("G0")
    carry = [{
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "G0",
        "source_mission_revision": "2026-09-01-r1",
        "source_gap_id": "G0",
        "source_fact_kind": "MIGRATION_FACT",
        "source_fact_ref": fact["source_result_ref"],
    }]
    mission = mission_v4(
        gap("G0", state="RETIRED"),
        gap("G1", depends_on=["G0"]),
        carry=carry,
    )
    validate_mission_v4(mission)
    validate_carry_forward_evidence(mission, queue_v4(facts=[fact]))

    bad_target = deepcopy(mission)
    bad_target["gaps"][0]["gap_state"] = "OPEN"
    with pytest.raises(V4ValidationError, match="target must be RETIRED"):
        validate_mission_v4(bad_target)

    missing = mission_v4(gap("G0", state="RETIRED"), gap("G1", depends_on=["G0"]))
    with pytest.raises(V4ValidationError, match="lacks carry-forward"):
        validate_mission_v4(missing)


def test_forward_transform_preserves_exact_migration_fact_and_maps_live_root_once() -> None:
    fact = migration_fact("G0")
    pre = queue_v31(v31_task("G1"), facts=[fact])
    kernel_v31.validate(pre)
    carry = [{
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "G0",
        "source_mission_revision": "2026-09-01-r1",
        "source_gap_id": "G0",
        "source_fact_kind": "MIGRATION_FACT",
        "source_fact_ref": fact["source_result_ref"],
    }]
    mission = mission_v4(
        gap("G0", state="RETIRED"),
        gap("G1"),
        carry=carry,
    )
    output = forward_transform_v31_to_v4(
        pre,
        missions=[mission],
        mission_blob_shas={"M": SHA_A},
        authorities=[repo_authority()],
        authority_blob_shas={"example/repo": SHA_B},
        transformed_at=NOW,
    )
    assert output["execution_lock"] is None
    assert output["migration_facts"] == [fact]
    assert len(output["tasks"]) == 1
    assert output["tasks"][0]["gap_id"] == "G1"
    assert output["tasks"][0]["mission_revision"] == "2026-09-02-r2"
    assert output["tasks"][0]["status"] == "QUEUED"


def test_forward_transform_fails_closed_on_live_v31_claim() -> None:
    executing = v31_task("G1", status="EXECUTING")
    executing["claim"] = {
        "run_id": "run-old",
        "role": kernel_v31.ROLE_A,
        "worker_instance": kernel_v31.INSTANCE_A1,
        "started_at": "2026-09-02T17:00:00Z",
        "expires_at": "2026-09-02T18:30:00Z",
    }
    pre = queue_v31(executing)
    kernel_v31.validate(pre)
    with pytest.raises(V4ValidationError, match="live V3.1 claim"):
        forward_transform_v31_to_v4(
            pre,
            missions=[mission_v4(gap("G1"))],
            mission_blob_shas={"M": SHA_A},
            authorities=[repo_authority()],
            authority_blob_shas={"example/repo": SHA_B},
            transformed_at=NOW,
        )


def test_rollback_normalizes_satisfied_dependencies_and_creates_no_synthetic_results() -> None:
    fact = migration_fact("G20")
    pre = queue_v31(facts=[fact])
    kernel_v31.validate(pre)
    current_v4 = queue_v4(facts=[fact])

    missions, rollback_queue, satisfied = derive_rollback_v31(
        pre_v31_queue=pre,
        v4_queue=current_v4,
        pre_cutover_missions=[mission_v31()],
        rollback_revisions={"M": "2026-09-03-r2"},
    )
    assert satisfied == {"M": {"G20"}}
    by_id = {item["gap_id"]: item for item in missions[0]["gaps"]}
    assert by_id["G20"]["gap_state"] == "RETIRED"
    assert by_id["G30"]["gap_state"] == "OPEN"
    assert by_id["G40"]["gap_state"] == "OPEN"
    assert by_id["G40"]["depends_on"] == ["G30"]
    assert rollback_queue["tasks"] == []
    assert rollback_queue["migration_facts"] == [fact]
    kernel_v31.validate(rollback_queue)


def test_rollback_rejects_unknown_satisfied_gap_and_preserves_only_preexisting_terminal_results() -> None:
    with pytest.raises(V4ValidationError, match="does not exist"):
        derive_rollback_missions_v31(
            [mission_v31()],
            satisfied_gap_ids={"M": {"UNKNOWN"}},
            rollback_revisions={"M": "2026-09-03-r2"},
        )

    terminal = v31_task("G20", status="TERMINAL")
    terminal["outcome"] = "COMPLETED"
    terminal["result_ref"] = "control/worker-results/preexisting.json"
    terminal["terminal_run_id"] = "run-preexisting"
    pre = queue_v31(terminal)
    kernel_v31.validate(pre)
    rollback = build_rollback_v31_queue(pre, queue_v4())
    assert rollback["tasks"] == [terminal]
    assert rollback["tasks"][0]["result_ref"] == "control/worker-results/preexisting.json"