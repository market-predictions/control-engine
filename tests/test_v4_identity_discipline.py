import json
from pathlib import Path

import pytest

from v4.authority import V4ValidationError, load_v4_authority

SCHEMA_ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def repository_authority(repository: str) -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": repository,
        "required_check_runs": ["tests"],
        "principal_manual_relay_count": 0,
    }


def mission(*, revision: str = "2026-09-02-r3", supersedes: str = "2026-08-20-r2") -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "TEST_IDENTITY",
        "mission_revision": revision,
        "repository": "example/project",
        "desired_outcome": "Validate canonical identity and revision discipline.",
        "gaps": [
            {
                "gap_id": "GAP_01",
                "gap_state": "OPEN",
                "depends_on": [],
                "repository": "example/project",
                "acceptance": ["identity remains deterministic"],
                "integration_policy": "HOLD_AFTER_PASS",
                "review_policy": "INTERNAL",
            }
        ],
        "authority_boundaries": ["no deployment authority"],
        "supersedes_revision": supersedes,
        "principal_manual_relay_count": 0,
    }


def test_repository_authority_case_variants_are_one_identity(tmp_path):
    root = tmp_path / "authority"
    write_json(root / "control/missions/TEST_IDENTITY.mission.json", mission())
    write_json(
        root / "control/repository-authority/one.json",
        repository_authority("Example/Project"),
    )
    write_json(
        root / "control/repository-authority/two.json",
        repository_authority("example/project"),
    )

    with pytest.raises(V4ValidationError, match="duplicate repository authority"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)


def test_superseding_mission_must_advance_monotonically(tmp_path):
    root = tmp_path / "authority"
    write_json(
        root / "control/missions/TEST_IDENTITY.mission.json",
        mission(revision="2026-08-01-r1", supersedes="2026-09-01-r2"),
    )
    write_json(
        root / "control/repository-authority/example__project.json",
        repository_authority("example/project"),
    )

    with pytest.raises(V4ValidationError, match="advance monotonically"):
        load_v4_authority(root, schema_root=SCHEMA_ROOT)
