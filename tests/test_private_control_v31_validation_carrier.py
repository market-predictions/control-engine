from pathlib import Path

import pytest

from scripts import validate_private_control_v31 as validator

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "private-control-v3-1-validation.yml"
VALIDATOR = ROOT / "scripts" / "validate_private_control_v31.py"


def test_private_v31_carrier_is_read_only_and_trusted_main_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:" in workflow
    assert "github.actor == 'market-predictions'" in workflow
    assert "github.event.comment.user.login" not in workflow
    assert "ref: main" in workflow
    assert "permission-contents: read" in workflow
    assert "permission-contents: write" not in workflow
    assert "permission-pull-requests: write" not in workflow
    assert "control-runtime-state" not in workflow
    assert "DISPATCH_QUEUE.json" not in workflow
    assert "python scripts/validate_private_control_v31.py private-candidate private-base" in workflow


def test_private_v31_validator_reads_committed_git_objects_only():
    text = VALIDATOR.read_text(encoding="utf-8")
    assert '"ls-tree", "-rz", "-r", "--full-tree", "HEAD"' in text
    assert '"cat-file", "blob", oid' in text
    assert "PRIVATE_CANDIDATE_EXECUTION=false" in text
    assert "PRIVATE_RUNTIME_MUTATION=false" in text
    for forbidden in ("importlib", "runpy", "exec(", "eval(", "os.system", "Popen", "shell=True"):
        assert forbidden not in text


def inert_entries():
    paths = {
        "README.md",
        "control/CHANGELOG.md",
        "control/CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
        "control/SYSTEM_INDEX.md",
        "control/missions/README.md",
        "control/missions/M1.mission.json",
        "control/repository-authority/o__r.json",
        "schemas/mission_contract_v31.schema.json",
        "schemas/repository_authority_v31.schema.json",
    }
    return {path: ("100644", "blob", "a" * 40) for path in paths}


def test_surface_accepts_only_inert_declarative_v31_data():
    missions, authorities = validator.validate_surface(inert_entries())
    assert missions == ["control/missions/M1.mission.json"]
    assert authorities == ["control/repository-authority/o__r.json"]


def test_surface_rejects_symlink_and_private_executable_surfaces():
    entries = inert_entries()
    entries["README.md"] = ("120000", "blob", "b" * 40)
    with pytest.raises(validator.ValidationError, match="symlink"):
        validator.validate_surface(entries)

    for path in (".github/workflows/validate-control-v3-1.yml", "tools/validate_control_v31.py"):
        entries = inert_entries()
        entries[path] = ("100644", "blob", "b" * 40)
        with pytest.raises(validator.ValidationError, match="non-V3.1 active surface"):
            validator.validate_surface(entries)


def test_authority_switches_require_actual_json_booleans():
    assert validator.explicit_bool(True)
    assert validator.explicit_bool(False)
    assert not validator.explicit_bool(1)
    assert not validator.explicit_bool(0)


def test_manual_relay_count_requires_exact_integer_zero():
    validator.require_zero_relay_count({"principal_manual_relay_count": 0})
    for value in (0.0, False, True, "0", None):
        with pytest.raises(validator.ValidationError, match="exact integer zero"):
            validator.require_zero_relay_count({"principal_manual_relay_count": value})


def test_repository_identity_is_github_safe_and_case_canonical():
    assert validator.canonical_repository("market-predictions/Control-Plane") == "market-predictions/control-plane"
    assert validator.canonical_repository("Owner/Repo") == validator.canonical_repository("owner/repo")
    for value in (
        "/",
        "owner/",
        "/repo",
        "owner/repo/extra",
        "owner name/repo",
        "owner/repo name",
        "-owner/repo",
        "owner-/repo",
        "owner--name/repo",
    ):
        assert validator.canonical_repository(value) is None


def test_trusted_public_schemas_are_valid_draft_2020_12_contracts():
    mission = validator.trusted_schema(validator.MISSION_SCHEMA_REL)
    authority = validator.trusted_schema(validator.REPOSITORY_SCHEMA_REL)
    assert mission["title"] == "MISSION_CONTRACT_V3_1"
    assert authority["title"] == "CONTROL_REPOSITORY_AUTHORITY_V3_1"
    assert mission["additionalProperties"] is False
    assert authority["additionalProperties"] is False


def test_schema_mirror_comparison_is_byte_exact_not_python_value_equal():
    trusted = b'{"minItems":1}\n'
    validator.require_exact_schema_bytes(trusted, trusted, label="Mission")
    with pytest.raises(validator.ValidationError, match="byte-for-byte"):
        validator.require_exact_schema_bytes(b'{"minItems":true}\n', trusted, label="Mission")


def test_trusted_schema_rejects_missing_required_mission_contract_fields():
    mission_schema = validator.trusted_schema(validator.MISSION_SCHEMA_REL)
    with pytest.raises(validator.ValidationError, match="violates trusted schema"):
        validator.validate_instance(
            {
                "protocol_id": "MISSION_CONTRACT_V3_1",
                "mission_id": "M1",
                "mission_revision": "2026-08-31-r1",
                "repository": "o/r",
                "gaps": [],
                "principal_manual_relay_count": 0,
            },
            mission_schema,
            label="Mission M1",
        )


def test_gap_dependency_graph_must_be_acyclic_without_recursion_limit():
    validator.assert_acyclic_dependencies(
        [{"gap_id": "G1", "depends_on": []}, {"gap_id": "G2", "depends_on": ["G1"]}],
        mission_name="M1",
    )
    with pytest.raises(validator.ValidationError, match="cyclic gap dependency"):
        validator.assert_acyclic_dependencies(
            [{"gap_id": "G1", "depends_on": ["G2"]}, {"gap_id": "G2", "depends_on": ["G1"]}],
            mission_name="M1",
        )

    chain = [
        {"gap_id": f"G{i}", "depends_on": [] if i == 0 else [f"G{i - 1}"]
        for i in range(1500)
    ]
    validator.assert_acyclic_dependencies(chain, mission_name="LONG")


def test_gap_auto_integration_requires_runtime_integration_and_repository_authority():
    auto = {
        "integration_policy": "AUTO_AFTER_PASS",
        "integration_enabled": True,
        "control_auto_profile": "CONTROL_AUTO_V1",
    }
    validator.assert_gap_integration_authorized(
        "AUTO_AFTER_PASS",
        auto,
        global_runtime_enabled=True,
        global_integration_enabled=True,
        label="M1:G1",
    )
    validator.assert_gap_integration_authorized(
        "HOLD_AFTER_PASS",
        auto,
        global_runtime_enabled=False,
        global_integration_enabled=False,
        label="M1:G1",
    )

    for runtime_enabled, integration_enabled in ((False, True), (True, False), (False, False)):
        with pytest.raises(validator.ValidationError, match="exceeds Control authority"):
            validator.assert_gap_integration_authorized(
                "AUTO_AFTER_PASS",
                auto,
                global_runtime_enabled=runtime_enabled,
                global_integration_enabled=integration_enabled,
                label="M1:G1",
            )

    for authority in (
        {**auto, "integration_policy": "HOLD_AFTER_PASS"},
        {**auto, "integration_enabled": False},
        {**auto, "control_auto_profile": "NONE"},
    ):
        with pytest.raises(validator.ValidationError, match="exceeds Control authority"):
            validator.assert_gap_integration_authorized(
                "AUTO_AFTER_PASS",
                authority,
                global_runtime_enabled=True,
                global_integration_enabled=True,
                label="M1:G1",
            )
        validator.assert_gap_integration_authorized(
            "HOLD_AFTER_PASS",
            authority,
            global_runtime_enabled=False,
            global_integration_enabled=False,
            label="M1:G1",
        )


def test_revision_discipline_is_bound_to_mission_identity_not_filename():
    base_revision = "2026-08-30-r1"
    next_revision = "2026-08-31-r2"
    base = {"M1": {"protocol_id": "MISSION_CONTRACT_V3_1", "mission_id": "M1", "mission_revision": base_revision, "desired_outcome": "old"}}
    changed_same_revision = {"M1": {"protocol_id": "MISSION_CONTRACT_V3_1", "mission_id": "M1", "mission_revision": base_revision, "desired_outcome": "new"}}
    with pytest.raises(validator.ValidationError, match="without new mission_revision"):
        validator.enforce_revision_discipline(changed_same_revision, base)

    changed_new_revision = {
        "M1": {
            "protocol_id": "MISSION_CONTRACT_V3_1",
            "mission_id": "M1",
            "mission_revision": next_revision,
            "supersedes_revision": base_revision,
            "desired_outcome": "new",
        }
    }
    validator.enforce_revision_discipline(changed_new_revision, base)


def test_revision_discipline_rejects_disappearing_existing_v31_mission():
    base = {"M1": {"protocol_id": "MISSION_CONTRACT_V3_1", "mission_id": "M1", "mission_revision": "2026-08-30-r1"}}
    with pytest.raises(validator.ValidationError, match="removed instead of being revised/retired"):
        validator.enforce_revision_discipline({}, base)
