from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from control_engine.v4_contracts import (
    V4ValidationError,
    acquire_task_v4,
    build_rollback_v31_queue,
)
from scripts import validate_private_control_v31 as v31_private_validator


NOW = datetime(2026, 9, 2, 22, 15, tzinfo=timezone.utc)


def _candidate() -> dict:
    return {
        "candidate_sha": "c" * 40,
        "candidate_pr_number": 7,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": "d" * 40,
    }


def _review_pass() -> dict:
    return {
        "candidate_sha": "c" * 40,
        "expected_base_branch": "main",
        "expected_base_sha": "d" * 40,
        "verdict": "PASS",
        "reviewed_at": "2026-09-02T22:00:00Z",
    }


def _active_integrate_queue() -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [{
            "task_id": "T1",
            "mission_id": "M",
            "mission_revision": "2026-09-02-r2",
            "mission_contract_blob_sha": "a" * 40,
            "repository_authority_blob_sha": "b" * 40,
            "gap_id": "G1",
            "repository": "example/repo",
            "acceptance": ["accept G1"],
            "integration_policy": "AUTO_AFTER_PASS",
            "review_policy": "INTERNAL",
            "convergence_required": False,
            "status": "ACTIVE",
            "phase": "INTEGRATE",
            "candidate": _candidate(),
            "last_review": _review_pass(),
            "external_review": None,
            "blocker": None,
            "created_at": "2026-09-02T21:00:00Z",
            "updated_at": "2026-09-02T21:00:00Z",
        }],
    }


def _empty_v4_queue() -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [],
    }


def test_active_integrate_cannot_reacquire_when_integration_is_disabled() -> None:
    queue = _active_integrate_queue()
    original = deepcopy(queue)

    with pytest.raises(V4ValidationError, match="integration disabled"):
        acquire_task_v4(
            queue,
            task_id="T1",
            run_id="run-2",
            now=NOW,
            control_runtime_enabled=True,
            integration_enabled=False,
        )

    assert queue == original
    assert queue["execution_lock"] is None


def test_rollback_rejects_malformed_preserved_v31_migration_fact() -> None:
    malformed_fact = {
        "protocol_id": "CONTROL_V3_1_MIGRATION_FACT",
        "fact": "LEGACY_PROJECT_INTEGRATION_COMPLETED",
        "mission_id": "M",
        "mission_revision": "2026-09-01-r1",
        "gap_id": "G1",
        "repository": "example/repo",
        # source_task_id deliberately missing: canonical V3.1 runtime rejects this.
        "source_result_ref": "control/worker-results/G1.json",
        "imported_at": "2026-09-02T21:00:00Z",
        "principal_manual_relay_count": 0,
    }
    pre_v31_queue = {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [malformed_fact],
        "tasks": [],
    }

    with pytest.raises(V4ValidationError, match="pre-cutover V3.1 queue invalid"):
        build_rollback_v31_queue(pre_v31_queue, _empty_v4_queue())


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


def test_trusted_v31_git_reader_ignores_local_replacement_refs(tmp_path: Path) -> None:
    root = tmp_path / "frozen-v31"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Control Test")

    original_path = root / "authority.json"
    original_path.write_text('{"value":"committed"}\n', encoding="utf-8")
    _git(root, "add", "authority.json")
    _git(root, "commit", "-m", "frozen authority")
    original_oid = _git(root, "rev-parse", "HEAD:authority.json")

    replacement_path = root / "replacement.json"
    replacement_path.write_text('{"value":"replacement"}\n', encoding="utf-8")
    replacement_oid = _git(root, "hash-object", "-w", "replacement.json")
    _git(root, "replace", original_oid, replacement_oid)

    assert b"replacement" in subprocess.run(
        ["git", "cat-file", "blob", original_oid],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout

    trusted = v31_private_validator.git_bytes(root, "cat-file", "blob", original_oid)
    assert trusted == b'{"value":"committed"}\n'
