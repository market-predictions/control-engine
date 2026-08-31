import pytest

from scripts import validate_private_control_v31 as validator


def _mission(revision: str, relay):
    return {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "M1",
        "mission_revision": revision,
        "desired_outcome": "same",
        "principal_manual_relay_count": relay,
    }


def test_revision_discipline_does_not_coerce_json_numeric_types():
    base_revision = "2026-08-30-r1"
    base = {"M1": _mission(base_revision, 0.0)}
    candidate = {"M1": _mission(base_revision, 0)}

    assert validator.canonical_json_bytes(base["M1"]) != validator.canonical_json_bytes(candidate["M1"])
    with pytest.raises(validator.ValidationError, match="without new mission_revision"):
        validator.enforce_revision_discipline(candidate, base)


def test_revision_discipline_still_ignores_object_key_order_only():
    left = {"mission_id": "M1", "mission_revision": "2026-08-30-r1", "value": 0}
    right = {"value": 0, "mission_revision": "2026-08-30-r1", "mission_id": "M1"}
    assert validator.canonical_json_bytes(left) == validator.canonical_json_bytes(right)
