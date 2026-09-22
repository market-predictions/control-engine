from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_contracts import acquire_task_v4
from control_engine.v4_runtime_protocol import parse_public_command, safe_work_capsule
from control_engine.v4_safety import NO_PROGRESS_BLOCKER, mark_no_progress_recheck_v4


NOW = datetime(2026, 9, 15, 18, 30, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
BASE_SHA = "c" * 40
MISSION_BLOB = "d" * 40
AUTHORITY_BLOB = "e" * 40


def candidate(sha: str = OLD_SHA, base_sha: str = BASE_SHA) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": 125,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": base_sha,
    }


def task(
    *,
    status: str = "ACTIVE",
    phase: str | None = "REPAIR",
    blocker: str | None = None,
    review_policy: str = "INTERNAL",
    external_review: dict | None = None,
) -> dict:
    return {
        "task_id": "MISSION--M--2026-09-15-r1--G1",
        "mission_id": "M",
        "mission_revision": "2026-09-15-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["candidate must make real repair progress"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": review_policy,
        "convergence_required": False,
        "status": status,
        "phase": phase,
        "candidate": candidate(),
        "last_review": {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
            "verdict": "REPAIR_REQUIRED" if phase == "REPAIR" else "PASS",
            "reviewed_at": "2026-09-15T17:30:00Z",
        },
        "external_review": external_review,
        "blocker": blocker,
        "created_at": "2026-09-15T16:00:00Z",
        "updated_at": "2026-09-15T17:30:00Z",
    }


def queue(one_task: dict, *, run_id: str = "run-1", locked: bool = True) -> dict:
    lock = None
    if locked:
        lock = {
            "run_id": run_id,
            "task_id": one_task["task_id"],
            "started_at": "2026-09-15T18:00:00Z",
            "expires_at": "2026-09-15T19:30:00Z",
        }
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": [],
        "tasks": [one_task],
    }


def event_body(q: dict, event: str, **extra: object) -> str:
    current = q["tasks"][0]
    run_id = q["execution_lock"]["run_id"]
    capsule = safe_work_capsule(q, task_id=current["task_id"], run_id=run_id)
    payload = {
        "run_id": run_id,
        "task_token": capsule["task_token"],
        "event": event,
        "repository": capsule["repository"],
        "action": capsule["action"],
        "candidate": capsule["candidate"],
        **extra,
    }
    return "CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":"))


def fake_state(q: dict) -> dict:
    return {
        "queue": q,
        "runtime_enabled": True,
        "integration_enabled": False,
        "main_sha": "1" * 40,
        "runtime_sha": "2" * 40,
        "queue_blob": "3" * 40,
        "repository_node_id": "R_test",
    }


def install_fake_write(monkeypatch, writes: list[tuple[dict, str]]) -> None:
    def fake_write(state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)


def test_first_noop_repair_becomes_one_bounded_recheck_then_blocks(monkeypatch) -> None:
    q = queue(task())
    parsed = parse_public_command(
        event_body(
            q,
            "CANDIDATE_READY",
            new_candidate_sha=OLD_SHA,
            candidate_pr_number=125,
            candidate_head_branch="candidate",
            new_expected_base_branch="main",
            new_expected_base_sha=BASE_SHA,
        )
    )
    writes: list[tuple[dict, str]] = []
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: candidate())
    install_fake_write(monkeypatch, writes)

    state, result = carrier._event(parsed, fake_state(q), now=NOW)
    marked = state["queue"]
    marked_task = marked["tasks"][0]
    assert result["result"] == "YIELDED"
    assert marked_task["status"] == "ACTIVE"
    assert marked_task["phase"] == "REVIEW"
    assert marked_task["blocker"] == NO_PROGRESS_BLOCKER
    assert marked_task["candidate"]["candidate_sha"] == OLD_SHA
    assert marked["execution_lock"] is None
    assert writes[-1][1] == "candidate-ready"

    reacquired = acquire_task_v4(
        marked,
        task_id=marked_task["task_id"],
        run_id="run-2",
        now=NOW,
        control_runtime_enabled=True,
        integration_enabled=False,
    )
    parsed_recheck = parse_public_command(event_body(reacquired, "INTERNAL_REPAIR"))
    state2, result2 = carrier._event(parsed_recheck, {**state, "queue": reacquired}, now=NOW)
    blocked = state2["queue"]["tasks"][0]
    assert result2["result"] == "YIELDED"
    assert blocked["status"] == "BLOCKED"
    assert blocked["phase"] is None
    assert blocked["blocker"] == NO_PROGRESS_BLOCKER
    assert state2["queue"]["execution_lock"] is None


def test_no_progress_recheck_can_pass_without_candidate_change(monkeypatch) -> None:
    marked_task = task(phase="REVIEW", blocker=NO_PROGRESS_BLOCKER)
    q = queue(marked_task, run_id="run-pass")
    parsed = parse_public_command(event_body(q, "INTERNAL_PASS"))
    writes: list[tuple[dict, str]] = []
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: candidate())
    install_fake_write(monkeypatch, writes)

    state, result = carrier._event(parsed, fake_state(q), now=NOW)
    current = state["queue"]["tasks"][0]
    assert result["result"] == "READY"
    assert current["status"] == "READY"
    assert current["phase"] is None
    assert current["blocker"] is None
    assert current["last_review"]["verdict"] == "PASS"
    assert state["queue"]["execution_lock"] is None


def test_noop_repair_after_admitted_external_failure_parks_immediately() -> None:
    external_fail = {
        "candidate_sha": OLD_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
        "status": "FAIL",
        "request_ref": "https://github.com/example/repo/pull/125#issuecomment-1",
        "evidence_ref": "https://github.com/example/repo/pull/125#issuecomment-2",
    }
    current = task(review_policy="EXTERNAL", external_review=external_fail)
    current["last_review"]["verdict"] = "PASS"
    q = queue(current, run_id="run-external")

    updated = mark_no_progress_recheck_v4(
        q,
        task_id=current["task_id"],
        run_id="run-external",
        now=NOW,
    )
    parked = updated["tasks"][0]
    assert parked["status"] == "BLOCKED"
    assert parked["phase"] is None
    assert parked["blocker"] == NO_PROGRESS_BLOCKER
    assert parked["external_review"]["status"] == "FAIL"
    assert updated["execution_lock"] is None


def test_blocked_no_progress_task_stays_parked_while_live_identity_is_exact(monkeypatch) -> None:
    q = queue(task(status="BLOCKED", phase=None, blocker=NO_PROGRESS_BLOCKER), locked=False)
    writes: list[tuple[dict, str]] = []
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: candidate())
    install_fake_write(monkeypatch, writes)

    state, result = carrier._tick(
        {"kind": "TICK", "run_id": "run-exact", "yielded_task_tokens": []},
        fake_state(q),
        now=NOW,
    )
    assert result["result"] == "NO_WORK"
    assert state["queue"] == q
    assert writes == []


def test_blocked_no_progress_task_auto_resumes_only_after_real_candidate_drift(monkeypatch) -> None:
    q = queue(task(status="BLOCKED", phase=None, blocker=NO_PROGRESS_BLOCKER), locked=False)
    live = candidate(NEW_SHA)
    writes: list[tuple[dict, str]] = []
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: live)
    install_fake_write(monkeypatch, writes)

    state, result = carrier._tick(
        {"kind": "TICK", "run_id": "run-drift", "yielded_task_tokens": []},
        fake_state(q),
        now=NOW,
    )
    current = state["queue"]["tasks"][0]
    assert result["result"] == "WORK"
    assert result["action"] == "REPAIR"
    assert result["candidate"]["candidate_sha"] == OLD_SHA
    assert result["live_candidate"]["candidate_sha"] == NEW_SHA
    assert current["status"] == "ACTIVE"
    assert current["phase"] == "REPAIR"
    assert current["blocker"] is None
    assert state["queue"]["execution_lock"]["run_id"] == "run-drift"
    assert writes[-1][1] == "no-progress-unblock-acquire"


def test_candidate_ready_during_review_drift_yields_to_repair_before_rebind(monkeypatch) -> None:
    external_pending = {
        "candidate_sha": OLD_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
        "status": "PENDING",
        "request_ref": "https://github.com/example/repo/pull/125#issuecomment-1",
        "evidence_ref": None,
    }
    current = task(phase="REVIEW", review_policy="EXTERNAL", external_review=external_pending)
    q = queue(current, run_id="run-review-drift")
    parsed = parse_public_command(
        event_body(
            q,
            "CANDIDATE_READY",
            new_candidate_sha=NEW_SHA,
            candidate_pr_number=125,
            candidate_head_branch="candidate",
            new_expected_base_branch="main",
            new_expected_base_sha=BASE_SHA,
        )
    )
    writes: list[tuple[dict, str]] = []
    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: candidate(NEW_SHA))
    install_fake_write(monkeypatch, writes)

    state, result = carrier._event(parsed, fake_state(q), now=NOW)
    drifted = state["queue"]["tasks"][0]
    assert result["result"] == "YIELDED"
    assert drifted["status"] == "ACTIVE"
    assert drifted["phase"] == "REPAIR"
    assert drifted["candidate"]["candidate_sha"] == OLD_SHA
    assert state["queue"]["execution_lock"] is None
    assert writes[-1][1] == "candidate-drift-to-repair"

    reacquired = acquire_task_v4(
        state["queue"],
        task_id=drifted["task_id"],
        run_id="run-review-drift-repair",
        now=NOW,
        control_runtime_enabled=True,
        integration_enabled=False,
    )
    parsed_repair = parse_public_command(
        event_body(
            reacquired,
            "CANDIDATE_READY",
            new_candidate_sha=NEW_SHA,
            candidate_pr_number=125,
            candidate_head_branch="candidate",
            new_expected_base_branch="main",
            new_expected_base_sha=BASE_SHA,
        )
    )
    state2, result2 = carrier._event(parsed_repair, {**state, "queue": reacquired}, now=NOW)
    rebound = state2["queue"]["tasks"][0]
    assert result2["result"] == "YIELDED"
    assert rebound["phase"] == "REVIEW"
    assert rebound["candidate"]["candidate_sha"] == NEW_SHA
    assert rebound["last_review"] is None
    assert rebound["external_review"] is None
    assert rebound["blocker"] is None
    assert state2["queue"]["execution_lock"] is None
    assert writes[-1][1] == "candidate-ready"
