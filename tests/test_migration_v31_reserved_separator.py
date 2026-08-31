from datetime import datetime, timezone

import pytest

from control_engine import migration_v31 as migration

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)


def _queue():
    return {"version": migration.LEGACY_QUEUE_VERSION, "principal_manual_relay_count": 0, "tasks": []}


def _mission(*, mission_id="M1", revision="r1", gap_id="G1"):
    return {
        "mission": {
            "mission_id": mission_id,
            "mission_revision": revision,
            "repository": "o/r",
            "gaps": [
                {
                    "gap_id": gap_id,
                    "gap_state": "OPEN",
                    "depends_on": [],
                    "repository": "o/r",
                    "operation": "IMPLEMENTATION",
                    "acceptance": ["done"],
                    "integration_policy": "HOLD_AFTER_PASS",
                }
            ],
        }
    }


def test_migration_rejects_reserved_successor_separator_in_task_identity_components():
    for wrapped in (
        _mission(mission_id="M--1"),
        _mission(revision="r--1"),
        _mission(gap_id="G--1"),
    ):
        with pytest.raises(migration.MigrationError, match="reserved task separator"):
            migration.migrate(_queue(), missions=[wrapped], now=NOW)
