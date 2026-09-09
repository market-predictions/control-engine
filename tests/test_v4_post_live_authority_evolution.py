from types import SimpleNamespace

import pytest

from scripts import validate_private_control_v4 as validator


def _bundle(*, missions, mission_shas, authority_shas):
    return SimpleNamespace(
        missions=tuple(missions),
        authorities=tuple(),
        mission_blob_shas=dict(mission_shas),
        authority_blob_shas=dict(authority_shas),
    )


def _mission(mission_id, revision, supersedes=None):
    value = {"mission_id": mission_id, "mission_revision": revision}
    if supersedes is not None:
        value["supersedes_revision"] = supersedes
    return value


def test_additive_mission_and_repository_authority_are_allowed_post_live():
    base = _bundle(
        missions=[_mission("A", "2026-09-01-r1")],
        mission_shas={"A": "1" * 40},
        authority_shas={"owner/a": "2" * 40},
    )
    candidate = _bundle(
        missions=[_mission("A", "2026-09-01-r1"), _mission("OVERIGE", "2026-09-09-r1")],
        mission_shas={"A": "1" * 40, "OVERIGE": "3" * 40},
        authority_shas={"owner/a": "2" * 40, "market-predictions/overige": "4" * 40},
    )

    validator.validate_authority_evolution(candidate, base)


def test_existing_mission_change_requires_revision_advance_and_exact_supersedes():
    base = _bundle(
        missions=[_mission("A", "2026-09-01-r1")],
        mission_shas={"A": "1" * 40},
        authority_shas={"owner/a": "2" * 40},
    )

    same_revision = _bundle(
        missions=[_mission("A", "2026-09-01-r1")],
        mission_shas={"A": "3" * 40},
        authority_shas={"owner/a": "2" * 40},
    )
    with pytest.raises(validator.ValidationError, match="advance mission_revision"):
        validator.validate_authority_evolution(same_revision, base)

    missing_supersedes = _bundle(
        missions=[_mission("A", "2026-09-09-r2")],
        mission_shas={"A": "4" * 40},
        authority_shas={"owner/a": "2" * 40},
    )
    with pytest.raises(validator.ValidationError, match="supersede exact current revision"):
        validator.validate_authority_evolution(missing_supersedes, base)

    valid = _bundle(
        missions=[_mission("A", "2026-09-09-r2", "2026-09-01-r1")],
        mission_shas={"A": "5" * 40},
        authority_shas={"owner/a": "2" * 40},
    )
    validator.validate_authority_evolution(valid, base)


def test_current_mission_and_repository_authority_cannot_be_deleted():
    base = _bundle(
        missions=[_mission("A", "2026-09-01-r1")],
        mission_shas={"A": "1" * 40},
        authority_shas={"owner/a": "2" * 40},
    )

    no_mission = _bundle(missions=[], mission_shas={}, authority_shas={"owner/a": "2" * 40})
    with pytest.raises(validator.ValidationError, match="Mission authority may not be deleted"):
        validator.validate_authority_evolution(no_mission, base)

    no_authority = _bundle(
        missions=[_mission("A", "2026-09-01-r1")],
        mission_shas={"A": "1" * 40},
        authority_shas={},
    )
    with pytest.raises(validator.ValidationError, match="repository authority may not be deleted"):
        validator.validate_authority_evolution(no_authority, base)
