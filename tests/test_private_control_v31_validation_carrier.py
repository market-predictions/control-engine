from pathlib import Path

import pytest

from scripts import validate_private_control_v31 as validator

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "private-control-v3-1-validation.yml"
VALIDATOR = ROOT / "scripts" / "validate_private_control_v31.py"


def test_private_v31_carrier_is_read_only_and_trusted_main_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:" in workflow
    assert "github.event.comment.user.login == 'market-predictions'" in workflow
    assert "ref: main" in workflow
    assert "permission-contents: read" in workflow
    assert "permission-contents: write" not in workflow
    assert "permission-pull-requests: write" not in workflow
    assert "control-runtime-state" not in workflow
    assert "DISPATCH_QUEUE.json" not in workflow
    assert "python scripts/validate_private_control_v31.py private-candidate private-base" in workflow


def test_private_v31_validator_reads_committed_git_objects_only():
    text = VALIDATOR.read_text(encoding="utf-8")
    assert '"ls-tree", "-rz", "--full-tree", "HEAD"' in text
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


def test_surface_rejects_symlink_even_at_allowed_path():
    entries = inert_entries()
    entries["README.md"] = ("120000", "blob", "b" * 40)
    with pytest.raises(validator.ValidationError, match="symlink"):
        validator.validate_surface(entries)


def test_surface_rejects_any_private_workflow_or_executable_tool():
    for path in (".github/workflows/validate-control-v3-1.yml", "tools/validate_control_v31.py"):
        entries = inert_entries()
        entries[path] = ("100644", "blob", "b" * 40)
        with pytest.raises(validator.ValidationError, match="non-V3.1 active surface"):
            validator.validate_surface(entries)


def test_surface_rejects_executable_mode_on_declarative_file():
    entries = inert_entries()
    entries["control/SYSTEM_INDEX.md"] = ("100755", "blob", "b" * 40)
    with pytest.raises(validator.ValidationError, match="executable"):
        validator.validate_surface(entries)


def test_authority_switches_require_actual_json_booleans():
    assert validator.explicit_bool(True)
    assert validator.explicit_bool(False)
    assert not validator.explicit_bool(1)
    assert not validator.explicit_bool(0)
    assert not validator.explicit_bool("true")
    assert not validator.explicit_bool(None)


def test_repository_identity_requires_nonempty_github_safe_components():
    for value in ("market-predictions/control-plane", "solidprivacy-nl/solidprivacy", "a/b.c_d-e"):
        assert validator.valid_repository(value)
    for value in ("/", "owner/", "/repo", "owner/repo/extra", "owner name/repo", "owner/repo name", "-owner/repo"):
        assert not validator.valid_repository(value)


def test_schema_contract_requires_parseable_expected_v31_shape():
    schema = {
        "$schema": validator.DRAFT_2020_12,
        "title": "MISSION_CONTRACT_V3_1",
        "type": "object",
        "additionalProperties": False,
        "required": ["protocol_id", "repository"],
        "properties": {
            "protocol_id": {"const": "MISSION_CONTRACT_V3_1"},
            "repository": {"type": "string", "pattern": "^[^/]+/[^/]+$"},
        },
    }
    validator.validate_schema_document(
        schema,
        title="MISSION_CONTRACT_V3_1",
        required={"protocol_id", "repository"},
        protocol_const="MISSION_CONTRACT_V3_1",
    )
    broken = dict(schema)
    broken["properties"] = {"protocol_id": {"const": "WRONG"}, "repository": {"type": "string", "pattern": "x"}}
    with pytest.raises(validator.ValidationError, match="protocol contract"):
        validator.validate_schema_document(
            broken,
            title="MISSION_CONTRACT_V3_1",
            required={"protocol_id", "repository"},
            protocol_const="MISSION_CONTRACT_V3_1",
        )


def test_gap_dependency_graph_must_be_acyclic():
    validator.assert_acyclic_dependencies(
        [
            {"gap_id": "G1", "depends_on": []},
            {"gap_id": "G2", "depends_on": ["G1"]},
        ],
        mission_name="M1",
    )
    with pytest.raises(validator.ValidationError, match="cyclic gap dependency"):
        validator.assert_acyclic_dependencies(
            [
                {"gap_id": "G1", "depends_on": ["G2"]},
                {"gap_id": "G2", "depends_on": ["G1"]},
            ],
            mission_name="M1",
        )
    with pytest.raises(validator.ValidationError, match="cyclic gap dependency"):
        validator.assert_acyclic_dependencies(
            [{"gap_id": "G1", "depends_on": ["G1"]}],
            mission_name="M1",
        )


def test_revision_discipline_is_bound_to_mission_identity_not_filename():
    base = {
        "M1": {
            "protocol_id": "MISSION_CONTRACT_V3_1",
            "mission_id": "M1",
            "mission_revision": "r1",
            "desired_outcome": "old",
        }
    }
    changed_same_revision = {
        "M1": {
            "protocol_id": "MISSION_CONTRACT_V3_1",
            "mission_id": "M1",
            "mission_revision": "r1",
            "desired_outcome": "new",
        }
    }
    with pytest.raises(validator.ValidationError, match="without new mission_revision"):
        validator.enforce_revision_discipline(changed_same_revision, base)

    changed_new_revision = {
        "M1": {
            "protocol_id": "MISSION_CONTRACT_V3_1",
            "mission_id": "M1",
            "mission_revision": "r2",
            "desired_outcome": "new",
        }
    }
    validator.enforce_revision_discipline(changed_new_revision, base)


def test_revision_discipline_rejects_disappearing_existing_v31_mission():
    base = {
        "M1": {
            "protocol_id": "MISSION_CONTRACT_V3_1",
            "mission_id": "M1",
            "mission_revision": "r1",
        }
    }
    with pytest.raises(validator.ValidationError, match="removed instead of being revised/retired"):
        validator.enforce_revision_discipline({}, base)
