import pytest

from scripts import validate_private_control_v31 as validator


def _minimal_mission(mission_id="M1", revision="2026-08-31-r1", gap_id="G1", depends_on=None):
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


def test_task_identity_components_are_unambiguous_across_double_hyphen_joining():
    schema = validator.trusted_schema(validator.MISSION_SCHEMA_REL)
    validator.validate_instance(_minimal_mission(), schema, label="valid Mission")
    validator.validate_instance(
        _minimal_mission(mission_id="MISSION_A", revision="2026-08-31-r1", gap_id="GAP-10"),
        schema,
        label="valid Mission",
    )

    for mission in (
        _minimal_mission(mission_id="M--1"),
        _minimal_mission(revision="2026-08-31-r--1"),
        _minimal_mission(gap_id="G--1"),
        _minimal_mission(depends_on=["G--0"]),
        _minimal_mission(mission_id="M-"),
        _minimal_mission(revision="-2026-08-31-r1"),
        _minimal_mission(gap_id="G-"),
        _minimal_mission(depends_on=["-G0"]),
    ):
        with pytest.raises(validator.ValidationError, match="violates trusted schema"):
            validator.validate_instance(mission, schema, label="invalid Mission")


def test_task_identity_components_reject_line_breaks_including_terminal_newlines():
    schema = validator.trusted_schema(validator.MISSION_SCHEMA_REL)
    for mission in (
        _minimal_mission(mission_id="M\n"),
        _minimal_mission(revision="2026-08-31-r1\n"),
        _minimal_mission(gap_id="G1\n"),
        _minimal_mission(depends_on=["G0\n"]),
        _minimal_mission(mission_id="M\r"),
    ):
        with pytest.raises(validator.ValidationError, match="violates trusted schema"):
            validator.validate_instance(mission, schema, label="invalid Mission")


def test_previously_colliding_component_tuples_are_both_rejected():
    schema = validator.trusted_schema(validator.MISSION_SCHEMA_REL)
    for mission in (
        _minimal_mission(mission_id="M-", revision="2026-08-31-r1"),
        _minimal_mission(mission_id="M", revision="-2026-08-31-r1"),
    ):
        with pytest.raises(validator.ValidationError, match="violates trusted schema"):
            validator.validate_instance(mission, schema, label="ambiguous Mission")
