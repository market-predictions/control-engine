import copy
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from v4.authority import (
    LEASE_SECONDS,
    PENDING_DRIFT_BLOCKER,
    V4ValidationError,
    derive_empty_rollback_v31_queue,
    derive_rollback_v31_mission,
    forward_queue_v31_to_v4,
    git_blob_sha,
    load_v4_authority,
    validate_v4_queue,
)

SCHEMA_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def mission(revision="2026-09-02-r3", supersedes="2026-08-20-r2", carry=None):
    result = {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "TEST_MISSION",
        "mission_revision": revision,
        "repository": "example/project",
        "desired_outcome": "Prove the smallest V4 contract.",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/project",
                "acceptance": ["one deterministic acceptance"],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "EXTERNAL",
            },
            {
                "gap_id": "GAP_02",
                "gap_state": "OPEN",
                "depends_on": ["GAP_01"],
                "repository": "example/project",
                "acceptance": ["second deterministic acceptance"],
                "integration_policy": "AUTO_AFTER_PASS",
                "review_policy": "INTERNAL",
                "convergence_required": True,
            },
        ],
        "authority_boundaries": ["no deployment authority"],
        "supersedes_revision": supersedes,
        "principal_manual_relay_count": 0,
    }
    if carry is not None:
        result["done_carry_forward"] = carry
        targets = {item["target_gap_id"] for item in carry}
        for gap in result["gaps"]:
            if gap["gap_id"] in targets:
                gap["gap_state"] = "RETIRED"
    return result


def migration_carry(target="GAP_01", source="GAP_01"):
    return {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": target,
        "source_mission_revision": "2026-08-20-r2",
        "source_gap_id": source,
        "source_fact_kind": "MIGRATION_FACT",
        "source_fact_ref": "legacy-gap-01",
    }


def repository_authority():
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": "example/project",
        "required_check_runs": ["tests"],
        "principal_manual_relay_count": 0,
    }


def authority_root(tmp_path: Path, *, current_mission=None) -> Path:
    root = tmp_path / "authority"
    write_json(
        root / "control/missions/TEST_MISSION.mission.json",
        current_mission or mission(),
    )
    write_json(
        root / "control/repository-authority/example__project.json",
        repository_authority(),
    )
    return root


def old_v31_queue(*, claimed=False):
    claim = {"run_id": "old"} if claimed else None
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [
            {
                "protocol_id": "CONTROL_V3_1_MIGRATION_FACT",
                "fact": "LEGACY_PROJECT_INTEGRATION_COMPLETED",
                "mission_id": "TEST_MISSION",
                "mission_revision": "2026-08-20-r2",
                "gap_id": "GAP_01",
                "repository": "example/project",
                "source_task_id": "legacy-gap-01",
                "source_result_ref": "control/worker-results/legacy.json",
                "imported_at": "2026-09-01T06:48:32Z",
                "principal_manual_relay_count": 0,
            }
        ],
        "tasks": [
            {
                "task_id": "old-gap-02",
                "repository": "example/project",
                "status": "QUEUED",
                "claim": claim,
                "outcome": None,
                "result_ref": None,
                "terminal_run_id": None,
                "created_at": "2026-09-01T12:00:00Z",
                "updated_at": "2026-09-01T12:00:00Z",
                "mission_id": "TEST_MISSION",
                "mission_revision": "2026-08-20-r2",
                "gap_id": "GAP_02",
            }
        ],
    }


def test_v4_contracts_keep_global_admin_flags_out_of_queue_and_repository():
    queue_schema = json.loads((SCHEMA_ROOT / "schemas/dispatch_queue_v4.schema.json").read_text())
    repo_schema = json.loads((SCHEMA_ROOT / "schemas/repository_authority_v4.schema.json").read_text())
    assert "control_runtime_enabled" not in queue_schema["properties"]
    assert "integration_enabled" not in queue_schema["properties"]
    assert "integration_enabled" not in repo_schema["properties"]


def test_authority_accepts_omitted_convergence_as_false(tmp_path):
    root = authority_root(tmp_path)
    missions, _, _, _ = load_v4_authority(root, schema_root=SCHEMA_ROOT)
    assert "convergence_required" not in missions["TEST_MISSION"]["gaps"][0]


def test_authority_rejects_duplicate_json_keys(tmp_path):
    root = authority_root(tmp_path)
    path = root / "control/missions/TEST_MISSION.mission.json"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '  "mission_id": "TEST_MISSION",',
        '  "mission_id": "TEST_MISSION",\n  "mission_id": "TEST_MISSION",',
        1,
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(V4ValidationError, match="duplicate JSON key: mission_id"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_authority_rejects_invalid_github_repository_identity(tmp_path):
    current = mission()
    current["repository"] = "../project"
    root = authority_root(tmp_path, current_mission=current)
    with pytest.raises(V4ValidationError, match="repository identity invalid"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_forward_transform_materializes_only_currently_eligible_roots(tmp_path):
    old = old_v31_queue()
    root = authority_root(tmp_path)
    result = forward_queue_v31_to_v4(old, root, schema_root=SCHEMA_ROOT)

    assert result["version"] == "4.0"
    assert result["execution_lock"] is None
    assert result["migration_facts"] == old["migration_facts"]
    assert all(fact["fact"] != "DONE_CARRY_FORWARD" for fact in result["migration_facts"])
    assert len(result["tasks"]) == 1
    tasks = {task["gap_id"]: task for task in result["tasks"]}
    assert set(tasks) == {"GAP_01"}
    assert tasks["GAP_01"]["created_at"] == old["migration_facts"][0]["imported_at"]
    assert tasks["GAP_01"]["status"] == "QUEUED"
    assert tasks["GAP_01"]["phase"] == "BUILD"
    assert tasks["GAP_01"]["candidate"] is None


def test_forward_transform_fails_if_eligible_gap_has_no_frozen_source_evidence(tmp_path):
    old = old_v31_queue()
    old["migration_facts"] = []
    root = authority_root(tmp_path)
    with pytest.raises(V4ValidationError, match="cannot materialize eligible current OPEN gap"):
        forward_queue_v31_to_v4(old, root, schema_root=SCHEMA_ROOT)


def test_protected_mission_carry_forward_validates_against_imported_source_fact(tmp_path):
    root = authority_root(tmp_path, current_mission=mission(carry=[migration_carry()]))
    result = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    validate_v4_queue(result, root, schema_root=SCHEMA_ROOT)
    current = json.loads((root / "control/missions/TEST_MISSION.mission.json").read_text())
    assert current["done_carry_forward"] == [migration_carry()]
    assert current["gaps"][0]["gap_state"] == "RETIRED"
    assert {task["gap_id"] for task in result["tasks"]} == {"GAP_02"}


def test_carry_forward_target_must_be_retired(tmp_path):
    current = mission(carry=[migration_carry()])
    current["gaps"][0]["gap_state"] = "OPEN"
    root = authority_root(tmp_path, current_mission=current)
    with pytest.raises(V4ValidationError, match="carry-forward target must be RETIRED"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_open_gap_cannot_depend_on_retired_gap_without_carry_forward(tmp_path):
    current = mission()
    current["gaps"][0]["gap_state"] = "RETIRED"
    root = authority_root(tmp_path, current_mission=current)
    with pytest.raises(V4ValidationError, match="RETIRED dependency GAP_01 requires carry-forward"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_future_revision_cannot_be_carry_forward_source(tmp_path):
    carry = migration_carry()
    carry["source_mission_revision"] = "2026-09-03-r4"
    root = authority_root(tmp_path, current_mission=mission(carry=[carry]))
    with pytest.raises(V4ValidationError, match="source must be an older revision"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_carry_forward_missing_source_fact_fails_closed(tmp_path):
    broken = migration_carry()
    broken["source_fact_ref"] = "missing"
    root = authority_root(tmp_path, current_mission=mission(carry=[broken]))
    with pytest.raises(V4ValidationError, match="missing carry-forward migration fact"):
        forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)


def test_carry_forward_repository_mismatch_fails_closed(tmp_path):
    root = authority_root(tmp_path, current_mission=mission(carry=[migration_carry()]))
    queue = old_v31_queue()
    queue["migration_facts"][0]["repository"] = "other/project"
    with pytest.raises(V4ValidationError, match="carry-forward migration fact mismatch"):
        forward_queue_v31_to_v4(queue, root, schema_root=SCHEMA_ROOT)


def test_invalid_v31_migration_fact_shape_fails_closed(tmp_path):
    root = authority_root(tmp_path)
    queue = old_v31_queue()
    del queue["migration_facts"][0]["source_result_ref"]
    with pytest.raises(V4ValidationError, match="V3.1 migration facts are invalid"):
        forward_queue_v31_to_v4(queue, root, schema_root=SCHEMA_ROOT)


def test_duplicate_carry_forward_target_is_rejected(tmp_path):
    root = authority_root(
        tmp_path,
        current_mission=mission(carry=[migration_carry(), migration_carry()]),
    )
    with pytest.raises(V4ValidationError, match="duplicate carry-forward target"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_forward_transform_rejects_live_or_nonquiescent_v31_work(tmp_path):
    root = authority_root(tmp_path)
    with pytest.raises(V4ValidationError, match="quiescent"):
        forward_queue_v31_to_v4(old_v31_queue(claimed=True), root, schema_root=SCHEMA_ROOT)


def test_queue_binding_fails_closed_on_authority_drift(tmp_path):
    root = authority_root(tmp_path)
    queue = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    queue["tasks"][0]["acceptance"] = ["drifted"]
    with pytest.raises(V4ValidationError, match="acceptance drift"):
        validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)


def test_queue_lock_requires_exact_5400_second_lease_and_active_task(tmp_path):
    root = authority_root(tmp_path)
    queue = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    task = queue["tasks"][0]
    task["status"] = "ACTIVE"
    task["phase"] = "BUILD"
    started = datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc)
    queue["execution_lock"] = {
        "run_id": "run-1",
        "task_id": task["task_id"],
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "expires_at": (started + timedelta(seconds=LEASE_SECONDS)).isoformat().replace("+00:00", "Z"),
    }
    validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)

    queue["execution_lock"]["expires_at"] = (
        started + timedelta(seconds=LEASE_SECONDS - 1)
    ).isoformat().replace("+00:00", "Z")
    with pytest.raises(V4ValidationError, match="5400"):
        validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)


def test_unlocked_active_task_is_valid_and_lock_must_target_active_task(tmp_path):
    root = authority_root(tmp_path)
    queue = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    task = queue["tasks"][0]
    task["status"] = "ACTIVE"
    task["phase"] = "BUILD"

    validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)

    queue["execution_lock"] = {
        "run_id": "run-1",
        "task_id": task["task_id"],
        "started_at": "2026-09-02T10:00:00Z",
        "expires_at": "2026-09-02T11:30:00Z",
    }
    validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)

    queue["execution_lock"]["task_id"] = "missing-task"
    with pytest.raises(V4ValidationError, match="target an ACTIVE task"):
        validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)


def test_pending_drift_marker_is_durable_active_review_provenance(tmp_path):
    root = authority_root(tmp_path)
    queue = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    task = queue["tasks"][0]
    task["status"] = "ACTIVE"
    task["phase"] = "REVIEW"
    task["blocker"] = PENDING_DRIFT_BLOCKER

    validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)

    task["status"] = "READY"
    task["phase"] = None
    with pytest.raises(V4ValidationError, match="requires ACTIVE/REVIEW"):
        validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)


def test_fractional_lock_extension_is_not_truncated(tmp_path):
    root = authority_root(tmp_path)
    queue = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    task = queue["tasks"][0]
    task["status"] = "ACTIVE"
    task["phase"] = "BUILD"
    queue["execution_lock"] = {
        "run_id": "run-1",
        "task_id": task["task_id"],
        "started_at": "2026-09-02T10:00:00.000000Z",
        "expires_at": "2026-09-02T11:30:00.000001Z",
    }
    with pytest.raises(V4ValidationError, match="5400"):
        validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)


def test_dependency_cycle_is_rejected(tmp_path):
    root = authority_root(tmp_path)
    current = mission()
    current["gaps"][0]["depends_on"] = ["GAP_02"]
    write_json(root / "control/missions/TEST_MISSION.mission.json", current)
    with pytest.raises(V4ValidationError, match="cycle"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_historical_nonterminal_task_is_rejected(tmp_path):
    root = authority_root(tmp_path)
    queue = forward_queue_v31_to_v4(old_v31_queue(), root, schema_root=SCHEMA_ROOT)
    historical = copy.deepcopy(queue["tasks"][0])
    historical["task_id"] = "historical-active"
    historical["mission_revision"] = "2026-08-20-r2"
    historical["status"] = "ACTIVE"
    historical["phase"] = "BUILD"
    queue["tasks"].append(historical)
    with pytest.raises(V4ValidationError, match="terminal historical fact"):
        validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)


def v31_mission():
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "TEST_MISSION",
        "mission_revision": "2026-08-20-r2",
        "repository": "example/project",
        "desired_outcome": "old",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/project",
                "operation": "IMPLEMENTATION",
                "acceptance": ["prior GAP_01 acceptance"],
                "integration_policy": "HOLD_AFTER_PASS",
            },
            {
                "gap_id": "GAP_02",
                "gap_state": "OPEN",
                "depends_on": ["GAP_01"],
                "repository": "example/project",
                "operation": "IMPLEMENTATION",
                "acceptance": ["prior GAP_02 acceptance"],
                "integration_policy": "AUTO_AFTER_PASS",
            },
        ],
        "authority_boundaries": ["old"],
        "principal_manual_relay_count": 0,
    }


def v31_authority_root(root: Path) -> Path:
    frozen = root.parent / "v31-authority"
    write_json(
        frozen / "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
        {
            "protocol_id": "CONTROL_RUNTIME_AUTHORITY_V3_1",
            "control_runtime_enabled": True,
            "integration_enabled": True,
            "semantic_claim_lease_seconds": LEASE_SECONDS,
            "principal_manual_relay_count": 0,
        },
    )
    write_json(
        frozen / "control/repository-authority/example__project.json",
        {
            "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V3_1",
            "repository": "example/project",
            "integration_policy": "AUTO_AFTER_PASS",
            "control_auto_profile": "CONTROL_AUTO_V1",
            "integration_enabled": True,
            "required_check_runs": [],
            "principal_manual_relay_count": 0,
        },
    )
    write_json(frozen / "control/missions/TEST_MISSION.mission.json", v31_mission())
    return frozen


def v4_queue_for_rollback(root: Path, *, old_queue=None, done_gap_02=False):
    source = copy.deepcopy(old_queue if old_queue is not None else old_v31_queue())
    queue = forward_queue_v31_to_v4(source, root, schema_root=SCHEMA_ROOT)
    if done_gap_02:
        task = next(task for task in queue["tasks"] if task["gap_id"] == "GAP_02")
        candidate_sha = "a" * 40
        task["status"] = "DONE"
        task["phase"] = None
        task["candidate"] = {
            "candidate_sha": candidate_sha,
            "candidate_pr_number": 1,
            "candidate_head_branch": "candidate",
            "expected_base_branch": "main",
            "expected_base_sha": "b" * 40,
        }
        task["last_review"] = {
            "candidate_sha": candidate_sha,
            "expected_base_branch": "main",
            "expected_base_sha": "b" * 40,
            "outcome": "PASS",
            "reviewed_at": "2026-09-02T12:00:00Z",
            "reviewer": "control-runner",
        }
        task["external_review"] = None
        task["blocker"] = None
    return queue


def rollback_kwargs(root: Path, *, pre_cutover_queue=None, v4_queue=None):
    old_queue = pre_cutover_queue if pre_cutover_queue is not None else old_v31_queue()
    current_v4_queue = v4_queue if v4_queue is not None else v4_queue_for_rollback(root)
    return {
        "pre_cutover_v31_authority_root": v31_authority_root(root),
        "pre_cutover_v31_queue": old_queue,
        "v4_queue": current_v4_queue,
        "authority_root": root,
        "schema_root": SCHEMA_ROOT,
    }


def test_rollback_keeps_v4_reopened_gap_open_and_retires_only_realized_v4_work(tmp_path):
    current = mission()
    current["gaps"][1]["depends_on"] = []
    root = authority_root(tmp_path, current_mission=current)
    v4_queue = v4_queue_for_rollback(root, done_gap_02=True)
    rollback = derive_rollback_v31_mission(
        v31_mission(),
        current,
        **rollback_kwargs(root, v4_queue=v4_queue),
        rollback_revision="2026-09-02-r3",
    )
    assert rollback["mission_revision"] == "2026-09-02-r3"
    assert {gap["gap_id"]: gap["gap_state"] for gap in rollback["gaps"]} == {
        "GAP_01": "OPEN",
        "GAP_02": "RETIRED",
    }

    queue = derive_empty_rollback_v31_queue(old_v31_queue())
    assert queue["tasks"] == []
    assert "worker_results" not in queue
    assert queue["principal_manual_relay_count"] == 0


def test_rollback_removes_only_protected_carried_prerequisites_from_open_dependencies(tmp_path):
    current = mission(carry=[migration_carry()])
    root = authority_root(tmp_path, current_mission=current)
    rollback = derive_rollback_v31_mission(
        v31_mission(),
        current,
        **rollback_kwargs(root),
        rollback_revision="2026-09-02-r3",
    )
    states = {gap["gap_id"]: gap for gap in rollback["gaps"]}
    assert states["GAP_01"]["gap_state"] == "RETIRED"
    assert states["GAP_02"]["gap_state"] == "OPEN"
    assert states["GAP_02"]["depends_on"] == []


def test_rollback_does_not_accept_unproven_legacy_completion(tmp_path):
    root = authority_root(tmp_path)
    queue = old_v31_queue()
    queue["migration_facts"] = []
    gap_01_task = copy.deepcopy(queue["tasks"][0])
    gap_01_task["task_id"] = "old-gap-01"
    gap_01_task["gap_id"] = "GAP_01"
    gap_01_task["created_at"] = "2026-09-01T11:00:00Z"
    gap_01_task["updated_at"] = "2026-09-01T11:00:00Z"
    queue["tasks"].append(gap_01_task)
    current_v4_queue = v4_queue_for_rollback(root, old_queue=queue)
    rollback = derive_rollback_v31_mission(
        v31_mission(),
        mission(),
        **rollback_kwargs(root, pre_cutover_queue=queue, v4_queue=current_v4_queue),
        rollback_revision="2026-09-02-r3",
    )
    assert {gap["gap_id"]: gap["gap_state"] for gap in rollback["gaps"]} == {
        "GAP_01": "OPEN",
        "GAP_02": "OPEN",
    }


def test_rollback_protected_legacy_carry_requires_exact_frozen_source_fact(tmp_path):
    current = mission(carry=[migration_carry()])
    root = authority_root(tmp_path, current_mission=current)
    valid_v4_queue = v4_queue_for_rollback(root)
    frozen = old_v31_queue()
    frozen["migration_facts"] = []
    with pytest.raises(V4ValidationError, match="source missing from frozen V3.1 facts"):
        derive_rollback_v31_mission(
            v31_mission(),
            current,
            **rollback_kwargs(root, pre_cutover_queue=frozen, v4_queue=valid_v4_queue),
            rollback_revision="2026-09-02-r3",
        )


def test_rollback_has_no_free_form_realization_channel(tmp_path):
    assert "realized_facts" not in inspect.signature(derive_rollback_v31_mission).parameters
    root = authority_root(tmp_path)
    rollback = derive_rollback_v31_mission(
        v31_mission(),
        mission(),
        **rollback_kwargs(root),
        rollback_revision="2026-09-02-r3",
    )
    states = {gap["gap_id"]: gap["gap_state"] for gap in rollback["gaps"]}
    assert states["GAP_01"] == "OPEN"
    assert states["GAP_02"] == "OPEN"


def test_rollback_done_task_requires_pass_review_evidence(tmp_path):
    root = authority_root(tmp_path)
    v4_queue = v4_queue_for_rollback(root)
    task = next(task for task in v4_queue["tasks"] if task["gap_id"] == "GAP_01")
    task["status"] = "DONE"
    task["phase"] = None
    with pytest.raises(V4ValidationError, match="lacks reviewed candidate evidence"):
        derive_rollback_v31_mission(
            v31_mission(),
            mission(),
            **rollback_kwargs(root, v4_queue=v4_queue),
            rollback_revision="2026-09-02-r3",
        )


def test_rollback_revision_must_advance_v31_discipline(tmp_path):
    root = authority_root(tmp_path)
    with pytest.raises(V4ValidationError, match="advance monotonically"):
        derive_rollback_v31_mission(
            v31_mission(),
            mission(),
            **rollback_kwargs(root),
            rollback_revision="2026-09-02-r2",
        )


def test_git_blob_binding_changes_when_authority_changes(tmp_path):
    root = authority_root(tmp_path)
    path = root / "control/missions/TEST_MISSION.mission.json"
    first = git_blob_sha(path)
    changed = mission()
    changed["desired_outcome"] = "changed"
    write_json(path, changed)
    assert git_blob_sha(path) != first
