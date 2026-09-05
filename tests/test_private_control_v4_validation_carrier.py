from pathlib import Path
import subprocess
import sys

import pytest

from scripts import validate_private_control_v4 as validator

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "private-control-v3-1-validation.yml"
VALIDATOR = ROOT / "scripts" / "validate_private_control_v4.py"


def test_existing_private_carrier_adds_exact_pair_v4_profile_without_second_workflow():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Validate Private Control Authority" in workflow
    assert 'v4_prefix = "CONTROL_PRIVATE_V4_VALIDATE "' in workflow
    assert 'event.get("issue", {}).get("number") == 106' in workflow
    assert 'len(v4_parts) == 2' in workflow
    assert 'sha, base_ref = v4_parts' in workflow
    assert 'sha != base_ref' in workflow
    assert 'profile = "V4"' in workflow
    assert 'ref: ${{ steps.gate.outputs.base_ref }}' in workflow
    assert "python -m scripts.validate_private_control_v4 private-candidate private-base" in workflow
    assert "python scripts/validate_private_control_v4.py private-candidate private-base" not in workflow
    assert "permission-contents: read" in workflow
    assert "permission-contents: write" not in workflow
    assert "permission-pull-requests: write" not in workflow
    assert "control-runtime-state" not in workflow
    assert "DISPATCH_QUEUE.json" not in workflow
    assert "CONTROL_PRIVATE_RUNTIME_MUTATION=false" in workflow
    assert "CONTROL_PRIVATE_VALIDATED_BASE=${{ steps.gate.outputs.base_ref }}" in workflow
    assert workflow.count("fetch-depth: 0") == 1


def test_v4_production_module_invocation_can_import_trusted_public_packages():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.validate_private_control_v4"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 2
    assert "usage: validate_private_control_v4.py" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_v31_profile_is_preserved_for_truthful_pre_v4_80_rollback():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'prefix = "CONTROL_PRIVATE_V31_VALIDATE "' in workflow
    assert 'event.get("issue", {}).get("number") == 87' in workflow
    assert 'profile = "V31" if authorized else ""' in workflow
    assert 'base_ref = "main" if authorized else ""' in workflow
    assert "python scripts/validate_private_control_v31.py private-candidate private-base" in workflow


def test_v4_validator_reads_committed_git_objects_only_and_reuses_public_contracts():
    text = VALIDATOR.read_text(encoding="utf-8")
    assert "load_v4_authority_from_git" in text
    assert '"ls-tree", "-rz", "-r", "--full-tree", "HEAD"' in text
    assert '"cat-file", "blob", oid' in text
    assert '"--no-replace-objects"' in text
    assert "CONTROL_PRIVATE_CANDIDATE_EXECUTION=false" in text
    assert "CONTROL_PRIVATE_RUNTIME_MUTATION=false" in text
    for forbidden in ("importlib", "runpy", "exec(", "eval(", "os.system", "shell=True"):
        assert forbidden not in text


def test_v4_runtime_switches_and_relay_are_type_strict():
    assert validator.explicit_bool(True)
    assert validator.explicit_bool(False)
    assert not validator.explicit_bool(1)
    assert not validator.explicit_bool(0)
    validator.require_zero_relay_count({"principal_manual_relay_count": 0})
    for value in (0.0, False, True, "0", None):
        with pytest.raises(validator.ValidationError, match="exact integer zero"):
            validator.require_zero_relay_count({"principal_manual_relay_count": value})


def test_v4_runner_object_and_prompt_are_public_trust_anchors():
    assert validator.REVIEWED_AUTOMATION_OBJECT_ID == "6a9a7e0b18b08191876c134d83cfbba2"
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "cfef93333aaf0a88ef72db3e3a4bd37c384217fc"
    validator.require_reviewed_automation_object_id(validator.REVIEWED_AUTOMATION_OBJECT_ID)
    for value in ("0" * 32, "6a9a7e0b18b08191876c134d83cfbba3", None):
        with pytest.raises(validator.ValidationError, match="exact reviewed V4-30 object"):
            validator.require_reviewed_automation_object_id(value)


def test_v4_frozen_authority_loader_uses_exact_v4_40_commit(monkeypatch, tmp_path):
    assert validator.V4_40_FROZEN_AUTHORITY_COMMIT == "3c314362341570349c15de00156dd6f5ab037fbe"
    calls = []
    sentinel = object()

    def fake_loader(root, *, commit_sha=None):
        calls.append((Path(root), commit_sha))
        return sentinel

    monkeypatch.setattr(validator, "load_v4_authority_from_git", fake_loader)
    assert validator.load_frozen_v4_40_authority(tmp_path) is sentinel
    assert calls == [(tmp_path, validator.V4_40_FROZEN_AUTHORITY_COMMIT)]


def test_v4_changed_surface_allows_bounded_convergence_but_rejects_unbounded_paths():
    base = {
        validator.RUNTIME_PATH: ("100644", "blob", "a" * 40),
        validator.INDEX_PATH: ("100644", "blob", "b" * 40),
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json": ("100644", "blob", "c" * 40),
    }
    candidate = dict(base)
    candidate[validator.RUNTIME_PATH] = ("100644", "blob", "d" * 40)
    del candidate["control/CONTROL_RUNTIME_AUTHORITY_V3_1.json"]
    assert validator.validate_changed_surface(candidate, base) == {
        validator.RUNTIME_PATH,
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
    }
    candidate["tools/private_runtime.py"] = ("100644", "blob", "e" * 40)
    with pytest.raises(validator.ValidationError, match="non-declarative authority surface"):
        validator.validate_changed_surface(candidate, base)


def test_current_doctrine_paths_must_all_be_inert_regular_blobs(monkeypatch, tmp_path):
    seen = []

    def fake_regular_blob(entries, path):
        seen.append(path)
        if path == "control/CONTROL_V4_ROADMAP.md":
            raise validator.ValidationError("private V4 path is not one inert regular Git blob")
        return "a" * 40

    monkeypatch.setattr(validator, "_regular_blob", fake_regular_blob)
    monkeypatch.setattr(
        validator,
        "_text",
        lambda root, entries, path: (
            "# Mission Contract Registry — V4\n"
            "CONTROL_AUTONOMY_ARCHITECTURE_V4.md\n"
            "MISSION_CONTRACT_V4\nreview_policy\n"
        ),
    )
    with pytest.raises(validator.ValidationError, match="inert regular Git blob"):
        validator.validate_current_surface(tmp_path, {})
    assert "control/CONTROL_AUTONOMY_ARCHITECTURE_V4.md" in seen
    assert "control/CONTROL_V4_ROADMAP.md" in seen


def test_v4_system_index_is_live_first_and_forbids_volatile_runtime_snapshots_anywhere():
    runtime = {"control_runtime_enabled": True, "integration_enabled": False}
    valid = "\n".join(
        (
            "# Control — Canonical System Index V4",
            "architecture=control/CONTROL_AUTONOMY_ARCHITECTURE_V4.md",
            "runtime=control-runtime-state:control/DISPATCH_QUEUE.json",
            "global_safety=control/CONTROL_RUNTIME_AUTHORITY_V4.json",
            "runner_config=control/CONTROL_RUNNER_V4.json",
            "runner_prompt=control/CONTROL_RUNNER_V4_PROMPT.md",
            "Current status is a fresh live projection, not a documentation lookup.",
            "Missing required evidence returns STATUS_OBSERVABILITY_INCOMPLETE.",
        )
    ).encode("utf-8")
    validator.validate_system_index(valid, runtime)

    with pytest.raises(validator.ValidationError, match="stale V3.1"):
        validator.validate_system_index(valid + b"\nv4_status=CANDIDATE_INERT_UNADOPTED\n", runtime)

    for injected in (
        b"\ncontrol_runtime_enabled=true\n",
        b"\n- control_runtime_enabled=false\n",
        b"\n> `integration_enabled=true`\n",
        b"\n  runner_config_blob_sha=deadbeef\n",
        b"\nstatus: `prompt_blob_sha=deadbeef`\n",
        b"\n* principal_manual_relay_count=0\n",
    ):
        with pytest.raises(validator.ValidationError, match="duplicates volatile"):
            validator.validate_system_index(valid + injected, runtime)


def test_v4_current_surface_requires_v3_authority_absent_and_v4_mission_registry():
    assert validator.LEGACY_CURRENT_PATHS == {
        "control/CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
    }
    assert validator.MISSION_README_PATH in validator.BOUNDED_DOCTRINE_PATHS


def test_v4_runner_current_contract_is_exact_prompt_blob_not_marker_presence():
    text = VALIDATOR.read_text(encoding="utf-8")
    assert 'REVIEWED_RUNNER_PROMPT_BLOB_SHA = "cfef93333aaf0a88ef72db3e3a4bd37c384217fc"' in text
    assert "prompt_oid != REVIEWED_RUNNER_PROMPT_BLOB_SHA" in text
    assert '"positive_git_cas_proof": "PROVEN_V4_30"' in text
    assert "for marker in" not in text
