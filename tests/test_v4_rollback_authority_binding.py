import copy
import json
from pathlib import Path

import pytest

from v4.authority import V4ValidationError, derive_rollback_v31_mission

SCHEMA_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def v4_mission() -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "ROLLBACK_BINDING",
        "mission_revision": "2026-09-02-r2",
        "repository": "example/project",
        "desired_outcome": "Prove rollback uses exact trusted Mission authority.",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/project",
                "acceptance": ["trusted acceptance"],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            }
        ],
        "authority_boundaries": ["no deployment authority"],
        "supersedes_revision": "2026-09-01-r1",
        "principal_manual_relay_count": 0,
    }


def v31_mission() -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "ROLLBACK_BINDING",
        "mission_revision": "2026-09-01-r1",
        "repository": "example/project",
        "desired_outcome": "prior",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/project",
                "operation": "IMPLEMENTATION",
                "acceptance": ["prior acceptance"],
                "integration_policy": "HOLD_AFTER_PASS",
            }
        ],
        "authority_boundaries": ["prior"],
        "principal_manual_relay_count": 0,
    }


def v31_global_authority(*, integration_enabled=False) -> dict:
    return {
        "protocol_id": "CONTROL_RUNTIME_AUTHORITY_V3_1",
        "control_runtime_enabled": True,
        "integration_enabled": integration_enabled,
        "semantic_claim_lease_seconds": 5400,
        "principal_manual_relay_count": 0,
    }


def v31_repository_authority(*, auto=False) -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V3_1",
        "repository": "example/project",
        "integration_policy": "AUTO_AFTER_PASS" if auto else "HOLD_AFTER_PASS",
        "control_auto_profile": "CONTROL_AUTO_V1" if auto else "NONE",
        "integration_enabled": auto,
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }


def authority_root(tmp_path: Path) -> Path:
    root = tmp_path / "authority"
    write_json(root / "control/missions/ROLLBACK_BINDING.mission.json", v4_mission())
    write_json(
        root / "control/repository-authority/example__project.json",
        {
            "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
            "repository": "example/project",
            "required_check_runs": [],
            "principal_manual_relay_count": 0,
        },
    )
    return root


def v31_authority_root(
    tmp_path: Path,
    *,
    current_mission=None,
    include_global=True,
    global_integration_enabled=False,
    repository_auto=False,
) -> Path:
    root = tmp_path / "v31-authority"
    write_json(
        root / "control/missions/ROLLBACK_BINDING.mission.json",
        current_mission or v31_mission(),
    )
    if include_global:
        write_json(
            root / "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
            v31_global_authority(integration_enabled=global_integration_enabled),
        )
    write_json(
        root / "control/repository-authority/example__project.json",
        v31_repository_authority(auto=repository_auto),
    )
    return root


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


def rollback_kwargs(tmp_path: Path, root: Path) -> dict:
    return {
        "pre_cutover_v31_authority_root": v31_authority_root(tmp_path),
        "pre_cutover_v31_queue": empty_v31_queue(),
        "v4_queue": empty_v4_queue(),
        "authority_root": root,
        "schema_root": SCHEMA_ROOT,
        "rollback_revision": "2026-09-02-r2",
    }


def test_rollback_rejects_same_identity_v4_mission_that_differs_from_trusted_authority(tmp_path):
    root = authority_root(tmp_path)
    tampered = copy.deepcopy(v4_mission())
    tampered["gaps"][0]["acceptance"] = ["caller supplied replacement acceptance"]

    with pytest.raises(V4ValidationError, match="differs from trusted authority"):
        derive_rollback_v31_mission(
            v31_mission(),
            tampered,
            **rollback_kwargs(tmp_path, root),
        )


def test_rollback_rejects_caller_supplied_v31_mission_that_differs_from_frozen_authority(tmp_path):
    root = authority_root(tmp_path)
    tampered = copy.deepcopy(v31_mission())
    tampered["gaps"][0]["acceptance"] = ["caller supplied rollback authority"]

    with pytest.raises(V4ValidationError, match="frozen V3.1 Mission differs from trusted authority"):
        derive_rollback_v31_mission(
            tampered,
            v4_mission(),
            **rollback_kwargs(tmp_path, root),
        )


def test_rollback_rejects_schema_invalid_frozen_v31_authority(tmp_path):
    root = authority_root(tmp_path)
    broken = v31_mission()
    del broken["gaps"][0]["operation"]
    frozen_root = v31_authority_root(tmp_path, current_mission=broken)

    with pytest.raises(V4ValidationError, match="frozen V3.1 Mission"):
        derive_rollback_v31_mission(
            broken,
            v4_mission(),
            pre_cutover_v31_authority_root=frozen_root,
            pre_cutover_v31_queue=empty_v31_queue(),
            v4_queue=empty_v4_queue(),
            authority_root=root,
            schema_root=SCHEMA_ROOT,
            rollback_revision="2026-09-02-r2",
        )


def test_rollback_rejects_missing_frozen_v31_global_authority(tmp_path):
    root = authority_root(tmp_path)
    frozen_root = v31_authority_root(tmp_path, include_global=False)

    with pytest.raises(V4ValidationError, match="global authority missing"):
        derive_rollback_v31_mission(
            v31_mission(),
            v4_mission(),
            pre_cutover_v31_authority_root=frozen_root,
            pre_cutover_v31_queue=empty_v31_queue(),
            v4_queue=empty_v4_queue(),
            authority_root=root,
            schema_root=SCHEMA_ROOT,
            rollback_revision="2026-09-02-r2",
        )


def test_rollback_rejects_v31_auto_gap_not_authorized_by_frozen_authority(tmp_path):
    root = authority_root(tmp_path)
    frozen = v31_mission()
    frozen["gaps"][0]["integration_policy"] = "AUTO_AFTER_PASS"
    frozen_root = v31_authority_root(tmp_path, current_mission=frozen)

    with pytest.raises(V4ValidationError, match="integration policy exceeds authority"):
        derive_rollback_v31_mission(
            frozen,
            v4_mission(),
            pre_cutover_v31_authority_root=frozen_root,
            pre_cutover_v31_queue=empty_v31_queue(),
            v4_queue=empty_v4_queue(),
            authority_root=root,
            schema_root=SCHEMA_ROOT,
            rollback_revision="2026-09-02-r2",
        )
