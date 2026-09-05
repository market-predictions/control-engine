from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_kernel_v31.py"
spec = importlib.util.spec_from_file_location("control_kernel_v31", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bridge)

NOW = datetime(2026, 8, 30, 22, 0, tzinfo=timezone.utc)


def authority(*, repository="o/r", policy="AUTO_AFTER_PASS", enabled=True, profile="CONTROL_AUTO_V1", checks=()):
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V3_1",
        "repository": repository,
        "integration_policy": policy,
        "integration_enabled": enabled,
        "control_auto_profile": profile,
        "required_check_runs": list(checks),
        "principal_manual_relay_count": 0,
    }


def task(*, repository="o/r", mission_id="M1", gap_id="G1"):
    return {
        "repository": repository,
        "mission_id": mission_id,
        "mission_revision": "r1",
        "gap_id": gap_id,
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "integration_policy": "AUTO_AFTER_PASS",
    }


def integration_task(*, repository="o/r", mission_id="M1", gap_id="G1", task_id=None, updated_at="2026-08-30T21:00:00Z"):
    task_id = task_id or bridge.core.deterministic_root_id(mission_id, "r1", gap_id) + "--ASSURANCE-aaaaaaaaaaaa"
    return {
        **task(repository=repository, mission_id=mission_id, gap_id=gap_id),
        "lifecycle_model": bridge.core.PROTOCOL_ID,
        "task_id": task_id,
        "operation": "ASSURANCE",
        "role": bridge.core.ROLE_B,
        "status": bridge.core.STATUS_TERMINAL,
        "outcome": "PASS",
        "claim": None,
        "result_ref": "control/worker-results/result.json",
        "terminal_run_id": "run-b1",
        "attempt_count": 1,
        "last_execution_error": None,
        "principal_manual_relay_count": 0,
        "created_at": "2026-08-30T20:00:00Z",
        "updated_at": updated_at,
        "candidate": {
            "candidate_sha": "a" * 40,
            "candidate_pr_number": 7,
            "candidate_head_branch": "control/candidate",
            "expected_base_branch": "main",
            "expected_base_sha": "b" * 40,
        },
        "integration_state": "PENDING",
    }


def v31_queue(*tasks):
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [],
        "tasks": list(tasks),
    }


def mission_wrapper(*, mission_id="M1", repository="o/r", gap_id="G1"):
    return {
        "mission": {
            "mission_id": mission_id,
            "mission_revision": "r1",
            "repository": repository,
            "gaps": [{"gap_id": gap_id, "gap_state": "OPEN"}],
        },
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "3" * 40,
    }


def test_live_repository_authority_blob_change_does_not_revoke_semantic_claim_authority():
    bridge._assert_live_task_authority(task(), [mission_wrapper()], {"o/r": authority(policy="HOLD_AFTER_PASS", enabled=False, profile="NONE")})


def test_integration_requires_frozen_and_live_auto_authority():
    t = task()
    assert bridge._frozen_integration_authorized(t, authority()) is True
    assert bridge._integration_authorized(t, authority(), authority()) is True
    assert bridge._integration_authorized(t, authority(policy="HOLD_AFTER_PASS"), authority()) is False
    assert bridge._integration_authorized(t, authority(), authority(policy="HOLD_AFTER_PASS")) is False
    assert bridge._integration_authorized(t, authority(enabled=False), authority()) is False
    assert bridge._integration_authorized(t, authority(), authority(enabled=False)) is False
    assert bridge._integration_authorized(t, authority(profile="NONE"), authority()) is False
    assert bridge._integration_authorized(t, authority(), authority(profile="NONE")) is False


def test_live_auto_cannot_expand_task_frozen_hold():
    t = task()
    t["integration_policy"] = "HOLD_AFTER_PASS"
    assert bridge._frozen_integration_authorized(t, authority()) is False
    assert bridge._integration_authorized(t, authority(), authority()) is False


def test_required_checks_are_union_of_frozen_and_live_restrictions():
    frozen = authority(checks=["ci/a", "ci/shared"])
    live = authority(checks=["ci/shared", "ci/b"])
    assert bridge._effective_required_checks(frozen, live) == ["ci/a", "ci/b", "ci/shared"]


def test_required_checks_fail_closed_on_invalid_shape():
    bad = authority()
    bad["required_check_runs"] = "ci/a"
    with pytest.raises(bridge.BridgeError, match="required checks"):
        bridge._effective_required_checks(bad, authority())


def test_planner_uses_frozen_auto_so_post_merge_recovery_survives_live_hold(monkeypatch):
    t = integration_task()
    q = v31_queue(t)
    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda _token, _task: authority(repository=_task["repository"]))
    hold = authority(policy="HOLD_AFTER_PASS", enabled=False, profile="NONE")
    assert bridge._plan_integration_target(
        q,
        {"control_runtime_enabled": True, "integration_enabled": True},
        [mission_wrapper()],
        {"o/r": hold},
        "control",
    ) == (t["task_id"], "o/r")
    assert bridge._plan_integration_target(
        q,
        {"control_runtime_enabled": False, "integration_enabled": True},
        [mission_wrapper()],
        {"o/r": hold},
        "control",
    ) == ("", "")
    assert bridge._plan_integration_target(
        q,
        {"control_runtime_enabled": True, "integration_enabled": False},
        [mission_wrapper()],
        {"o/r": hold},
        "control",
    ) == ("", "")


def test_planner_prefers_live_auto_over_older_frozen_only_recovery_candidate(monkeypatch):
    older_hold = integration_task(
        repository="o/hold",
        mission_id="M1",
        task_id="OLDER--ASSURANCE-aaaaaaaaaaaa",
        updated_at="2026-08-30T20:00:00Z",
    )
    later_auto = integration_task(
        repository="o/auto",
        mission_id="M2",
        task_id="LATER--ASSURANCE-bbbbbbbbbbbb",
        updated_at="2026-08-30T21:00:00Z",
    )
    q = v31_queue(older_hold, later_auto)

    monkeypatch.setattr(
        bridge,
        "_frozen_repository_authority",
        lambda _token, t: authority(repository=t["repository"]),
    )
    repo_auth = {
        "o/hold": authority(repository="o/hold", policy="HOLD_AFTER_PASS", enabled=False, profile="NONE"),
        "o/auto": authority(repository="o/auto"),
    }
    missions = [
        mission_wrapper(mission_id="M1", repository="o/hold"),
        mission_wrapper(mission_id="M2", repository="o/auto"),
    ]
    assert bridge._plan_integration_target(
        q,
        {"control_runtime_enabled": True, "integration_enabled": True},
        missions,
        repo_auth,
        "control",
    ) == (later_auto["task_id"], "o/auto")


def test_planner_and_executor_keep_exact_same_task_within_repository(monkeypatch):
    older = integration_task(task_id="OLDER", updated_at="2026-08-30T20:00:00Z")
    later = integration_task(task_id="LATER", updated_at="2026-08-30T21:00:00Z")
    later["candidate"] = {**later["candidate"], "candidate_sha": "c" * 40, "candidate_pr_number": 8}
    q = v31_queue(older, later)

    monkeypatch.setattr(
        bridge,
        "_frozen_repository_authority",
        lambda _token, t: authority(policy="HOLD_AFTER_PASS", enabled=False, profile="NONE") if t["task_id"] == "OLDER" else authority(),
    )
    planned = bridge._plan_integration_target(
        q,
        {"control_runtime_enabled": True, "integration_enabled": True},
        [mission_wrapper()],
        {"o/r": authority()},
        "control",
    )
    assert planned == ("LATER", "o/r")

    seen = []
    branch_reads = iter(["b" * 40, "d" * 40])
    fast_forwards = []

    def fake_api(_token, method, path, body=None):
        seen.append((method, path, body))
        if path.endswith("/pulls/8") and method == "GET":
            return {"state": "open", "merged": False, "head": {"sha": "c" * 40}, "base": {"ref": "main"}}
        if "check-runs" in path:
            return {"check_runs": []}
        if path.endswith("/statuses/" + "c" * 40):
            return {}
        if path.endswith("/git/ref/pull/8/merge") and method == "GET":
            return {"object": {"sha": "d" * 40}}
        if path.endswith("/commits/" + "d" * 40):
            return {"sha": "d" * 40, "parents": [{"sha": "b" * 40}, {"sha": "c" * 40}]}
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "_api", fake_api)
    monkeypatch.setattr(bridge, "_branch_sha", lambda *_args, **_kwargs: next(branch_reads))

    def fake_fast_forward(token, repository, branch, *, pr_number, merge_sha, expected_base_sha):
        assert pr_number == 8
        fast_forwards.append((token, repository, branch, merge_sha, expected_base_sha))
        return True

    monkeypatch.setattr(bridge, "_fast_forward_branch_ref", fake_fast_forward)
    monkeypatch.setattr(bridge.core, "mark_integrated", lambda queue_arg, **_kwargs: queue_arg)
    _, report = bridge._integrate_one(q, [mission_wrapper()], {"o/r": authority()}, "control", "target", "LATER", "o/r", NOW)
    assert report["task_id"] == "LATER"
    assert report["integration"] == "MERGED"
    assert all("/pulls/7" not in path for _, path, _ in seen)
    assert fast_forwards == [("target", "o/r", "main", "d" * 40, "b" * 40)]


def test_open_candidate_with_revoked_mission_authority_never_merges(monkeypatch):
    t = integration_task()
    q = v31_queue(t)
    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda _token, _task: authority())
    monkeypatch.setattr(bridge, "_branch_sha", lambda *_args, **_kwargs: "b" * 40)
    calls = []

    def fake_api(_token, method, path, body=None):
        calls.append((method, path, body))
        if "/pulls/" in path and method == "GET":
            return {"state": "open", "merged": False, "head": {"sha": "a" * 40}, "base": {"ref": "main"}}
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "_api", fake_api)
    held, report = bridge._integrate_one(q, [], {"o/r": authority()}, "control", "target", t["task_id"], "o/r", NOW)
    assert report["integration"] == "HOLD_MISSION_AUTHORITY"
    assert held["tasks"][0]["integration_state"] == "HOLD"
    assert all(method == "GET" for method, _, _ in calls)


def test_already_merged_exact_candidate_reconciles_after_lost_runtime_write(monkeypatch):
    t = integration_task()
    queue = v31_queue(t)
    live = authority(policy="HOLD_AFTER_PASS", enabled=False, profile="NONE")
    frozen = authority()
    calls = []

    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda _token, _task: frozen)

    def fake_api(_token, method, path, body=None):
        calls.append((method, path, body))
        assert method == "GET"
        if "/pulls/" in path:
            return {
                "state": "closed",
                "merged": True,
                "head": {"sha": "a" * 40},
                "base": {"ref": "main"},
                "merge_commit_sha": "c" * 40,
            }
        if "/commits/" in path:
            return {
                "sha": "c" * 40,
                "parents": [{"sha": "b" * 40}, {"sha": "a" * 40}],
            }
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "_api", fake_api)
    marked = {}

    def fake_mark(queue_arg, *, assurance_task_id, merge_sha, merged_at):
        marked.update(task_id=assurance_task_id, merge_sha=merge_sha, merged_at=merged_at)
        return {**queue_arg, "reconciled": True}

    monkeypatch.setattr(bridge.core, "mark_integrated", fake_mark)
    q, report = bridge._integrate_one(queue, [], {"o/r": live}, "control", "target", t["task_id"], "o/r", NOW)

    assert q["reconciled"] is True
    assert report["integration"] == "RECONCILED_MERGED"
    assert report["merge_sha"] == "c" * 40
    assert marked["task_id"] == t["task_id"]
    assert len(calls) == 2


def test_already_merged_candidate_rejects_unassured_merge_base(monkeypatch):
    t = integration_task()
    queue = v31_queue(t)
    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda _token, _task: authority())

    def fake_api(_token, method, path, body=None):
        if "/pulls/" in path:
            return {
                "state": "closed",
                "merged": True,
                "head": {"sha": "a" * 40},
                "base": {"ref": "main"},
                "merge_commit_sha": "c" * 40,
            }
        if "/commits/" in path:
            return {
                "sha": "c" * 40,
                "parents": [{"sha": "d" * 40}, {"sha": "a" * 40}],
            }
        raise AssertionError(path)

    monkeypatch.setattr(bridge, "_api", fake_api)
    with pytest.raises(bridge.BridgeError, match="frozen base and candidate parents"):
        bridge._integrate_one(queue, [], {"o/r": authority()}, "control", "target", t["task_id"], "o/r", NOW)


def test_already_merged_candidate_never_legitimizes_missing_frozen_auto_authority(monkeypatch):
    t = integration_task()
    queue = v31_queue(t)
    frozen = authority(policy="HOLD_AFTER_PASS", enabled=False, profile="NONE")
    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda _token, _task: frozen)
    monkeypatch.setattr(
        bridge,
        "_api",
        lambda *_args, **_kwargs: {
            "state": "closed",
            "merged": True,
            "head": {"sha": "a" * 40},
            "base": {"ref": "main"},
            "merge_commit_sha": "c" * 40,
        },
    )
    with pytest.raises(bridge.BridgeError, match="lacks frozen AUTO authority"):
        bridge._integrate_one(queue, [], {"o/r": authority()}, "control", "target", t["task_id"], "o/r", NOW)


def test_already_merged_candidate_requires_exact_frozen_identity(monkeypatch):
    t = integration_task()
    queue = v31_queue(t)
    monkeypatch.setattr(bridge, "_frozen_repository_authority", lambda _token, _task: authority())
    monkeypatch.setattr(
        bridge,
        "_api",
        lambda *_args, **_kwargs: {
            "state": "closed",
            "merged": True,
            "head": {"sha": "d" * 40},
            "base": {"ref": "main"},
            "merge_commit_sha": "c" * 40,
        },
    )
    with pytest.raises(bridge.BridgeError, match="exact PASS candidate"):
        bridge._integrate_one(queue, [], {"o/r": authority()}, "control", "target", t["task_id"], "o/r", NOW)
