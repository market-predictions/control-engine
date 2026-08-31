from datetime import datetime, timezone
from pathlib import Path
import subprocess

from control_engine import kernel_v31 as core
from scripts import control_kernel_v31 as bridge

NOW = datetime(2026, 8, 31, 9, 15, tzinfo=timezone.utc)
EXPECTED_BASE = "2" * 40
CANDIDATE = "1" * 40
MERGE = "3" * 40
REVISION = "2026-08-31-r1"
REPOSITORY = "owner/repo"


def candidate():
    return {
        "candidate_sha": CANDIDATE,
        "candidate_pr_number": 7,
        "candidate_head_branch": "control/candidate",
        "expected_base_branch": "main",
        "expected_base_sha": EXPECTED_BASE,
    }


def assurance_task():
    return {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": core.deterministic_root_id("M1", REVISION, "G1") + "--ASSURANCE-111111111111",
        "operation": "ASSURANCE",
        "role": core.ROLE_B,
        "repository": REPOSITORY,
        "candidate": candidate(),
        "status": core.STATUS_TERMINAL,
        "outcome": "PASS",
        "claim": None,
        "result_ref": "control/worker-results/pass.json",
        "terminal_run_id": "run-b1",
        "attempt_count": 1,
        "last_execution_error": None,
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-31T08:00:00Z",
        "updated_at": "2026-08-31T08:30:00Z",
        "mission_id": "M1",
        "mission_revision": REVISION,
        "mission_contract_blob_sha": "a" * 40,
        "repository_authority_blob_sha": "b" * 40,
        "gap_id": "G1",
        "integration_policy": "AUTO_AFTER_PASS",
        "acceptance": ["done"],
        "integration_state": "PENDING",
    }


def queue():
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [],
        "tasks": [assurance_task()],
    }


def auto_authority():
    return {
        "integration_policy": "AUTO_AFTER_PASS",
        "integration_enabled": True,
        "control_auto_profile": "CONTROL_AUTO_V1",
        "required_check_runs": [],
    }


def patch_common(monkeypatch, *, live_authority=True):
    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda *_: auto_authority())
    monkeypatch.setattr(bridge, "_has_live_task_authority", lambda *_: live_authority)
    monkeypatch.setattr(bridge, "_integration_authorized", lambda *_: live_authority)
    monkeypatch.setattr(bridge, "_required_checks_green", lambda *_: True)
    monkeypatch.setattr(bridge, "_publish_assurance_status", lambda *_: None)
    monkeypatch.setattr(bridge, "_merged_commit_proves_expected_candidate", lambda *_args, **_kwargs: True)


def test_atomic_integration_uses_exact_synthetic_merge_and_leased_base_ref(monkeypatch):
    patch_common(monkeypatch)
    branch_reads = iter([EXPECTED_BASE, MERGE])
    monkeypatch.setattr(bridge, "_branch_sha", lambda *_: next(branch_reads))

    def api(_token, method, path, body=None):
        assert body is None
        if method == "GET" and path.endswith("/pulls/7"):
            return {"state": "open", "merged": False, "head": {"sha": CANDIDATE}, "base": {"ref": "main"}}
        if method == "GET" and path.endswith("/git/ref/pull/7/merge"):
            return {"object": {"sha": MERGE}}
        raise AssertionError((method, path))

    monkeypatch.setattr(bridge, "_api", api)
    calls = []

    def fast_forward(token, repository, branch, *, pr_number, merge_sha, expected_base_sha):
        calls.append((token, repository, branch, pr_number, merge_sha, expected_base_sha))
        return True

    monkeypatch.setattr(bridge, "_fast_forward_branch_ref", fast_forward)

    updated, report = bridge._integrate_one(
        queue(),
        missions=[],
        repo_auth={REPOSITORY: auto_authority()},
        control_token="control",
        target_token="target",
        target_task_id=assurance_task()["task_id"],
        target_repository=REPOSITORY,
        now=NOW,
    )

    assert report == {"integration": "MERGED", "task_id": assurance_task()["task_id"], "merge_sha": MERGE}
    assert calls == [("target", REPOSITORY, "main", 7, MERGE, EXPECTED_BASE)]
    assert updated["tasks"][0]["integration_state"] == "MERGED"
    assert updated["tasks"][0]["merge_sha"] == MERGE


def test_git_ref_update_uses_exact_expected_old_sha_lease(monkeypatch):
    git_calls = []
    monkeypatch.setattr(bridge, "_init_repo", lambda *_: None)

    def fake_git(_token, _repo, args, *, check=True):
        git_calls.append((list(args), check))
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_run(cmd, *, cwd=None, check=True):
        assert cmd == ["git", "rev-parse", "FETCH_HEAD"]
        return subprocess.CompletedProcess(cmd, 0, MERGE + "\n", "")

    monkeypatch.setattr(bridge, "_git", fake_git)
    monkeypatch.setattr(bridge, "_run", fake_run)

    assert bridge._fast_forward_branch_ref(
        "target",
        REPOSITORY,
        "main",
        pr_number=7,
        merge_sha=MERGE,
        expected_base_sha=EXPECTED_BASE,
    )
    assert git_calls[0] == (["fetch", "--quiet", "--depth=1", "origin", "refs/pull/7/merge"], False)
    assert git_calls[1] == ([
        "push",
        "--quiet",
        f"--force-with-lease=refs/heads/main:{EXPECTED_BASE}",
        "origin",
        f"{MERGE}:refs/heads/main",
    ], False)


def test_atomic_ref_race_materializes_base_drift_without_false_merge(monkeypatch):
    patch_common(monkeypatch)
    monkeypatch.setattr(bridge, "_branch_sha", lambda *_: EXPECTED_BASE)
    monkeypatch.setattr(bridge, "_fast_forward_branch_ref", lambda *_args, **_kwargs: False)

    def api(_token, method, path, body=None):
        assert body is None
        if method == "GET" and path.endswith("/pulls/7"):
            return {"state": "open", "merged": False, "head": {"sha": CANDIDATE}, "base": {"ref": "main"}}
        if method == "GET" and path.endswith("/git/ref/pull/7/merge"):
            return {"object": {"sha": MERGE}}
        raise AssertionError((method, path))

    monkeypatch.setattr(bridge, "_api", api)

    updated, report = bridge._integrate_one(
        queue(), [], {REPOSITORY: auto_authority()}, "control", "target",
        assurance_task()["task_id"], REPOSITORY, NOW,
    )

    assert report["integration"] == "BASE_DRIFT"
    assert updated["tasks"][0]["integration_state"] == "BASE_DRIFT"
    assert any(task.get("operation") == "REPAIR" and task.get("reason") == "BASE_DRIFT_AFTER_PASS" for task in updated["tasks"])


def test_open_recovery_without_live_authority_is_held_once_and_stops_blocking(monkeypatch):
    patch_common(monkeypatch, live_authority=False)
    monkeypatch.setattr(bridge, "_branch_sha", lambda *_: EXPECTED_BASE)

    def api(_token, method, path, body=None):
        assert body is None
        if method == "GET" and path.endswith("/pulls/7"):
            return {"state": "open", "merged": False, "head": {"sha": CANDIDATE}, "base": {"ref": "main"}}
        raise AssertionError((method, path))

    monkeypatch.setattr(bridge, "_api", api)

    updated, report = bridge._integrate_one(
        queue(), [], {REPOSITORY: auto_authority()}, "control", "target",
        assurance_task()["task_id"], REPOSITORY, NOW,
    )

    assert report["integration"] == "HOLD_MISSION_AUTHORITY"
    assert updated["tasks"][0]["integration_state"] == "HOLD"
    assert bridge._integration_candidates(updated) == []


def test_kernel_source_has_no_rest_pull_merge_side_effect():
    source = (Path(__file__).resolve().parents[1] / "scripts" / "control_kernel_v31.py").read_text(encoding="utf-8")
    assert 'pulls/{pr_number}/merge' not in source
    assert 'git/ref/pull/{pr_number}/merge' in source
    assert "--force-with-lease=refs/heads/" in source
    assert '"force": False' not in source
