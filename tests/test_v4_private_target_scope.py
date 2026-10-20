"""Regression boundary for selected private GitHub target reads (no live credentials)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import control_v4_target_access as access
from scripts import control_v4_target_scope as scope


MEMORY = "market-predictions/memory"
PUBLIC = "market-predictions/control-engine"


def test_public_repository_still_reads_without_target_secret(monkeypatch):
    monkeypatch.delenv("CONTROL_TARGET_READ_TOKEN", raising=False)
    monkeypatch.delenv("CONTROL_TARGET_REPOSITORIES", raising=False)
    assert access.target_headers("repos/market-predictions/control-engine") == {}
    access.assert_supported_target(PUBLIC, lambda path: {"full_name": PUBLIC, "private": False})


def test_private_target_requires_exact_scope_and_short_lived_token(monkeypatch):
    monkeypatch.setenv("CONTROL_TARGET_REPOSITORIES", MEMORY)
    monkeypatch.setenv("CONTROL_TARGET_READ_TOKEN", "test-ephemeral-token")
    observed = []
    access.assert_supported_target(
        MEMORY,
        lambda path: observed.append(path) or {"full_name": MEMORY, "private": True},
    )
    assert observed == ["repos/" + MEMORY]
    assert access.target_headers("repos/" + MEMORY + "/pulls/2") == {
        "Authorization": "Bearer test-ephemeral-token"
    }
    for unrelated in (
        "repos/market-predictions/control-plane",
        "repos/market-predictions/memory-copy",
        "repos/other/memory",
        "repos/market-predictions/memory-evasion",
    ):
        assert access.target_headers(unrelated) == {}


def test_private_repo_rejected_without_both_scope_and_token(monkeypatch):
    monkeypatch.delenv("CONTROL_TARGET_REPOSITORIES", raising=False)
    monkeypatch.setenv("CONTROL_TARGET_READ_TOKEN", "test-secret")
    with pytest.raises(access.TargetAccessError):
        access.assert_supported_target(MEMORY, lambda _: {"full_name": MEMORY, "private": True})

    monkeypatch.setenv("CONTROL_TARGET_REPOSITORIES", MEMORY)
    monkeypatch.delenv("CONTROL_TARGET_READ_TOKEN", raising=False)
    with pytest.raises(access.TargetAccessError):
        access.assert_supported_target(MEMORY, lambda _: {"full_name": MEMORY, "private": True})
    with pytest.raises(access.TargetAccessError):
        access.target_headers("repos/" + MEMORY + "/pulls/2")


def test_repository_identity_and_privacy_are_verified_exactly(monkeypatch):
    monkeypatch.setenv("CONTROL_TARGET_REPOSITORIES", MEMORY)
    monkeypatch.setenv("CONTROL_TARGET_READ_TOKEN", "test-secret")
    for response in (None, {"full_name": "other/repo", "private": True},
                     {"full_name": MEMORY}, {"full_name": MEMORY, "private": "yes"}):
        with pytest.raises(access.TargetAccessError):
            access.assert_supported_target(MEMORY, lambda _: response)


def test_duplicate_target_scope_refused(monkeypatch):
    monkeypatch.setenv("CONTROL_TARGET_REPOSITORIES", MEMORY + "\n" + MEMORY)
    with pytest.raises(access.TargetAccessError):
        access.selected_repositories()


def test_scope_must_derive_from_live_mission_not_public_command(monkeypatch):
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": MEMORY}]),
    )
    state = {"main_sha": "a" * 40, "queue": {"tasks": [], "execution_lock": None}}
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", MEMORY)
    assert scope.choose("native", state) == [MEMORY]
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", "market-predictions/unregistered")
    with pytest.raises(ValueError, match="outside current governed Mission"):
        scope.choose("native", state)


def test_review_scope_never_grants_access_to_all_pending_private_targets(monkeypatch):
    targets = [MEMORY, "market-predictions/private-other"]
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": t} for t in targets]),
    )
    monkeypatch.setattr(scope.review, "eligible", lambda t: True)
    state = {
        "main_sha": "a" * 40,
        "queue": {"tasks": [{"repository": t} for t in targets], "execution_lock": None},
    }
    assert len(scope.choose("review", state)) == 1
    assert scope.choose("replenish", state) == []


def test_existing_workflows_gate_short_lived_scoped_read_tokens():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for workflow in ("control-v4-runtime-carrier.yml", "control-v4-authority-adoption.yml"):
        text = (root / workflow).read_text(encoding="utf-8")
        assert "permission-contents: write" in text  # canonical Control Plane only
        assert "permission-contents: read" in text
        assert "permission-pull-requests: read" in text
        assert "permission-issues: read" in text
        assert "permission-checks: read" in text
        assert "steps.target-scope.outputs.has_targets == 'true'" in text
        assert "repositories: ${{ steps.target-scope.outputs.repository_names }}" in text
        assert "CONTROL_TARGET_READ_TOKEN: ${{ steps.target-token.outputs.token }}" in text
        assert "CONTROL_TARGET_REPOSITORIES: ${{ steps.target-scope.outputs.full_names }}" in text


def test_scope_output_mints_token_only_for_private_targets(monkeypatch, tmp_path):
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": MEMORY}, {"repository": PUBLIC}]),
    )
    monkeypatch.setattr(
        scope.carrier, "_load_current",
        lambda: {"main_sha": "a" * 40, "queue": {"tasks": [], "execution_lock": None}},
    )
    monkeypatch.setattr(
        scope.carrier, "_public_get",
        lambda path, allow_404=False: {"full_name": PUBLIC, "private": False}
        if path == "repos/" + PUBLIC else None,
    )
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "native")
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", PUBLIC)
    scope.main()
    assert "has_targets=false" in output.read_text()
    output.write_text("")
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", MEMORY)
    scope.main()
    assert "has_targets=true" in output.read_text()
    assert "repository_names<<CONTROL_SCOPE_END\\nmemory\\nCONTROL_SCOPE_END" in output.read_text()
    assert "market-predictions/control-plane" not in output.read_text()


def test_invalid_public_identity_fails_before_token_creation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": MEMORY}]),
    )
    monkeypatch.setattr(
        scope.carrier, "_load_current",
        lambda: {"main_sha": "a" * 40, "queue": {"tasks": [], "execution_lock": None}},
    )
    monkeypatch.setattr(scope.carrier, "_public_get", lambda path, allow_404=False:
                        {"full_name": "other/untrusted", "private": False})
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "native")
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", MEMORY)
    with pytest.raises(ValueError, match="identity mismatch"):
        scope.main()
    assert not output.exists()
