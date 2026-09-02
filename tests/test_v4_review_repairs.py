import copy
import hashlib
import json
from pathlib import Path

import pytest

from v4.authority import V4ValidationError, validate_v4_queue

SCHEMA_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def canonical_sha256(value: dict) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def repo(repository: str) -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": repository,
        "required_check_runs": ["tests"],
        "principal_manual_relay_count": 0,
    }


def migration_fact(repository: str = "example/secondary") -> dict:
    return {
        "protocol_id": "CONTROL_V3_1_MIGRATION_FACT",
        "fact": "LEGACY_PROJECT_INTEGRATION_COMPLETED",
        "mission_id": "TEST_MULTI",
        "mission_revision": "2026-08-20-r2",
        "gap_id": "GAP_01",
        "repository": repository,
        "source_task_id": "legacy-gap-01",
        "source_result_ref": "control/worker-results/legacy.json",
        "imported_at": "2026-09-01T06:48:32Z",
        "principal_manual_relay_count": 0,
    }


def mission(*, carry: dict, revision: str = "2026-09-02-r3") -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "TEST_MULTI",
        "mission_revision": revision,
        "repository": "example/primary",
        "desired_outcome": "Validate exact carry-forward boundaries.",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/secondary",
                "acceptance": ["secondary repository work is proven"],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL"
            }
        ],
        "done_carry_forward": [carry],
        "authority_boundaries": ["no deployment authority"],
        "supersedes_revision": "2026-08-20-r2",
        "principal_manual_relay_count": 0
    }


def migration_carry(*, source_revision: str = "2026-08-20-r2") -> dict:
    return {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "GAP_01",
        "source_mission_revision": source_revision,
        "source_gap_id": "GAP_01",
        "source_fact_kind": "MIGRATION_FACT",
        "source_fact_ref": "legacy-gap-01"
    }


def authority_root(tmp_path: Path, current_mission: dict) -> Path:
    root = tmp_path / "authority"
    write_json(root / "control/missions/TEST_MULTI.mission.json", current_mission)
    write_json(root / "control/repository-authority/example__primary.json", repo("example/primary"))
    write_json(root / "control/repository-authority/example__secondary.json", repo("example/secondary"))
    return root


def empty_queue(*, facts=None, tasks=None, lock=None) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": facts or [],
        "tasks": tasks or [],
    }


def test_carry_forward_binds_to_target_gap_repository(tmp_path):
    current = mission(carry=migration_carry())
    root = authority_root(tmp_path, current)
    queue = empty_queue(facts=[migration_fact("example/secondary")])
    validate_v4_queue(queue, root, schema_root=SCHEMA_ROOT)

    broken = copy.deepcopy(queue)
    broken["migration_facts"][0]["repository"] = "example/primary"
    with pytest.raises(V4ValidationError, match="carry-forward migration fact mismatch"):
        validate_v4_queue(broken, root, schema_root=SCHEMA_ROOT)


def test_carry_forward_rejects_future_or_nonmonotone_source_revision(tmp_path):
    current = mission(carry=migration_carry(source_revision="2026-09-03-r4"))
    root = authority_root(tmp_path, current)
    with pytest.raises(V4ValidationError, match="older revision"):
        validate_v4_queue(empty_queue(), root, schema_root=SCHEMA_ROOT)


def active_task(task_id: str, repository: str = "example/secondary") -> dict:
    return {
        "task_id": task_id,
        "mission_id": "TEST_MULTI",
        "mission_revision": "2026-09-02-r3",
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "gap_id": "GAP_01",
        "repository": repository,
        "acceptance": ["secondary repository work is proven"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "BUILD",
        "candidate": None,
        "last_review": None,
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-02T10:00:00Z",
        "updated_at": "2026-09-02T10:00:00Z"
    }


def test_active_task_requires_exactly_one_matching_lock(tmp_path):
    current = mission(carry=migration_carry())
    current.pop("done_carry_forward")
    root = authority_root(tmp_path, current)

    # Current-task authority hashes are intentionally refreshed from disk so the
    # failure under test is exclusively the ACTIVE/lock invariant.
    from v4.authority import git_blob_sha

    task = active_task("task-1")
    task["mission_contract_blob_sha"] = git_blob_sha(root / "control/missions/TEST_MULTI.mission.json")
    task["repository_authority_blob_sha"] = git_blob_sha(
        root / "control/repository-authority/example__secondary.json"
    )

    with pytest.raises(V4ValidationError, match="ACTIVE task requires exactly one execution_lock"):
        validate_v4_queue(empty_queue(tasks=[task]), root, schema_root=SCHEMA_ROOT)

    second = copy.deepcopy(task)
    second["task_id"] = "task-2"
    lock = {
        "run_id": "run-1",
        "task_id": "task-1",
        "started_at": "2026-09-02T10:00:00Z",
        "expires_at": "2026-09-02T11:30:00Z"
    }
    with pytest.raises(V4ValidationError, match="complete ACTIVE task set"):
        validate_v4_queue(empty_queue(tasks=[task, second], lock=lock), root, schema_root=SCHEMA_ROOT)


def historical_done_task() -> dict:
    candidate_sha = "a" * 40
    return {
        "task_id": "historical-done",
        "mission_id": "TEST_MULTI",
        "mission_revision": "2026-08-20-r2",
        "mission_contract_blob_sha": "3" * 40,
        "repository_authority_blob_sha": "4" * 40,
        "gap_id": "GAP_01",
        "repository": "example/secondary",
        "acceptance": ["historical acceptance"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "INTERNAL",
        "convergence_required": False,
        "status": "DONE",
        "phase": None,
        "candidate": {
            "candidate_sha": candidate_sha,
            "candidate_pr_number": 1,
            "candidate_head_branch": "candidate",
            "expected_base_branch": "main",
            "expected_base_sha": "b" * 40
        },
        "last_review": {
            "candidate_sha": candidate_sha,
            "outcome": "PASS",
            "reviewed_at": "2026-08-20T12:00:00Z",
            "reviewer": "control-runner"
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-08-20T10:00:00Z",
        "updated_at": "2026-08-20T12:00:00Z"
    }


def test_v4_done_carry_forward_is_bound_to_protected_task_digest(tmp_path):
    source = historical_done_task()
    carry = {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "GAP_01",
        "source_mission_revision": "2026-08-20-r2",
        "source_gap_id": "GAP_01",
        "source_fact_kind": "V4_DONE",
        "source_fact_ref": source["task_id"],
        "source_task_sha256": canonical_sha256(source)
    }
    root = authority_root(tmp_path, mission(carry=carry))
    validate_v4_queue(empty_queue(tasks=[source]), root, schema_root=SCHEMA_ROOT)

    reconstructed = copy.deepcopy(source)
    reconstructed["mission_contract_blob_sha"] = "f" * 40
    with pytest.raises(V4ValidationError, match="digest mismatch"):
        validate_v4_queue(empty_queue(tasks=[reconstructed]), root, schema_root=SCHEMA_ROOT)
