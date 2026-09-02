import copy
import hashlib
import json
from pathlib import Path

import pytest

from v4.authority import V4ValidationError, derive_rollback_v31_mission

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


def repository_authority() -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": "example/project",
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }


def v31_gap(gap_id: str) -> dict:
    return {
        "gap_id": gap_id,
        "gap_state": "OPEN",
        "depends_on": [],
        "repository": "example/project",
        "operation": "IMPLEMENTATION",
        "acceptance": [f"{gap_id} acceptance"],
        "integration_policy": "HOLD_AFTER_PASS",
    }


def v31_mission(*gap_ids: str) -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "ROLLBACK_CARRY",
        "mission_revision": "2026-08-20-r2",
        "repository": "example/project",
        "desired_outcome": "Frozen pre-cutover authority.",
        "gaps": [v31_gap(gap_id) for gap_id in gap_ids],
        "authority_boundaries": ["no deployment authority"],
        "principal_manual_relay_count": 0,
    }


def v31_authority_root(tmp_path: Path, mission: dict) -> Path:
    root = tmp_path / "v31-authority"
    write_json(root / "control/missions/ROLLBACK_CARRY.mission.json", mission)
    return root


def v4_mission(carry: dict) -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "ROLLBACK_CARRY",
        "mission_revision": "2026-09-02-r4",
        "repository": "example/project",
        "desired_outcome": "Preserve exact completed work across rollback.",
        "gaps": [
            {
                "gap_id": "NEW_GAP",
                "gap_state": "RETIRED",
                "depends_on": [],
                "repository": "example/project",
                "acceptance": ["renamed work remains completed"],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            }
        ],
        "done_carry_forward": [carry],
        "authority_boundaries": ["no deployment authority"],
        "supersedes_revision": "2026-08-20-r2",
        "principal_manual_relay_count": 0,
    }


def v4_authority_root(tmp_path: Path, mission: dict) -> Path:
    root = tmp_path / "v4-authority"
    write_json(root / "control/missions/ROLLBACK_CARRY.mission.json", mission)
    write_json(
        root / "control/repository-authority/example__project.json",
        repository_authority(),
    )
    return root


def migration_fact() -> dict:
    return {
        "protocol_id": "CONTROL_V3_1_MIGRATION_FACT",
        "fact": "LEGACY_PROJECT_INTEGRATION_COMPLETED",
        "mission_id": "ROLLBACK_CARRY",
        "mission_revision": "2026-08-20-r2",
        "gap_id": "OLD_GAP",
        "repository": "example/project",
        "source_task_id": "legacy-old-gap",
        "source_result_ref": "control/worker-results/legacy-old-gap.json",
        "imported_at": "2026-09-01T06:48:32Z",
        "principal_manual_relay_count": 0,
    }


def v31_queue(*, facts=None) -> dict:
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": facts or [],
        "tasks": [],
    }


def v4_queue(*, facts=None, tasks=None) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": facts or [],
        "tasks": tasks or [],
    }


def historical_done_task() -> dict:
    candidate_sha = "a" * 40
    return {
        "task_id": "historical-old-gap",
        "mission_id": "ROLLBACK_CARRY",
        "mission_revision": "2026-09-01-r3",
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "gap_id": "OLD_GAP",
        "repository": "example/project",
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
            "expected_base_sha": "b" * 40,
        },
        "last_review": {
            "candidate_sha": candidate_sha,
            "expected_base_branch": "main",
            "expected_base_sha": "b" * 40,
            "outcome": "PASS",
            "reviewed_at": "2026-09-01T12:00:00Z",
            "reviewer": "control-runner",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-01T12:00:00Z",
    }


def derive(tmp_path: Path, frozen: dict, current: dict, *, old_queue: dict, current_queue: dict):
    return derive_rollback_v31_mission(
        copy.deepcopy(frozen),
        current,
        pre_cutover_v31_authority_root=v31_authority_root(tmp_path, frozen),
        pre_cutover_v31_queue=old_queue,
        v4_queue=current_queue,
        authority_root=v4_authority_root(tmp_path, current),
        schema_root=SCHEMA_ROOT,
        rollback_revision="2026-09-02-r3",
    )


def test_migration_carry_projects_back_to_frozen_source_gap_id(tmp_path):
    frozen = v31_mission("OLD_GAP")
    carry = {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "NEW_GAP",
        "source_mission_revision": "2026-08-20-r2",
        "source_gap_id": "OLD_GAP",
        "source_fact_kind": "MIGRATION_FACT",
        "source_fact_ref": "legacy-old-gap",
    }
    current = v4_mission(carry)
    fact = migration_fact()

    rollback = derive(
        tmp_path,
        frozen,
        current,
        old_queue=v31_queue(facts=[fact]),
        current_queue=v4_queue(facts=[fact]),
    )

    assert [(gap["gap_id"], gap["gap_state"]) for gap in rollback["gaps"]] == [
        ("OLD_GAP", "RETIRED")
    ]


def test_protected_historical_v4_done_survives_rollback(tmp_path):
    frozen = v31_mission("OLD_GAP")
    source = historical_done_task()
    carry = {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "NEW_GAP",
        "source_mission_revision": "2026-09-01-r3",
        "source_gap_id": "OLD_GAP",
        "source_fact_kind": "V4_DONE",
        "source_fact_ref": source["task_id"],
        "source_task_sha256": canonical_sha256(source),
    }
    current = v4_mission(carry)

    rollback = derive(
        tmp_path,
        frozen,
        current,
        old_queue=v31_queue(),
        current_queue=v4_queue(tasks=[source]),
    )

    assert [(gap["gap_id"], gap["gap_state"]) for gap in rollback["gaps"]] == [
        ("OLD_GAP", "RETIRED")
    ]


def test_historical_v4_done_from_frozen_v31_revision_fails_closed(tmp_path):
    frozen = v31_mission("OLD_GAP")
    source = historical_done_task()
    source["mission_revision"] = frozen["mission_revision"]
    carry = {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "NEW_GAP",
        "source_mission_revision": frozen["mission_revision"],
        "source_gap_id": "OLD_GAP",
        "source_fact_kind": "V4_DONE",
        "source_fact_ref": source["task_id"],
        "source_task_sha256": canonical_sha256(source),
    }
    current = v4_mission(carry)

    with pytest.raises(V4ValidationError, match="must postdate frozen V3.1 revision"):
        derive(
            tmp_path,
            frozen,
            current,
            old_queue=v31_queue(),
            current_queue=v4_queue(tasks=[source]),
        )


def test_historical_v4_done_ambiguous_frozen_mapping_fails_closed(tmp_path):
    frozen = v31_mission("OLD_GAP", "NEW_GAP")
    source = historical_done_task()
    carry = {
        "protocol_id": "DONE_CARRY_FORWARD",
        "target_gap_id": "NEW_GAP",
        "source_mission_revision": "2026-09-01-r3",
        "source_gap_id": "OLD_GAP",
        "source_fact_kind": "V4_DONE",
        "source_fact_ref": source["task_id"],
        "source_task_sha256": canonical_sha256(source),
    }
    current = v4_mission(carry)

    with pytest.raises(V4ValidationError, match="cannot map unambiguously"):
        derive(
            tmp_path,
            frozen,
            current,
            old_queue=v31_queue(),
            current_queue=v4_queue(tasks=[source]),
        )
