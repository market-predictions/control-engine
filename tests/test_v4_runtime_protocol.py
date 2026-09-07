from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import (
    RuntimeProtocolError,
    StaleEventError,
    bind_public_event_to_holder,
    candidate_ready_v4,
    compact_public_result,
    external_finding_v4,
    external_unavailable_v4,
    parse_public_command,
    reconcile_review_candidate_drift_v4,
    safe_work_capsule,
    select_task_id_v4,
    task_token,
    yield_holder_v4,
)


NOW = datetime(2026, 9, 6, 8, 30, tzinfo=timezone.utc)
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
BASE_SHA = "c" * 40
MISSION_BLOB = "d" * 40
AUTHORITY_BLOB = "e" * 40


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
        "reviewed_at": "2026-09-06T08:00:00Z",
    }


def external_pending(sha: str = OLD_SHA) -> dict:
    return {
        "candidate_sha": sha,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "request_key": f"G1--{sha}--main--{BASE_SHA}",
        "status": "PENDING",
        "request_ref": "https://github.com/example/repo/pull/120#issuecomment-1",
        "evidence_ref": None,
    }


def external_indeterminate(sha: str = OLD_SHA) -> dict:
    value = external_pending(sha)
    value["status"] = "INDETERMINATE"
    return value


def task(
    task_id: str = "MISSION--M--2026-09-06-r1--G1",
    *,
    status: str = "ACTIVE",
    phase: str | None = "REVIEW",
    review_policy: str = "EXTERNAL",
    candidate_value: dict | None = None,
    last_review: dict | None = None,
    external_review: dict | None = None,
    integration_policy: str = "HOLD_AFTER_PASS",
) -> dict:
    return {
        "task_id": task_id,
        "mission_id": "M",
        "mission_revision": "2026-09-06-r1",
        "mission_contract_blob_sha": MISSION_BLOB,
        "repository_authority_blob_sha": AUTHORITY_BLOB,
        "gap_id": task_id.rsplit("--", 1)[-1],
        "repository": "example/repo",
        "acceptance": ["private acceptance must never enter public transport"],
        "integration_policy": integration_policy,
        "review_policy": review_policy,
        "convergence_required": False,
        "status": status,
        "phase": phase,
        "candidate": candidate_value,
        "last_review": last_review,
        "external_review": external_review,
        "blocker": None,
        "created_at": "2026-09-06T07:00:00Z",
        "updated_at": "2026-09-06T08:00:00Z",
    }


def distinct_task(value: dict, *, mission: str, revision: str, blob: str, gap: str) -> dict:
    result = deepcopy(value)
    result["mission_id"] = mission
    result["mission_revision"] = revision
    result["mission_contract_blob_sha"] = blob
    result["gap_id"] = gap
    return result


def queue(one_task: dict, *, run_id: str = "run-1", locked: bool = True) -> dict:
    lock = None
    if locked:
        lock = {
            "run_id": run_id,
            "task_id": one_task["task_id"],
            "started_at": "2026-09-06T08:00:00Z",
            "expires_at": "2026-09-06T09:30:00Z",
        }
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": lock,
        "migration_facts": [],
        "tasks": [one_task],
    }


def active_external_queue() -> dict:
    return queue(
        task(
            candidate_value=candidate(),
            last_review=review_pass(),
            external_review=external_pending(),
        )
    )


def event_body(q: dict, event: str, **extra: object) -> str:
    current = q["tasks"][0]
    capsule = safe_work_capsule(q, task_id=current["task_id"], run_id="run-1")
    payload = {
        "run_id": "run-1",
        "task_token": capsule["task_token"],
        "event": event,
        "repository": capsule["repository"],
        "action": capsule["action"],
        **({"candidate": capsule["candidate"]} if "candidate" in capsule else {}),
        **extra,
    }
    return "CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":"))


def test_public_protocol_rejects_generic_queue_patch_raw_task_id_duplicate_keys_and_legacy_flat_event() -> None:
    with pytest.raises(RuntimeProtocolError):
        parse_public_command('CONTROL_V4_RUNTIME_PATCH_QUEUE {"queue":{}}')
    with pytest.raises(RuntimeProtocolError):
        parse_public_command('CONTROL_V4_RUNTIME_EVENT {"run_id":"r","task_id":"PRIVATE","task_token":"' + "a" * 64 + '","event":"YIELD"}')
    with pytest.raises(RuntimeProtocolError):
        parse_public_command('CONTROL_V4_RUNTIME_TICK {"run_id":"a","run_id":"b"}')
    with pytest.raises(RuntimeProtocolError):
        parse_public_command(
            'CONTROL_V4_RUNTIME_EVENT {"run_id":"r","task_token":"' + "a" * 64 +
            '","event":"YIELD","holder_candidate_sha":"' + OLD_SHA +
            '","holder_expected_base_branch":"main","holder_expected_base_sha":"' + BASE_SHA + '"}'
        )


def test_tick_uses_only_opaque_yield_tokens() -> None:
    first = task("MISSION--M--2026-09-06-r1--G1", candidate_value=candidate(), last_review=review_pass(), external_review=external_pending())
    second = task("MISSION--M--2026-09-06-r1--G2", candidate_value=candidate(), last_review=review_pass(), external_review=external_pending())
    second = distinct_task(second, mission="M2", revision="2026-09-06-r2", blob="f" * 40, gap="G2")
    q = {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": [first, second],
    }
    first_token = task_token(first, "cycle-1")
    selected = select_task_id_v4(q, run_id="cycle-1", yielded_task_tokens=[first_token], integration_enabled=False)
    assert selected == second["task_id"]
    command = parse_public_command(
        "CONTROL_V4_RUNTIME_TICK " + json.dumps({"run_id": "cycle-1", "yielded_task_tokens": [first_token]})
    )
    assert "task_id" not in command


def test_safe_capsule_leaks_no_private_queue_mission_or_acceptance_content() -> None:
    q = active_external_queue()
    private_task_id = q["tasks"][0]["task_id"]
    capsule = safe_work_capsule(q, task_id=private_task_id, run_id="run-1")
    encoded = compact_public_result(capsule)
    assert capsule["action"] == "RECONCILE_EXTERNAL_REVIEW"
    assert capsule["task_token"] == task_token(q["tasks"][0], "run-1")
    assert private_task_id not in encoded
    assert "private acceptance" not in encoded
    for forbidden in (
        "acceptance",
        "mission_contract_blob_sha",
        "repository_authority_blob_sha",
        "last_review",
        "external_review",
        "execution_lock",
        "lock_expires_at",
    ):
        assert forbidden not in encoded
    assert q["execution_lock"]["expires_at"] not in encoded


def test_canonical_event_echoes_work_identity_and_binds_to_internal_holder() -> None:
    q = active_external_queue()
    parsed = parse_public_command(event_body(q, "REVIEW_UNAVAILABLE"))
    assert parsed["repository"] == "example/repo"
    assert parsed["action"] == "RECONCILE_EXTERNAL_REVIEW"
    assert parsed["candidate"] == candidate()

    bound = bind_public_event_to_holder(q, parsed)
    assert "repository" not in bound
    assert "action" not in bound
    assert "candidate" not in bound
    assert bound["task_id"] == q["tasks"][0]["task_id"]
    assert bound["holder_candidate_sha"] == OLD_SHA
    assert bound["holder_expected_base_branch"] == "main"
    assert bound["holder_expected_base_sha"] == BASE_SHA


def test_candidate_less_work_yield_uses_same_canonical_event_without_candidate() -> None:
    q = queue(
        task(
            status="ACTIVE",
            phase="BUILD",
            review_policy="INTERNAL",
            candidate_value=None,
            last_review=None,
            external_review=None,
        )
    )
    body = event_body(q, "YIELD")
    payload = json.loads(body.split(" ", 1)[1])
    assert payload["action"] == "BUILD"
    assert "candidate" not in payload
    parsed = parse_public_command(body)
    bound = bind_public_event_to_holder(q, parsed)
    assert "holder_candidate_sha" not in bound
    updated = yield_holder_v4(q, bound, now=NOW)
    assert updated["execution_lock"] is None


def test_canonical_event_fails_closed_on_work_identity_mismatch_or_extra_field() -> None:
    q = active_external_queue()
    for mutation in (
        {"repository": "example/other"},
        {"action": "REQUEST_EXTERNAL_REVIEW"},
        {"candidate": candidate(NEW_SHA)},
    ):
        parsed = parse_public_command(event_body(q, "REVIEW_UNAVAILABLE"))
        parsed.update(mutation)
        with pytest.raises(StaleEventError):
            bind_public_event_to_holder(q, parsed)

    body = event_body(q, "REVIEW_UNAVAILABLE")
    payload = json.loads(body.split(" ", 1)[1])
    payload["unexpected"] = "value"
    with pytest.raises(RuntimeProtocolError):
        parse_public_command("CONTROL_V4_RUNTIME_EVENT " + json.dumps(payload, separators=(",", ":")))


def test_carrier_review_pass_events_recheck_live_candidate_before_applying_pass(monkeypatch) -> None:
    for event, extra, seeded in (
        ("INTERNAL_PASS", {}, queue(task(candidate_value=candidate(), last_review=None, external_review=None))),
        (
            "EXTERNAL_PASS",
            {"evidence_ref": "https://github.com/example/repo/pull/120#issuecomment-2"},
            active_external_queue(),
        ),
    ):
        state = {"queue": seeded, "runtime_enabled": True, "integration_enabled": False}
        parsed = parse_public_command(event_body(seeded, event, **extra))
        writes = []

        def fake_write(current_state, next_queue, *, reason):
            writes.append((deepcopy(next_queue), reason))
            return {**current_state, "queue": deepcopy(next_queue)}

        monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: candidate(NEW_SHA))
        monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)

        _, result = carrier._event(parsed, state, now=NOW)

        assert writes == [(writes[0][0], "candidate-drift-to-repair")]
        current = writes[0][0]["tasks"][0]
        assert current["phase"] == "REPAIR"
        assert current["candidate"]["candidate_sha"] == OLD_SHA
        if event == "INTERNAL_PASS":
            assert current["last_review"] is None
        else:
            assert current["external_review"]["status"] == "PENDING"
        assert result["action"] == "REPAIR"
        assert result["live_candidate"]["candidate_sha"] == NEW_SHA


def test_weeu_shape_candidate_drift_requires_no_external_review_and_goes_to_same_task_repair() -> None:
    q = active_external_queue()
    private_task_id = q["tasks"][0]["task_id"]
    live = {
        "candidate_sha": NEW_SHA,
        "candidate_pr_number": 120,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }
    repaired, drifted = reconcile_review_candidate_drift_v4(
        q,
        task_id=private_task_id,
        run_id="run-1",
        live_candidate=live,
        now=NOW,
    )
    assert drifted is True
    assert repaired["tasks"][0]["task_id"] == private_task_id
    assert repaired["tasks"][0]["phase"] == "REPAIR"
    assert repaired["tasks"][0]["candidate"]["candidate_sha"] == OLD_SHA
    assert repaired["execution_lock"]["run_id"] == "run-1"
    capsule = safe_work_capsule(repaired, task_id=private_task_id, run_id="run-1", live_candidate=live)
    assert capsule["action"] == "REPAIR"
    assert capsule["candidate"]["candidate_sha"] == OLD_SHA
    assert capsule["live_candidate"]["candidate_sha"] == NEW_SHA
    assert private_task_id not in compact_public_result(capsule)


def test_review_unavailable_is_retryable_releases_lock_and_replay_fails_closed() -> None:
    q = active_external_queue()
    parsed = parse_public_command(event_body(q, "REVIEW_UNAVAILABLE"))
    bound = bind_public_event_to_holder(q, parsed)
    updated = external_unavailable_v4(q, bound, now=NOW)
    assert updated["tasks"][0]["status"] == "ACTIVE"
    assert updated["tasks"][0]["phase"] == "REVIEW"
    assert updated["tasks"][0]["external_review"]["status"] == "INDETERMINATE"
    assert updated["execution_lock"] is None
    rebound = bind_public_event_to_holder(updated, parsed)
    with pytest.raises(StaleEventError):
        yield_holder_v4(updated, rebound, now=NOW)


def test_indeterminate_external_wait_is_demoted_below_productive_active_and_queued_work() -> None:
    waiting = task(
        "MISSION--M--2026-09-06-r1--WAIT",
        candidate_value=candidate(),
        last_review=review_pass(),
        external_review=external_indeterminate(),
    )
    productive = distinct_task(
        task(
            "MISSION--M2--2026-09-06-r2--REVIEW",
            review_policy="INTERNAL",
            candidate_value=candidate(),
            last_review=None,
            external_review=None,
        ),
        mission="M2",
        revision="2026-09-06-r2",
        blob="f" * 40,
        gap="REVIEW",
    )
    queued = distinct_task(
        task(
            "MISSION--M3--2026-09-06-r3--BUILD",
            status="QUEUED",
            phase="BUILD",
            review_policy="INTERNAL",
            candidate_value=None,
            last_review=None,
            external_review=None,
        ),
        mission="M3",
        revision="2026-09-06-r3",
        blob="1" * 40,
        gap="BUILD",
    )

    def unlocked(tasks: list[dict]) -> dict:
        return {
            "version": "4.0",
            "principal_manual_relay_count": 0,
            "execution_lock": None,
            "migration_facts": [],
            "tasks": tasks,
        }

    assert select_task_id_v4(unlocked([waiting, productive, queued]), run_id="fair-1", integration_enabled=False) == productive["task_id"]
    assert select_task_id_v4(unlocked([waiting, queued]), run_id="fair-2", integration_enabled=False) == queued["task_id"]
    assert select_task_id_v4(unlocked([waiting]), run_id="fair-3", integration_enabled=False) == waiting["task_id"]


def test_actionable_external_finding_returns_same_stable_task_to_repair_with_lock() -> None:
    q = active_external_queue()
    parsed = parse_public_command(
        event_body(q, "EXTERNAL_FINDING", evidence_ref="https://github.com/example/repo/pull/120#issuecomment-2")
    )
    bound = bind_public_event_to_holder(q, parsed)
    updated = external_finding_v4(q, bound, now=NOW)
    assert updated["tasks"][0]["task_id"] == q["tasks"][0]["task_id"]
    assert updated["tasks"][0]["phase"] == "REPAIR"
    assert updated["tasks"][0]["external_review"]["status"] == "FAIL"
    assert updated["execution_lock"]["run_id"] == "run-1"


def test_candidate_ready_requires_verified_exact_live_identity_and_clears_stale_reviews() -> None:
    q = active_external_queue()
    q["tasks"][0]["phase"] = "REPAIR"
    parsed = parse_public_command(
        event_body(
            q,
            "CANDIDATE_READY",
            new_candidate_sha=NEW_SHA,
            candidate_pr_number=120,
            candidate_head_branch="candidate",
            new_expected_base_branch="main",
            new_expected_base_sha=BASE_SHA,
        )
    )
    bound = bind_public_event_to_holder(q, parsed)
    verified = candidate(NEW_SHA)
    updated = candidate_ready_v4(q, bound, verified_candidate=verified, now=NOW)
    current = updated["tasks"][0]
    assert current["phase"] == "REVIEW"
    assert current["candidate"]["candidate_sha"] == NEW_SHA
    assert current["last_review"] is None
    assert current["external_review"] is None
    assert updated["execution_lock"]["run_id"] == "run-1"

    wrong = deepcopy(verified)
    wrong["candidate_sha"] = "9" * 40
    with pytest.raises(StaleEventError):
        candidate_ready_v4(q, bound, verified_candidate=wrong, now=NOW)


def test_integration_disabled_skips_active_integrate_and_ready_auto() -> None:
    integrate = task(
        "MISSION--M--2026-09-06-r1--G1",
        status="ACTIVE",
        phase="INTEGRATE",
        review_policy="INTERNAL",
        candidate_value=candidate(),
        last_review=review_pass(),
        external_review=None,
        integration_policy="AUTO_AFTER_PASS",
    )
    ready = distinct_task(
        task(
            "MISSION--M2--2026-09-06-r2--G2",
            status="READY",
            phase=None,
            review_policy="INTERNAL",
            candidate_value=candidate(),
            last_review=review_pass(),
            external_review=None,
            integration_policy="AUTO_AFTER_PASS",
        ),
        mission="M2",
        revision="2026-09-06-r2",
        blob="f" * 40,
        gap="G2",
    )
    queued = distinct_task(
        task(
            "MISSION--M3--2026-09-06-r3--G3",
            status="QUEUED",
            phase="BUILD",
            review_policy="INTERNAL",
            candidate_value=None,
            last_review=None,
            external_review=None,
        ),
        mission="M3",
        revision="2026-09-06-r3",
        blob="1" * 40,
        gap="G3",
    )
    q = {"version": "4.0", "principal_manual_relay_count": 0, "execution_lock": None, "migration_facts": [], "tasks": [integrate, ready, queued]}
    assert select_task_id_v4(q, run_id="r", integration_enabled=False) == queued["task_id"]
