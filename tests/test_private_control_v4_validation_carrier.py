from pathlib import Path
import json
import subprocess
import sys

import pytest

from scripts import validate_private_control_v4 as validator

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "private-control-v3-1-validation.yml"
VALIDATOR = ROOT / "scripts" / "validate_private_control_v4.py"

# Deliberately independent from validator.BOUNDED_DOCTRINE_PATHS so deleting a
# required production path cannot silently shrink the regression matrix too.
REQUIRED_CURRENT_DOCTRINE_PATHS = (
    "control/CONTROL_AUTONOMY_ARCHITECTURE_V4.md",
    "control/CONTROL_V4_REALIZATION_RUNBOOK.md",
    "control/CONTROL_V4_ROADMAP.md",
    "control/CONTROL_V4_CONVERGENCE_AND_DEBT_RETIREMENT_PLAN.md",
    "control/CONTROL_V4_SURFACE_INVENTORY.md",
    "control/missions/README.md",
    "control/CHANGELOG.md",
    "control/CONTROL_V4_COHERENCE_REPAIR_2026_09_05.md",
)

VALID_MISSION_README = (
    "# Mission Contract Registry — V4\n"
    "CONTROL_AUTONOMY_ARCHITECTURE_V4.md\n"
    "MISSION_CONTRACT_V4\n"
    "review_policy\n"
)


def _current_doctrine_entries() -> dict[str, tuple[str, str, str]]:
    return {
        path: ("100644", "blob", f"{index + 1:040x}")
        for index, path in enumerate(REQUIRED_CURRENT_DOCTRINE_PATHS)
    }


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


def test_v4_runner_object_prompt_and_system_index_are_public_trust_anchors():
    assert validator.REVIEWED_AUTOMATION_OBJECT_ID == "6a9a7e0b18b08191876c134d83cfbba2"
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "cfef93333aaf0a88ef72db3e3a4bd37c384217fc"
    assert validator.REVIEWED_SYSTEM_INDEX_BLOB_SHA == "e8aae3b78782933b51a97f4132580de71893de7f"
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


@pytest.mark.parametrize("missing_path", REQUIRED_CURRENT_DOCTRINE_PATHS)
def test_every_required_current_doctrine_path_is_independently_required(
    monkeypatch, tmp_path, missing_path
):
    entries = _current_doctrine_entries()
    del entries[missing_path]
    monkeypatch.setattr(validator, "_text", lambda root, tree, path: VALID_MISSION_README)

    with pytest.raises(validator.ValidationError, match=f"required private V4 file missing: {missing_path}"):
        validator.validate_current_surface(tmp_path, entries)


@pytest.mark.parametrize("non_regular_path", REQUIRED_CURRENT_DOCTRINE_PATHS)
def test_every_required_current_doctrine_path_is_independently_inert_regular_blob(
    monkeypatch, tmp_path, non_regular_path
):
    entries = _current_doctrine_entries()
    entries[non_regular_path] = ("120000", "blob", "f" * 40)
    monkeypatch.setattr(validator, "_text", lambda root, tree, path: VALID_MISSION_README)

    with pytest.raises(
        validator.ValidationError,
        match=f"private V4 path is not one inert regular Git blob: {non_regular_path}",
    ):
        validator.validate_current_surface(tmp_path, entries)


@pytest.mark.parametrize(
    "legacy_path",
    (
        "control/CONTROL_AUTONOMY_ARCHITECTURE_V3_1.md",
        "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json",
        "schemas/mission_contract_v31.schema.json",
        "schemas/repository_authority_v31.schema.json",
    ),
)
def test_each_legacy_current_authority_path_is_behaviorally_rejected(
    monkeypatch, tmp_path, legacy_path
):
    entries = _current_doctrine_entries()
    entries[legacy_path] = ("100644", "blob", "e" * 40)
    monkeypatch.setattr(validator, "_text", lambda root, tree, path: VALID_MISSION_README)

    with pytest.raises(validator.ValidationError, match="competing V3.1 current authority"):
        validator.validate_current_surface(tmp_path, entries)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def _init_git_fixture(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Control Tests")
    _git(root, "config", "user.email", "control-tests@example.invalid")
    (root / "control").mkdir(parents=True, exist_ok=True)


def _git_blob_oid(root: Path, path: str) -> str:
    oid = _git(root, "hash-object", path)
    assert len(oid) == 40
    return oid


def _commit_fixture(root: Path, message: str = "fixture") -> dict[str, tuple[str, str, str]]:
    _git(root, "add", ".")
    _git(root, "commit", "-qm", message)
    return validator.committed_tree(root)


def _write_real_runner_fixture(root: Path) -> tuple[dict[str, tuple[str, str, str]], str]:
    _init_git_fixture(root)
    prompt_path = root / validator.RUNNER_PROMPT_PATH
    prompt_path.write_text(
        "status=ACTIVE_BOUND\ncanonical reviewed prompt\n",
        encoding="utf-8",
    )
    prompt_oid = _git_blob_oid(root, validator.RUNNER_PROMPT_PATH)

    config = {
        "protocol_id": "CONTROL_RUNNER_V4",
        "runner_id": "CONTROL_V4_RUNNER",
        "execution_surface": "CHATGPT_SCHEDULED",
        "prompt_path": validator.RUNNER_PROMPT_PATH,
        "prompt_blob_sha": prompt_oid,
        "schedule": {
            "timing_mode": "exact_schedule",
            "timezone": "Europe/Amsterdam",
            "rrule": "FREQ=HOURLY;BYMINUTE=30;BYSECOND=0",
        },
        "automation_object_id": validator.REVIEWED_AUTOMATION_OBJECT_ID,
        "automation_object_binding_status": "BOUND",
        "scheduled_credential_binding_status": "PLATFORM_MANAGED_NO_STABLE_CREDENTIAL_ID_EXPOSED",
        "effective_capability_binding_status": "BOUND_TO_EXACT_SCHEDULED_OBJECT_TOOL_SURFACE",
        "scheduled_capability_observation": {
            "scheduler_automation_admin": "PLATFORM_EXPOSED_ACCEPTED",
            "protection_rules_admin": "UNAVAILABLE_OBSERVED_V4_30",
            "positive_git_cas_proof": "PROVEN_V4_30",
        },
        "principal_manual_relay_count": 0,
    }
    config_path = root / validator.RUNNER_CONFIG_PATH
    config_path.write_text(json.dumps(config, separators=(",", ":")) + "\n", encoding="utf-8")
    config_oid = _git_blob_oid(root, validator.RUNNER_CONFIG_PATH)

    runtime = {
        "protocol_id": "CONTROL_RUNTIME_AUTHORITY_V4",
        "control_runtime_enabled": True,
        "integration_enabled": False,
        "runner_config_path": validator.RUNNER_CONFIG_PATH,
        "runner_config_blob_sha": config_oid,
        "principal_manual_relay_count": 0,
    }
    runtime_path = root / validator.RUNTIME_PATH
    runtime_path.write_text(json.dumps(runtime, separators=(",", ":")) + "\n", encoding="utf-8")

    return _commit_fixture(root), prompt_oid


def test_exact_reviewed_runner_prompt_blob_is_behaviorally_accepted_from_real_git(
    monkeypatch, tmp_path
):
    entries, prompt_oid = _write_real_runner_fixture(tmp_path)
    prompt_raw, committed_prompt_oid = validator._blob(
        tmp_path, entries, validator.RUNNER_PROMPT_PATH
    )
    assert committed_prompt_oid == prompt_oid
    assert prompt_raw == b"status=ACTIVE_BOUND\ncanonical reviewed prompt\n"

    monkeypatch.setattr(validator, "REVIEWED_RUNNER_PROMPT_BLOB_SHA", prompt_oid)
    runtime = validator.validate_runtime_and_runner(tmp_path, entries)
    assert runtime["control_runtime_enabled"] is True
    assert runtime["integration_enabled"] is False


def test_non_anchor_runner_prompt_blob_is_behaviorally_rejected_from_real_git(
    monkeypatch, tmp_path
):
    entries, prompt_oid = _write_real_runner_fixture(tmp_path)
    assert validator._regular_blob(entries, validator.RUNNER_PROMPT_PATH) == prompt_oid
    monkeypatch.setattr(validator, "REVIEWED_RUNNER_PROMPT_BLOB_SHA", "d" * 40)
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator.validate_runtime_and_runner(tmp_path, entries)


def _valid_system_index() -> bytes:
    return "\n".join(
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


def _write_real_system_index_fixture(
    root: Path,
) -> tuple[dict[str, tuple[str, str, str]], bytes, str]:
    _init_git_fixture(root)
    index_path = root / validator.INDEX_PATH
    index_path.write_bytes(_valid_system_index())
    entries = _commit_fixture(root)
    raw, oid = validator._blob(root, entries, validator.INDEX_PATH)
    assert raw == _valid_system_index()
    return entries, raw, oid


def test_exact_reviewed_system_index_blob_is_behaviorally_accepted_from_real_git(
    monkeypatch, tmp_path
):
    _entries, raw, oid = _write_real_system_index_fixture(tmp_path)
    monkeypatch.setattr(validator, "REVIEWED_SYSTEM_INDEX_BLOB_SHA", oid)
    runtime = {"control_runtime_enabled": True, "integration_enabled": False}
    validator.validate_system_index(raw, runtime, index_oid=oid)


def test_changed_committed_system_index_blob_is_behaviorally_rejected_from_real_git(
    monkeypatch, tmp_path
):
    _entries, approved_raw, approved_oid = _write_real_system_index_fixture(tmp_path)
    monkeypatch.setattr(validator, "REVIEWED_SYSTEM_INDEX_BLOB_SHA", approved_oid)

    index_path = tmp_path / validator.INDEX_PATH
    index_path.write_bytes(approved_raw + b"\nchanged after review\n")
    changed_entries = _commit_fixture(tmp_path, "changed index")
    changed_raw, changed_oid = validator._blob(
        tmp_path, changed_entries, validator.INDEX_PATH
    )
    assert changed_oid != approved_oid

    runtime = {"control_runtime_enabled": True, "integration_enabled": False}
    with pytest.raises(
        validator.ValidationError,
        match="SYSTEM_INDEX blob differs from exact trusted reviewed V4 live-first contract",
    ):
        validator.validate_system_index(changed_raw, runtime, index_oid=changed_oid)
