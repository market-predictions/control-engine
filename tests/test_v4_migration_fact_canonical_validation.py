from datetime import datetime, timezone

import pytest

from control_engine import kernel_v31
from control_engine.v4_contracts import (
    V4ValidationError,
    forward_transform_v31_to_v4,
    validate_carry_forward_evidence,
    validate_queue_v4,
)


NOW = datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc)


def _noncanonical_fact() -> dict:
    return {
        "protocol_id": "CONTROL_V3_1_MIGRATION_FACT",
        "fact": "LEGACY_PROJECT_INTEGRATION_COMPLETED",
        "mission_id": "M",
        "mission_revision": "2026-09-01-r1",
        "gap_id": "G--OLD",
        "repository": "example/repo",
        "source_task_id": "legacy-G",
        "source_result_ref": "control/worker-results/G-old.json",
        "imported_at": "2026-09-03T12:00:00Z",
        "principal_manual_relay_count": 0,
    }


def _mission() -> dict:
    return {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "M",
        "mission_revision": "2026-09-03-r2",
        "repository": "example/repo",
        "desired_outcome": "bounded outcome",
        "gaps": [{
            "gap_id": "G0",
            "gap_state": "RETIRED",
            "depends_on": [],
            "repository": "example/repo",
            "acceptance": ["preserve only canonical completion evidence"],
            "integration_policy": "HOLD_AFTER_PASS",
            "review_policy": "INTERNAL",
        }],
        "done_carry_forward": [{
            "protocol_id": "DONE_CARRY_FORWARD",
            "target_gap_id": "G0",
            "source_mission_revision": "2026-09-01-r1",
            "source_gap_id": "G--OLD",
            "source_fact_kind": "MIGRATION_FACT",
            "source_fact_ref": "control/worker-results/G-old.json",
        }],
        "authority_boundaries": ["no production authority"],
        "principal_manual_relay_count": 0,
    }


def _authority() -> dict:
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": "example/repo",
        "required_check_runs": ["CI"],
        "principal_manual_relay_count": 0,
    }


def test_noncanonical_v31_migration_fact_cannot_cross_forward_or_carry_forward_boundary() -> None:
    fact = _noncanonical_fact()
    pre_v31 = {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [fact],
        "tasks": [],
    }

    # The V3.1 kernel validates queue/task shape only; canonical migration-fact
    # semantics deliberately live in migration_v31 and must be reused by V4.
    kernel_v31.validate(pre_v31)

    with pytest.raises(V4ValidationError, match="noncanonical V3.1 migration facts"):
        forward_transform_v31_to_v4(
            pre_v31,
            missions=[_mission()],
            mission_blob_shas={"M": "a" * 40},
            authorities=[_authority()],
            authority_blob_shas={"example/repo": "b" * 40},
            transformed_at=NOW,
        )

    v4_queue = {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [fact],
        "tasks": [],
    }
    with pytest.raises(V4ValidationError, match="noncanonical V3.1 migration facts"):
        validate_queue_v4(v4_queue)
    with pytest.raises(V4ValidationError, match="noncanonical V3.1 migration facts"):
        validate_carry_forward_evidence(_mission(), v4_queue)
