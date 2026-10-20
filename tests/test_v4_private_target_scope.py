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
    assert scope.choose("review", state)[0] in targets
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
    workflow = (root / "control-v4-runtime-carrier.yml").read_text(encoding="utf-8")
    assert "CONTROL_REVIEW_TARGET_REPOSITORY: ${{ steps.target-scope.outputs.review_repository }}" in workflow


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
    assert "memory" in output.read_text().splitlines()
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


def test_review_token_scope_matches_exact_shared_batch_and_caps_one_private(monkeypatch, tmp_path):
    from scripts import control_v4_review_resume as resume

    targets = [MEMORY, "market-predictions/other-private"]
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": name} for name in targets]),
    )
    monkeypatch.setattr(resume, "eligible", lambda task: True)
    queue = {"tasks": [
        {"task_id": f"task-{i}", "repository": name} for i, name in enumerate(targets)
    ], "execution_lock": None}
    monkeypatch.setattr(scope.carrier, "_load_current", lambda: {
        "main_sha": "a" * 40, "queue": queue
    })
    monkeypatch.setattr(scope.carrier, "_public_get", lambda path, allow_404=False: None)
    from datetime import datetime, timezone
    batch = resume.current_review_batch(queue, now=datetime.now(timezone.utc))
    chosen = scope.choose("review", {"main_sha": "a" * 40, "queue": queue})
    assert len(chosen) == 1
    assert chosen[0] in {task["repository"] for task in batch}
    out = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "review")
    scope.main()
    text = out.read_text()
    assert "has_targets=true" in text
    assert sum(name in text for name in targets) == 1
    assert "review_repository=" + chosen[0] in text


def test_no_work_fallback_rejects_private_proposals_even_if_runtime_target_has_token(monkeypatch):
    from scripts import control_v4_auto_replenish as replenish

    monkeypatch.setenv("CONTROL_TARGET_REPOSITORIES", MEMORY)
    monkeypatch.setenv("CONTROL_TARGET_READ_TOKEN", "test-ephemeral-token")
    monkeypatch.setattr(replenish.owner_admin, "_public_get", lambda path: {
        "full_name": MEMORY, "private": True
    })
    with pytest.raises(replenish.AutoReplenishError):
        replenish._assert_proposal_targets_public({
            "replenishment_proposals": [{"repository": MEMORY}]
        })


def test_review_repository_rotation_cannot_starve_one_sparse_project(monkeypatch):
    """A/B cannot be phase-locked to the older eight-task batch offset."""
    from datetime import datetime, timedelta, timezone
    from scripts import control_v4_review_resume as resume
    a = "market-predictions/private-a"
    b = "market-predictions/private-b"
    repositories = [a] * 7 + [b] + [a] * 8
    queue = {
        "tasks": [{"task_id": f"task-{index}", "repository": repo}
                  for index, repo in enumerate(repositories)],
        "execution_lock": None,
    }
    monkeypatch.setattr(resume, "eligible", lambda task: True)
    start = datetime(2026, 10, 21, 0, tzinfo=timezone.utc)
    selected = [resume.selected_review_repository(
        queue, now=start + timedelta(hours=hours)
    ) for hours in range(2)]
    assert set(selected) == {a, b}
    for hours, repository in enumerate(selected):
        batch = resume.current_review_batch(
            queue, now=start + timedelta(hours=hours), repository=repository,
        )
        assert batch
        assert all(task["repository"] == repository for task in batch)


def test_public_other_owner_remains_supported_without_private_app_token(monkeypatch, tmp_path):
    external = "other-owner/public-repository"
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": external}]),
    )
    monkeypatch.setattr(scope.review, "eligible", lambda task: True)
    monkeypatch.setattr(
        scope.carrier, "_load_current",
        lambda: {
            "main_sha": "a" * 40,
            "queue": {
                "tasks": [{"task_id": "one", "repository": external}],
                "execution_lock": None,
            },
        },
    )
    monkeypatch.setattr(scope.carrier, "_public_get",
                        lambda path, allow_404=False: {
                            "full_name": external, "private": False
                        })
    out = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "review")
    scope.main()
    assert "has_targets=false" in out.read_text()
    assert "review_repository=" + external in out.read_text()
    assert "repository_names<<CONTROL_SCOPE_END\\n\\nCONTROL_SCOPE_END" not in out.read_text()


def test_private_external_owner_rejected_without_installed_owner_app(monkeypatch, tmp_path):
    external = "other-owner/private-repository"
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[{"repository": external}]),
    )
    monkeypatch.setattr(scope.review, "eligible", lambda task: True)
    monkeypatch.setattr(scope.carrier, "_load_current", lambda: {
        "main_sha": "a" * 40,
        "queue": {
            "tasks": [{"task_id": "one", "repository": external}],
            "execution_lock": None,
        },
    })
    monkeypatch.setattr(scope.carrier, "_public_get",
                        lambda path, allow_404=False: None)
    out = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "review")
    with pytest.raises(ValueError, match="installed owner-scoped App"):
        scope.main()
    assert not out.exists()
