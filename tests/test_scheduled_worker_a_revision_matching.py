from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_engine import scheduled_worker_a as worker_a


def _write_intake(path: Path, *, task_id: str, revision: str, marker: str) -> None:
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "project_id": marker,
                "queue_intent": {
                    "task_id": task_id,
                    "revision": revision,
                    "candidate_sha": "a" * 40,
                    "handover_id": "H2",
                },
            }
        ),
        encoding="utf-8",
    )


def test_matching_intake_prefers_exact_canonical_queue_revision(tmp_path: Path) -> None:
    intake_dir = tmp_path / "project-intake"
    intake_dir.mkdir()
    task_id = "EXHAUSTED-ASSURE"
    _write_intake(
        intake_dir / "historical.json",
        task_id=task_id,
        revision="EXHAUSTED-ASSURE-OLD",
        marker="historical",
    )
    _write_intake(
        intake_dir / "current.json",
        task_id=task_id,
        revision="EXHAUSTED-ASSURE-CURRENT",
        marker="current",
    )

    path, payload = worker_a._matching_intake(
        intake_dir,
        {"task_id": task_id, "intake_revision": "EXHAUSTED-ASSURE-CURRENT"},
    )

    assert path.name == "current.json"
    assert payload["project_id"] == "current"


def test_matching_intake_fails_closed_on_duplicate_exact_revision(tmp_path: Path) -> None:
    intake_dir = tmp_path / "project-intake"
    intake_dir.mkdir()
    task_id = "EXHAUSTED-ASSURE"
    for filename in ("one.json", "two.json"):
        _write_intake(
            intake_dir / filename,
            task_id=task_id,
            revision="EXHAUSTED-ASSURE-CURRENT",
            marker=filename,
        )

    with pytest.raises(worker_a.ActuatorContractError, match="duplicate project intakes"):
        worker_a._matching_intake(
            intake_dir,
            {"task_id": task_id, "intake_revision": "EXHAUSTED-ASSURE-CURRENT"},
        )


def test_matching_intake_without_revision_still_rejects_ambiguous_history(tmp_path: Path) -> None:
    intake_dir = tmp_path / "project-intake"
    intake_dir.mkdir()
    task_id = "EXHAUSTED-ASSURE"
    _write_intake(intake_dir / "old.json", task_id=task_id, revision="OLD", marker="old")
    _write_intake(intake_dir / "new.json", task_id=task_id, revision="NEW", marker="new")

    with pytest.raises(worker_a.ActuatorContractError, match="current_revision=None"):
        worker_a._matching_intake(intake_dir, {"task_id": task_id})
