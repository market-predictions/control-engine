import copy
import json
from pathlib import Path

import pytest

from v4.authority import (
    V4ValidationError,
    derive_rollback_v31_mission,
    git_blob_sha,
    validate_v4_queue,
)

SCHEMA_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def repository_authority() -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": "example/project",
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }


def v4_mission(*, review_policy="INTERNAL") -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "BOUNDARY_TEST",
        "mission_revision": "2026-09-02-r3",
        "repository": "example/project",
        "desired_outcome": "Prove review/base and rollback authority boundaries.",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/project",
                "acceptance": ["boundary remains exact"],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": review_policy,
            }
        ],
        "authority_boundaries": ["no deployment authority"],
        "supersedes_revision": "2026-08-20-r2",
        "principal_manual_relay_count": 0,
    }


def v4_authority_root(tmp_path: Path, *, review_policy="INTERNAL") -> Path:
    root = tmp_path / "v4-authority"
    write_json(root / "control/missions/BOUNDARY_TEST.mission.json", v4_mission(review_policy=review_policy))
    write_json(
        root / "control/repository-authority/example__project.json",
        repository_authority(),
    )
    return root


def reviewed_task(root: Path, *, review_policy="INTERNAL") -> dict:
    candidate_sha = "a" * 40
    expected_base_sha = "b" * 40
    task = {
        "task_id": "boundary-task",
        "mission_id": "BOUNDARY_TEST",
        "mission_revision": "2026-09-02-r3",
        "mission_contract_blob_sha": git_blob_sha(root / "control/missions/BOUNDARY_TEST.mission.json"),
        "repository_authority_blob_sha": git_blob_sha(
            root / "control/repository-authority/example__project.json"
        ),
        "gap_id": "GAP_01",
        "repository": "example/project",
        "acceptance": ["boundary remains exact"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": review_policy,
        "convergence_required": False,
        "status": "READY",
        "phase": None,
        "candidate": {
            "candidate_sha": candidate_sha,
            "candidate_pr_number": 1,
            "candidate_head_branch": "candidate",
            "expected_base_branch": "main",
            "expected_base_sha": expected_base_sha,
        },
        "last_review": {
            "candidate_sha": candidate_sha,
            "expected_base_branch": "main",
            "expected_base_sha": expected_base_sha,
            "outcome": "PASS",
            "reviewed_at": "2026-09-02T12:00:00Z",
            "reviewer": "control-runner",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-02T10:00:00Z",
        "updated_at": "2026-09-02T12:00:00Z",
    }
    if review_policy == "EXTERNAL":
        task["external_review"] = {
            "candidate_sha": candidate_sha,
            "expected_base_branch": "main",
            "expected_base_sha": expected_base_sha,
            "provider": "codex",
            "request_key": "boundary-review",
            "request_ref": "review-1",
            "status": "PASS",
            "result_ref": "reviews/boundary.json",
        }
    return task


def queue(task: dict) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [task],
    }


def test_internal_review_same_candidate_but_different_base_is_rejected(tmp_path):
    root = v4_authority_root(tmp_path)
    task = reviewed_task(root)
    task["last_review"]["expected_base_sha"] = "c" * 40

    with pytest.raises(V4ValidationError, match="last_review candidate/base drift"):
        validate_v4_queue(queue(task), root, schema_root=SCHEMA_ROOT)


def test_external_review_same_candidate_but_different_base_is_rejected(tmp_path):
    root = v4_authority_root(tmp_path, review_policy="EXTERNAL")
    task = reviewed_task(root, review_policy="EXTERNAL")
    task["external_review"]["expected_base_branch"] = "release"

    with pytest.raises(V4ValidationError, match="external_review candidate/base drift"):
        validate_v4_queue(queue(task), root, schema_root=SCHEMA_ROOT)


def v31_gap(gap_id: str, *, repository="example/project", depends_on=None) -> dict:
    return {
        "gap_id": gap_id,
        "gap_state": "OPEN",
        "depends_on": depends_on or [],
        "repository": repository,
        "operation": "IMPLEMENTATION",
        "acceptance": [f"{gap_id} acceptance"],
        "integration_policy": "HOLD_AFTER_PASS",
    }


def v31_mission(gaps: list[dict]) -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "BOUNDARY_TEST",
        "mission_revision": "2026-08-20-r2",
        "repository": "example/project",
        "desired_outcome": "Frozen authority.",
        "gaps": gaps,
        "authority_boundaries": ["no deployment authority"],
        "principal_manual_relay_count": 0,
    }


def empty_v31_queue() -> dict:
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [],
        "tasks": [],
    }


def empty_v4_queue() -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [],
    }


def derive_with_frozen(tmp_path: Path, frozen: dict):
    v31_root = tmp_path / "v31-authority"
    write_json(v31_root / "control/missions/BOUNDARY_TEST.mission.json", frozen)
    v4_root = v4_authority_root(tmp_path)
    return derive_rollback_v31_mission(
        copy.deepcopy(frozen),
        v4_mission(),
        pre_cutover_v31_authority_root=v31_root,
        pre_cutover_v31_queue=empty_v31_queue(),
        v4_queue=empty_v4_queue(),
        authority_root=v4_root,
        schema_root=SCHEMA_ROOT,
        rollback_revision="2026-09-02-r3",
    )


def test_schema_valid_frozen_v31_gap_repository_mismatch_is_rejected(tmp_path):
    frozen = v31_mission([v31_gap("GAP_01", repository="example/other")])

    with pytest.raises(V4ValidationError, match="V3.1 gap repository mismatch"):
        derive_with_frozen(tmp_path, frozen)


def test_schema_valid_frozen_v31_dependency_cycle_is_rejected(tmp_path):
    frozen = v31_mission(
        [
            v31_gap("GAP_01", depends_on=["GAP_02"]),
            v31_gap("GAP_02", depends_on=["GAP_01"]),
        ]
    )

    with pytest.raises(V4ValidationError, match="V3.1 dependency cycle"):
        derive_with_frozen(tmp_path, frozen)
