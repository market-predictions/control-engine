from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import parse_public_command, safe_work_capsule, select_task_id_v4


NOW = datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
BASE_SHA = "c" * 40
MISSION_BLOB = "d" * 40
AUTHORITY_BLOB = "e" * 40
RUN_ID = "event-boundary-run"


def candidate(sha: str = OLD_SHA) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": 120,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def review_pass(sha: str = OLD_SHA) -> dict:
    return {
        "candidate_sha": sha,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "verdict": "PASS",
        "reviewed_at": "2026-09-09T00:00:00Z",
    }


def task(*, phase: str = "REVIEW", review_policy: str = "EXTERNAL", last_review=None, external_review=None) -> dict:
    return {
        "task_id": "MISSION--M--2026-09-09-r1--G1",
        "mission_id": "M",
        "mission_revision": "2026-09-09-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["private"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": review_policy,
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": phase,
        "candidate": candidate(),
        "last_review": last_review,
        "external_review": external_review,
        "blocker": None,
        "created_at": "2026-09-09T00:00:00Z",
        "updated_at": "2026-09-09T00:00:00Z",
    }


def queue(value: dict) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": {
            "run_id": RUN_ID,
            "task_id": value["task_id"],
            "started_at": "2026-09-09T00:00:00Z",
            "expires_at": "2026-09-09T01:30:00Z",
        },
        "migration_facts": [],
        "tasks": [value],
    }


def event(q: dict, name: str, **extra: object) -> dict:
    current = q["tasks"][0]
    work = safe_work_capsule(q, task_id=current["task_id"], run_id=RUN_ID)
    payload = {
        "run_id": RUN_ID,
        "task_token": work["task_token"],
        "event": name,
        "repository": work["repository"],
        "action": work["action"],
        "candidate": work["candidate"],
        **extra,
    }
    return parse_public_command("CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":")))


def event_text(q: dict, name: str = "YIELD") -> str:
    current = q["tasks"][0]
    work = safe_work_capsule(q, task_id=current["task_id"], run_id=RUN_ID)
    payload = {
        "run_id": RUN_ID,
        "task_token": work["task_token"],
        "event": name,
        "repository": work["repository"],
        "action": work["action"],
        "candidate": work["candidate"],
    }
    return "CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":"))


def run_event(monkeypatch, q: dict, command: dict, *, live: dict | None = None):
    writes: list[tuple[dict, str]] = []

    def fake_write(state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)
    if live is not None:
        monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: deepcopy(live))
    state = {"queue": deepcopy(q), "runtime_enabled": True, "integration_enabled": False}
    _, result = carrier._event(command, state, now=NOW)
    return writes, result


def test_candidate_ready_is_one_atomic_transition_and_release(monkeypatch) -> None:
    q = queue(task(phase="REPAIR"))
    command = event(
        q,
        "CANDIDATE_READY",
        new_candidate_sha=NEW_SHA,
        candidate_pr_number=120,
        candidate_head_branch="candidate",
        new_expected_base_branch="main",
        new_expected_base_sha=BASE_SHA,
    )
    writes, result = run_event(monkeypatch, q, command, live=candidate(NEW_SHA))
    assert len(writes) == 1
    written, reason = writes[0]
    assert reason == "candidate-ready"
    assert written["tasks"][0]["phase"] == "REVIEW"
    assert written["tasks"][0]["candidate"]["candidate_sha"] == NEW_SHA
    assert written["execution_lock"] is None
    assert result["result"] == "YIELDED"
    assert "action" not in result


def test_internal_repair_changes_phase_and_releases(monkeypatch) -> None:
    q = queue(task(phase="REVIEW"))
    command = event(q, "INTERNAL_REPAIR")
    writes, result = run_event(monkeypatch, q, command, live=candidate())
    assert len(writes) == 1
    assert writes[0][0]["tasks"][0]["phase"] == "REPAIR"
    assert writes[0][0]["execution_lock"] is None
    assert result["result"] == "YIELDED"


def test_external_policy_internal_pass_releases_then_fresh_tick_selects_external_request(monkeypatch) -> None:
    q = queue(task(phase="REVIEW", review_policy="EXTERNAL"))
    command = event(q, "INTERNAL_PASS")
    writes, result = run_event(monkeypatch, q, command, live=candidate())
    written = writes[0][0]
    assert result["result"] == "YIELDED"
    assert written["execution_lock"] is None
    assert written["tasks"][0]["phase"] == "REVIEW"
    assert written["tasks"][0]["last_review"]["verdict"] == "PASS"
    assert select_task_id_v4(written, run_id=RUN_ID, yielded_task_tokens=[], integration_enabled=False) == written["tasks"][0]["task_id"]
    reacquired = deepcopy(written)
    reacquired["execution_lock"] = {
        "run_id": RUN_ID,
        "task_id": written["tasks"][0]["task_id"],
        "started_at": "2026-09-09T00:31:00Z",
        "expires_at": "2026-09-09T02:01:00Z",
    }
    work = safe_work_capsule(reacquired, task_id=written["tasks"][0]["task_id"], run_id=RUN_ID)
    assert work["action"] == "REQUEST_EXTERNAL_REVIEW"


def test_external_finding_changes_to_repair_and_releases(monkeypatch) -> None:
    pending = {
        "candidate_sha": OLD_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
        "status": "PENDING",
        "request_ref": "https://github.com/example/repo/pull/120#issuecomment-1",
        "evidence_ref": None,
    }
    q = queue(task(phase="REVIEW", last_review=review_pass(), external_review=pending))
    command = event(q, "EXTERNAL_FINDING", evidence_ref="https://github.com/example/repo/pull/120#issuecomment-2")
    writes, result = run_event(monkeypatch, q, command, live=candidate())
    assert writes[0][0]["tasks"][0]["phase"] == "REPAIR"
    assert writes[0][0]["execution_lock"] is None
    assert result["result"] == "YIELDED"


@pytest.mark.parametrize("event_name", ["YIELD", "REVIEW_UNAVAILABLE"])
def test_existing_release_events_remain_released(monkeypatch, event_name: str) -> None:
    pending = None
    if event_name == "REVIEW_UNAVAILABLE":
        pending = {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
            "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
            "status": "PENDING",
            "request_ref": "https://github.com/example/repo/pull/120#issuecomment-1",
            "evidence_ref": None,
        }
    q = queue(task(phase="REVIEW", last_review=review_pass() if pending else None, external_review=pending))
    command = event(q, event_name)
    writes, result = run_event(monkeypatch, q, command, live=candidate() if event_name == "REVIEW_UNAVAILABLE" else None)
    assert writes[0][0]["execution_lock"] is None
    assert result["result"] == "YIELDED"


def test_ready_producing_internal_pass_returns_ready_without_holder(monkeypatch) -> None:
    q = queue(task(phase="REVIEW", review_policy="INTERNAL"))
    command = event(q, "INTERNAL_PASS")
    writes, result = run_event(monkeypatch, q, command, live=candidate())
    assert writes[0][0]["execution_lock"] is None
    assert writes[0][0]["tasks"][0]["status"] == "READY"
    assert result["result"] == "READY"


def test_review_candidate_drift_during_event_is_atomic_repair_release(monkeypatch) -> None:
    q = queue(task(phase="REVIEW"))
    command = event(q, "INTERNAL_PASS")
    writes, result = run_event(monkeypatch, q, command, live=candidate(NEW_SHA))
    assert len(writes) == 1
    assert writes[0][1] == "candidate-drift-to-repair"
    assert writes[0][0]["tasks"][0]["phase"] == "REPAIR"
    assert writes[0][0]["execution_lock"] is None
    assert result["result"] == "YIELDED"
    assert "action" not in result
    assert "live_candidate" not in result


def test_carrier_event_source_has_no_work_return_path_after_transition() -> None:
    source = open(carrier.__file__, encoding="utf-8").read().split("def _event(", 1)[1].split("def _set_outputs", 1)[0]
    assert "return state, safe_work_capsule" not in source
    assert "return state, _event_result(state, command)" in source


def test_event_expiring_before_ref_cas_is_rejected_without_graphql_mutation(monkeypatch) -> None:
    q = queue(task(phase="REVIEW"))
    raw = event_text(q)
    parsed = parse_public_command(raw)
    bound = carrier.bind_public_event_to_holder(q, parsed)
    carrier.assert_event_identity(q, bound, now=datetime(2026, 9, 9, 1, 29, 59, tzinfo=timezone.utc))
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", raw)
    monkeypatch.setattr(carrier, "_private_headers", lambda: {})

    class AtExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 9, 9, 1, 30, 0, tzinfo=timezone.utc)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(carrier, "datetime", AtExpiry)
    graphql_calls = []

    def fake_request_json(*args, **kwargs):
        graphql_calls.append((args, kwargs))
        raise AssertionError("GraphQL mutation must not be attempted after EVENT lease expiry")

    monkeypatch.setattr(carrier, "_request_json", fake_request_json)
    with pytest.raises(carrier.StaleEventError, match="event lease expired"):
        carrier._update_refs_exact(
            repository_node_id="NODE",
            main_oid="a" * 40,
            runtime_before_oid="b" * 40,
            runtime_after_oid="c" * 40,
            client_id="event-expired",
            source_queue=q,
        )
    assert graphql_calls == []


def test_unexpired_event_passes_ref_cas_fence_and_calls_graphql_once(monkeypatch) -> None:
    q = queue(task(phase="REVIEW"))
    raw = event_text(q)
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", raw)
    monkeypatch.setattr(carrier, "_private_headers", lambda: {})

    class BeforeExpiry(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 9, 9, 1, 29, 59, tzinfo=timezone.utc)
            return value if tz is None else value.astimezone(tz)

    monkeypatch.setattr(carrier, "datetime", BeforeExpiry)
    graphql_calls = []

    def fake_request_json(url, *, headers=None, method="GET", payload=None, allow_404=False):
        graphql_calls.append((url, method, payload))
        assert url == carrier.GRAPHQL
        assert method == "POST"
        return {"data": {"updateRefs": {"clientMutationId": "event-live"}}}

    monkeypatch.setattr(carrier, "_request_json", fake_request_json)
    carrier._update_refs_exact(
        repository_node_id="NODE",
        main_oid="a" * 40,
        runtime_before_oid="b" * 40,
        runtime_after_oid="c" * 40,
        client_id="event-live",
        source_queue=q,
    )
    assert len(graphql_calls) == 1
