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


def test_default_native_start_preserves_public_path_behind_private_work(monkeypatch):
    from test_v4_terminal_target_recovery import queue as v4_queue, task as v4_task

    private = "market-predictions/memory"
    public = "market-predictions/control-engine"
    first = v4_task("MISSION--M--2026-09-22-r1--G1", private, 10)
    second = v4_task("MISSION--M--2026-09-22-r1--G2", public, 11)
    current = v4_queue(first, second)
    monkeypatch.setattr(
        scope.carrier, "_load_authority_bundle",
        lambda sha: SimpleNamespace(missions=[
            {"repository": private}, {"repository": public},
        ]),
    )
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", "")
    monkeypatch.setenv("GITHUB_RUN_ID", "39505195811")
    monkeypatch.setattr(scope.carrier, "_public_get",
                        lambda path, allow_404=False: (
                            {"full_name": public, "private": False}
                            if path == "repos/" + public else None))
    state = {"main_sha": "a" * 40, "queue": current}
    assert scope.choose("native", state) == [public]
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", private)
    assert scope.choose("native", state) == [private]
    monkeypatch.setenv("CONTROL_V4_START_REPOSITORY", "")
    assert scope.choose("native", {"main_sha": "a" * 40,
                                   "queue": v4_queue(first)}) == []


def test_default_native_scope_is_after_gap_queue_append_and_before_carrier():
    text = (Path(__file__).resolve().parents[1] /
            ".github/workflows/control-v4-runtime-carrier.yml").read_text()
    native = text.split("\n  interactive-control-start:\n", 1)[1]
    assert (native.index("Queue one existing authorized Mission gap")
            < native.index("Resolve exact target read scope")
            < native.index("Acquire via existing authority, lease and atomic CAS checks"))
    assert "CONTROL_V4_START_REPOSITORY: ${{ steps.target-scope.outputs.native_repository }}" in native



def test_holderless_public_tick_cannot_scope_private_or_hide_public_work(monkeypatch, tmp_path):
    import json
    from test_v4_terminal_target_recovery import queue as make_queue, task as make_task

    private_task = make_task("MISSION--M--2026-09-22-r1--G1", MEMORY, 10)
    public_task = make_task("MISSION--M--2026-09-22-r1--G2", PUBLIC, 11)
    current = make_queue(private_task, public_task)
    state = {"main_sha": "a" * 40, "queue": current}
    monkeypatch.setattr(scope.carrier, "_load_authority_bundle", lambda _: SimpleNamespace(
        missions=[{"repository": MEMORY}, {"repository": PUBLIC}]
    ))
    monkeypatch.setattr(scope.carrier, "_load_current", lambda: state)
    monkeypatch.setattr(scope.carrier, "_public_get", lambda path, allow_404=False: (
        {"full_name": PUBLIC, "private": False} if path == "repos/" + PUBLIC else None
    ))
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", "CONTROL_V4_RUNTIME_TICK " +
                       json.dumps({"run_id": "v41:control-go:39841658834"}))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "event")
    output = tmp_path / "scope-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert scope.choose("event", state) == [PUBLIC]
    scope.main()
    assert "has_targets=false" in output.read_text()
    output.unlink()

    state["queue"] = make_queue(private_task)
    assert scope.choose("event", state) == []
    scope.main()
    assert "has_targets=false" in output.read_text()
    assert "repository_names<<CONTROL_SCOPE_END\n\nCONTROL_SCOPE_END" in output.read_text()


@pytest.mark.parametrize("kind", ["TICK", "EVENT"])
def test_private_event_scope_requires_matching_unexpired_holder(monkeypatch, tmp_path, kind):
    import json
    from datetime import datetime, timedelta, timezone
    from test_v4_terminal_target_recovery import queue as make_queue, task as make_task

    run_id = "v41:control-go:39841658834"
    task = make_task("MISSION--M--2026-09-22-r1--G1", MEMORY, 10)
    current = make_queue(task)
    current["execution_lock"] = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "started_at": "2026-10-22T19:37:37Z",
        "expires_at": "2000-01-01T00:00:00Z",
    }
    state = {"main_sha": "a" * 40, "queue": current}
    monkeypatch.setattr(scope.carrier, "_load_authority_bundle",
                        lambda _: SimpleNamespace(missions=[{"repository": MEMORY}]))
    monkeypatch.setattr(scope.carrier, "_load_current", lambda: state)
    monkeypatch.setattr(scope.carrier, "_public_get", lambda path, allow_404=False: None)
    if kind == "TICK":
        command = {"run_id": run_id}
    else:
        command = {"run_id": run_id, "task_token": "a" * 64,
                   "event": "YIELD", "repository": MEMORY, "action": "REPAIR"}
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", "CONTROL_V4_RUNTIME_" +
                       kind + " " + json.dumps(command))
    monkeypatch.setenv("CONTROL_TARGET_SCOPE_MODE", "event")
    output = tmp_path / "scope-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert scope.choose("event", state) == []
    scope.main()
    assert "has_targets=false" in output.read_text()
    assert "memory" not in output.read_text()
    output.unlink()

    current["execution_lock"]["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=30)
    ).isoformat()
    assert scope.choose("event", state) == [MEMORY]
    scope.main()
    assert "has_targets=true" in output.read_text()
    assert "memory" in output.read_text().splitlines()


def test_public_issue_tick_selects_public_task_without_private_candidate_read(monkeypatch):
    from test_v4_terminal_target_recovery import (
        NOW, candidate, fake_state, queue as make_queue, task as make_task,
    )

    private_task = make_task("MISSION--M--2026-09-22-r1--G1", MEMORY, 10)
    public_task = make_task("MISSION--M--2026-09-22-r1--G2", PUBLIC, 11)
    current = make_queue(private_task, public_task)
    seen = []
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.delenv("CONTROL_V4_START_REPOSITORY", raising=False)
    monkeypatch.setattr(scope.carrier, "_public_get", lambda path, allow_404=False: (
        {"full_name": PUBLIC, "private": False} if path == "repos/" + PUBLIC else None
    ))
    monkeypatch.setattr(scope.carrier, "_target_pr_candidate",
                        lambda repository, pr: seen.append(repository) or candidate("2" * 40, pr))
    monkeypatch.setattr(scope.carrier, "_read_review_observation",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(scope.carrier, "_write_queue_exact",
                        lambda state, q, *, reason: {**state, "queue": q})

    updated, result = scope.carrier._tick(
        {"kind": "TICK", "run_id": "public-event-test", "yielded_task_tokens": []},
        fake_state(current), now=NOW,
    )
    assert result["result"] == "WORK"
    assert result["repository"] == PUBLIC
    assert seen == [PUBLIC]
    assert updated["queue"]["execution_lock"]["task_id"] == public_task["task_id"]
