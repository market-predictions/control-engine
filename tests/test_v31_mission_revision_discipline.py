import pytest

from scripts import validate_private_control_v31 as validator


def mission(revision: str, *, supersedes=None, marker="base"):
    doc = {
        "protocol_id": "MISSION_CONTRACT_V3_1",
        "mission_id": "M1",
        "mission_revision": revision,
        "repository": "o/r",
        "desired_outcome": marker,
        "gaps": [],
        "authority_boundaries": ["bounded"],
        "principal_manual_relay_count": 0,
    }
    if supersedes is not None:
        doc["supersedes_revision"] = supersedes
    return doc


def test_revision_format_is_machine_orderable_and_date_valid():
    assert validator.revision_key("2026-08-31-r3")[0] == 3
    for invalid in ("r3", "2026-08-31", "2026-08-31-r0", "2026-99-99-r3", "2026-08-31-r3\n"):
        with pytest.raises(validator.ValidationError, match="Mission revision invalid"):
            validator.revision_key(invalid)


def test_changed_mission_requires_forward_sequence_and_exact_supersedes_link():
    base = {"M1": mission("2026-08-30-r2")}
    good = {"M1": mission("2026-08-31-r3", supersedes="2026-08-30-r2", marker="changed")}
    validator.enforce_revision_discipline(good, base)

    for candidate in (
        {"M1": mission("2026-08-29-r1", supersedes="2026-08-30-r2", marker="rollback")},
        {"M1": mission("2026-08-31-r2", supersedes="2026-08-30-r2", marker="reuse")},
        {"M1": mission("2026-08-29-r3", supersedes="2026-08-30-r2", marker="date rollback")},
        {"M1": mission("2026-08-31-r3", supersedes="2026-08-29-r1", marker="wrong parent")},
        {"M1": mission("2026-08-31-r3", marker="missing parent")},
    ):
        with pytest.raises(validator.ValidationError):
            validator.enforce_revision_discipline(candidate, base)


def test_unchanged_mission_keeps_same_revision_without_churn():
    base_doc = mission("2026-08-30-r2")
    validator.enforce_revision_discipline({"M1": dict(base_doc)}, {"M1": base_doc})
