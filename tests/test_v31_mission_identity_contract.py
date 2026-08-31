import pytest

from scripts import validate_private_control_v31 as validator


def _minimal_mission(mission_id="M1", revision="r1", gap_id="G1", depends_on=None):
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": mission_id,
        "mission_revision": revision,
        "repository": "owner/repo",
        "desired_outcome": "value",
        "gaps": [
            {
                "gap_id": gap_id,
                "gap_state": "OPEN",
                "depends_on": [] if depends_on is None else depends_on,
                "repository": "owner/repo",
                "operation": "IMPLEMENTATION",
                "acceptance": ["observable outcome"],
                "integration_policy": "HOLD_AFTER_PASS",
            }
        ],
        "authority_boundaries": ["bounded"],
        "principal_manual_relay_count": 0,
    }


def test_task_identity_components_reserve_double_hyphen_separator():
    schema = validator.trusted_schema(validator.MISSION_SCHEMA_REL)
    validator.validate_instance(_minimal_mission(), schema, label="valid Mission")

    for mission in (
        _minimal_mission(mission_id="M--1"),
        _minimal_mission(revision="r--1"),
        _minimal_mission(gap_id="G--1"),
        _minimal_mission(depends_on=["G--0"]),
    ):
        with pytest.raises(validator.ValidationError, match="violates trusted schema"):
            validator.validate_instance(mission, schema, label="invalid Mission")
