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
            }
        ],
        "authority_boundaries": ["prior"],
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


def test_rollback_rejects_same_identity_mission_that_differs_from_trusted_authority(tmp_path):
    root = authority_root(tmp_path)
    tampered = copy.deepcopy(v4_mission())
    tampered["gaps"][0]["acceptance"] = ["caller supplied replacement acceptance"]

    with pytest.raises(V4ValidationError, match="differs from trusted authority"):
        derive_rollback_v31_mission(
            v31_mission(),
            tampered,
            pre_cutover_v31_queue=empty_v31_queue(),
            v4_queue=empty_v4_queue(),
            authority_root=root,
            schema_root=SCHEMA_ROOT,
            rollback_revision="2026-09-02-r2",
        )
