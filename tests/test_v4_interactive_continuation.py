"""Behavioral regressions for one native start across a task's phases."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import textwrap

import pytest

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import parse_public_command, safe_work_capsule
from test_v4_event_boundary_release import (
    NEW_SHA, NOW, candidate, queue, run_event, task,
)


RUN_ID = "v41:control-go:39033163807"


def interactive_queue(*, phase="BUILD", review_policy="EXTERNAL"):
    value = queue(task(phase=phase, review_policy=review_policy))
    value["execution_lock"]["run_id"] = RUN_ID
    if phase == "BUILD":
        value["tasks"][0]["candidate"] = None
    return value


def command(q, name, **extra):
    current = q["tasks"][0]
    work = safe_work_capsule(q, task_id=current["task_id"], run_id=RUN_ID)
    payload = {key: work[key] for key in ("run_id", "task_token", "repository", "action")}
    if "candidate" in work:
        payload["candidate"] = work["candidate"]
    payload.update(event=name, **extra)
    return parse_public_command("CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload))


def test_one_native_start_build_review_repair_review_keeps_original_claim(monkeypatch):
    q = interactive_queue()
    original_lock = deepcopy(q["execution_lock"])
    other = task()
    other["task_id"] = "MISSION--M--2026-09-09-r1--G2"
    other["gap_id"] = "G2"
    other["status"] = "QUEUED"
    other["phase"] = "BUILD"
    other["candidate"] = None
    q["tasks"].append(other)

    for name, extra, expected_action in (
        ("CANDIDATE_READY", {
            "new_candidate_sha": candidate()["candidate_sha"],
            "candidate_pr_number": 120, "candidate_head_branch": "candidate",
            "new_expected_base_branch": "main",
            "new_expected_base_sha": candidate()["expected_base_sha"],
        }, "REVIEW_INTERNAL"),
        ("INTERNAL_REPAIR", {}, "REPAIR"),
        ("CANDIDATE_READY", {
            "new_candidate_sha": NEW_SHA, "candidate_pr_number": 120,
            "candidate_head_branch": "candidate", "new_expected_base_branch": "main",
            "new_expected_base_sha": candidate()["expected_base_sha"],
        }, "REVIEW_INTERNAL"),
        ("INTERNAL_PASS", {}, "REQUEST_EXTERNAL_REVIEW"),
    ):
        event = command(q, name, **extra)
        live_sha = extra["new_candidate_sha"] if name == "CANDIDATE_READY" else q["tasks"][0]["candidate"]["candidate_sha"]
        live = candidate(live_sha)
        writes, result = run_event(monkeypatch, q, event, live=live)
        assert len(writes) == 1
        q = writes[0][0]
        assert q["execution_lock"] == original_lock
        assert q["tasks"][1] == other
        assert result["result"] == "WORK"
        assert result["action"] == expected_action
        assert result["run_id"] == RUN_ID
        assert result["candidate"] == q["tasks"][0]["candidate"]


def pending_review(monkeypatch):
    q = interactive_queue(phase="REVIEW")
    for name, extra in (
        ("INTERNAL_PASS", {}),
        ("EXTERNAL_REQUESTED", {"request_ref": "https://github.com/example/repo/pull/120#issuecomment-1"}),
    ):
        writes, result = run_event(monkeypatch, q, command(q, name, **extra), live=candidate())
        q = writes[0][0]
        assert result["result"] == "WORK"
    return q, result


def test_native_review_wait_can_receive_finding_then_repair(monkeypatch):
    original = interactive_queue(phase="REVIEW")["execution_lock"]
    q, result = pending_review(monkeypatch)
    assert q["execution_lock"] == original
    assert result["action"] == "RECONCILE_EXTERNAL_REVIEW"
    writes, result = run_event(monkeypatch, q, command(
        q, "EXTERNAL_FINDING", evidence_ref="https://github.com/example/repo/pull/120#issuecomment-2",
    ), live=candidate())
    assert writes[0][0]["execution_lock"] == original
    assert result["action"] == "REPAIR"


@pytest.mark.parametrize("event_name", ["YIELD", "REVIEW_UNAVAILABLE", "EXTERNAL_PASS"])
def test_wait_exit_and_external_pass_release_native_claim(monkeypatch, event_name):
    q, _ = pending_review(monkeypatch)
    extra = {"evidence_ref": "https://github.com/example/repo/pull/120#issuecomment-2"} if event_name == "EXTERNAL_PASS" else {}
    writes, result = run_event(monkeypatch, q, command(q, event_name, **extra), live=candidate())
    assert len(writes) == 1
    assert writes[0][0]["execution_lock"] is None
    assert result["result"] == ("READY" if event_name == "EXTERNAL_PASS" else "YIELDED")


def test_internal_ready_releases_native_claim(monkeypatch):
    q = interactive_queue(phase="REVIEW", review_policy="INTERNAL")
    writes, result = run_event(monkeypatch, q, command(q, "INTERNAL_PASS"), live=candidate())
    assert writes[0][0]["execution_lock"] is None
    assert result["result"] == "READY"


def test_candidate_drift_releases_native_claim_without_pass(monkeypatch):
    q = interactive_queue(phase="REVIEW")
    writes, result = run_event(monkeypatch, q, command(q, "INTERNAL_PASS"), live=candidate(NEW_SHA))
    assert writes[0][0]["execution_lock"] is None
    assert writes[0][0]["tasks"][0]["phase"] == "REPAIR"
    assert writes[0][0]["tasks"][0]["last_review"] is None
    assert result["result"] == "YIELDED"


def test_lost_event_result_is_recovered_by_read_only_holder_revalidation(monkeypatch):
    q = interactive_queue(phase="REVIEW")
    original_event = command(q, "INTERNAL_REPAIR")
    writes, _lost_result = run_event(monkeypatch, q, original_event, live=candidate())
    committed = writes[0][0]
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    state = {"queue": committed, "runtime_enabled": True, "integration_enabled": False}
    unchanged, result = carrier._tick({"kind": "TICK", "run_id": RUN_ID}, state, now=NOW)
    assert unchanged == state
    assert result["action"] == "REPAIR"
    assert len(writes) == 1
    # Retrying the old EVENT would be unsafe: its WORK action is now stale.
    with pytest.raises(carrier.StaleEventError):
        carrier._event(original_event, state, now=NOW)
    assert len(writes) == 1


def test_native_tick_cannot_acquire_after_yield_or_lease_expiry(monkeypatch):
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    for lock in (None, {**interactive_queue()["execution_lock"],
                        "started_at": "2026-09-08T22:00:00Z", "expires_at": "2026-09-08T23:30:00Z"}):
        q = interactive_queue()
        q["execution_lock"] = lock
        original = deepcopy(q)
        with pytest.raises(carrier.StaleEventError, match="manual TICK requires existing unexpired holder"):
            carrier._tick({"kind": "TICK", "run_id": RUN_ID}, {
                "queue": q, "runtime_enabled": True, "integration_enabled": False,
            }, now=NOW)
        assert q == original


def test_native_event_expiring_at_ref_cas_never_mutates_refs(monkeypatch):
    q = interactive_queue(phase="REVIEW")
    event = command(q, "INTERNAL_REPAIR")
    raw = {key: value for key, value in event.items() if key != "kind"}
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", "CONTROL_V4_RUNTIME_EVENT " + json.dumps(raw))

    class AtExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 9, 1, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(carrier, "datetime", AtExpiry)
    calls = []
    monkeypatch.setattr(carrier, "_request_json", lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(carrier.StaleEventError, match="event lease expired"):
        carrier._update_refs_exact(repository_node_id="NODE", main_oid="a" * 40,
                                   runtime_before_oid="b" * 40, runtime_after_oid="c" * 40,
                                   client_id="expired-native", source_queue=q)
    assert calls == []


@pytest.mark.parametrize("run_id,admitted", [
    (RUN_ID, True), ("v41:gh:39033163807", True),
    ("v41:control-go:0", False), ("v41:control-go:39033163807:extra", False),
])
def test_real_workflow_admission_accepts_only_exact_native_namespace(monkeypatch, tmp_path, run_id, admitted):
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text()
    section = workflow.split("      - name: Reject stale or misbound command before private capability", 1)[1]
    script = section.split("          python3 - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("CONTROL_V4_TICK_MAX_AGE_SECONDS", "120")
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", "CONTROL_V4_RUNTIME_TICK " + json.dumps({"run_id": run_id}))
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND_CREATED_AT", datetime.now(timezone.utc).isoformat())
    exec(compile(textwrap.dedent(script), "workflow-admission", "exec"), {})
    assert output.read_text().strip() == f"admitted={'true' if admitted else 'false'}"
