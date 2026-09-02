from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

import pytest

from control_engine import kernel_v31
from control_engine.v4_authority_io import (
    assert_v4_queue_bound_to_authority,
    forward_transform_v31_to_v4_from_git,
    load_v31_missions_from_git,
    load_v4_authority_from_git,
)
from control_engine.v4_contracts import V4ValidationError


NOW = datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc)


def _mission() -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "M",
        "mission_revision": "2026-09-02-r2",
        "repository": "example/repo",
        "desired_outcome": "bounded outcome",
        "gaps": [{
            "gap_id": "G1",
            "gap_state": "OPEN",
            "depends_on": [],
            "repository": "example/repo",
            "acceptance": ["accept G1"],
            "integration_policy": "HOLD_AFTER_PASS",
            "review_policy": "INTERNAL",
        }],
        "authority_boundaries": ["no production authority"],
        "principal_manual_relay_count": 0,
    }


def _v31_mission() -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "M",
        "mission_revision": "2026-09-01-r1",
        "repository": "example/repo",
        "desired_outcome": "bounded outcome",
        "gaps": [{
            "gap_id": "G1",
            "gap_state": "OPEN",
            "depends_on": [],
            "repository": "example/repo",
            "operation": "IMPLEMENTATION",
            "acceptance": ["accept G1"],
            "integration_policy": "HOLD_AFTER_PASS",
        }],
        "authority_boundaries": ["no production authority"],
        "supersedes_revision": None,
        "principal_manual_relay_count": 0,
    }


def _authority() -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": "example/repo",
        "required_check_runs": ["CI"],
        "principal_manual_relay_count": 0,
    }


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.strip()


def _commit_authority(root: Path, mission: dict | str, authority: dict | None = None) -> None:
    (root / "control/missions").mkdir(parents=True, exist_ok=True)
    (root / "control/repository-authority").mkdir(parents=True, exist_ok=True)
    mission_text = mission if isinstance(mission, str) else json.dumps(mission, indent=2) + "\n"
    (root / "control/missions/M.mission.json").write_text(mission_text, encoding="utf-8")
    (root / "control/repository-authority/example__repo.json").write_text(
        json.dumps(authority or _authority(), indent=2) + "\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "authority")


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "authority"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Control Test")
    _commit_authority(root, _mission())
    return root


def _v31_queue() -> dict:
    task = {
        "lifecycle_model": kernel_v31.PROTOCOL_ID,
        "task_id": "MISSION--M--2026-09-01-r1--G1",
        "operation": "IMPLEMENTATION",
        "role": kernel_v31.ROLE_A,
        "repository": "example/repo",
        "status": kernel_v31.STATUS_QUEUED,
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
        "gap_id": "G1",
        "integration_policy": "HOLD_AFTER_PASS",
        "acceptance": ["accept G1"],
    }
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [],
        "tasks": [task],
    }


def test_loader_binds_exact_committed_git_blob_shas(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    bundle = load_v4_authority_from_git(root)

    expected_mission = _git(root, "rev-parse", "HEAD:control/missions/M.mission.json")
    expected_authority = _git(root, "rev-parse", "HEAD:control/repository-authority/example__repo.json")
    assert bundle.mission_blob_shas == {"M": expected_mission}
    assert bundle.authority_blob_shas == {"example/repo": expected_authority}


def test_loader_rejects_ambiguous_duplicate_json_key(tmp_path: Path) -> None:
    root = tmp_path / "authority"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Control Test")
    raw = json.dumps(_mission())
    raw = raw[:-1] + ',"mission_id":"OTHER"}'
    _commit_authority(root, raw)

    with pytest.raises(V4ValidationError, match="invalid or ambiguous"):
        load_v4_authority_from_git(root)


def test_changed_committed_mission_changes_trusted_blob_identity(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    before = load_v4_authority_from_git(root).mission_blob_shas["M"]
    mission = _mission()
    mission["desired_outcome"] = "changed bounded outcome"
    _commit_authority(root, mission)
    after = load_v4_authority_from_git(root).mission_blob_shas["M"]

    assert after != before


def test_forward_transform_uses_actual_authority_blob_shas(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    bundle = load_v4_authority_from_git(root)
    result = forward_transform_v31_to_v4_from_git(
        _v31_queue(), authority_root=root, transformed_at=NOW
    )

    task = result["tasks"][0]
    assert task["mission_contract_blob_sha"] == bundle.mission_blob_shas["M"]
    assert task["repository_authority_blob_sha"] == bundle.authority_blob_shas["example/repo"]


def test_queue_binding_rejects_caller_supplied_fake_authority_sha(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    bundle = load_v4_authority_from_git(root)
    queue = forward_transform_v31_to_v4_from_git(
        _v31_queue(), authority_root=root, transformed_at=NOW
    )
    assert_v4_queue_bound_to_authority(queue, bundle)

    forged = deepcopy(queue)
    forged["tasks"][0]["mission_contract_blob_sha"] = "f" * 40
    with pytest.raises(V4ValidationError, match="trusted Git authority"):
        assert_v4_queue_bound_to_authority(forged, bundle)


def test_frozen_v4_mission_blob_set_drift_fails_closed(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    bundle = load_v4_authority_from_git(root)
    queue = forward_transform_v31_to_v4_from_git(
        _v31_queue(), authority_root=root, transformed_at=NOW
    )

    with pytest.raises(V4ValidationError, match="drifted from frozen cutover set"):
        assert_v4_queue_bound_to_authority(
            queue, bundle, expected_mission_blob_shas={"M": "0" * 40}
        )


def test_frozen_v31_loader_rejects_mission_only_incomplete_authority(tmp_path: Path) -> None:
    root = tmp_path / "frozen-v31"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Control Test")
    (root / "control/missions").mkdir(parents=True)
    (root / "control/missions/M.mission.json").write_text(
        json.dumps(_v31_mission(), indent=2) + "\n", encoding="utf-8"
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "incomplete frozen V3.1 authority")

    with pytest.raises(V4ValidationError, match="complete frozen V3.1 authority|frozen V3.1 authority"):
        load_v31_missions_from_git(root)