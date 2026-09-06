from __future__ import annotations

import json

from scripts.control_v4_runtime_command_compat import EVENT_PREFIX, normalize_runner_command


RUN_ID = "sched11-20260906T152720Z-8b7c91"
TOKEN = "3b583f6ae60b5dc738836ededf4c687e7e2d633b744761173085bd02ddc3e969"
CANDIDATE = {
    "candidate_head_branch": "r2/32-executable-assurance-kernel",
    "candidate_pr_number": 48,
    "candidate_sha": "8ee4f1b9cdfa315cc8886d35bbf8d61eb444bdf2",
    "expected_base_branch": "main",
    "expected_base_sha": "acdc5d5bae018b64aa082ad68c3e94de955e91a3",
}


def nested_review_unavailable(**extra: object) -> str:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "REVIEW_UNAVAILABLE",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate": CANDIDATE,
    }
    payload.update(extra)
    return EVENT_PREFIX + json.dumps(payload, separators=(",", ":"))


def test_observed_review_unavailable_envelope_normalizes_to_existing_holder_schema() -> None:
    normalized = normalize_runner_command(nested_review_unavailable())
    assert normalized.startswith(EVENT_PREFIX)
    payload = json.loads(normalized[len(EVENT_PREFIX):])
    assert payload == {
        "event": "REVIEW_UNAVAILABLE",
        "holder_candidate_sha": CANDIDATE["candidate_sha"],
        "holder_expected_base_branch": CANDIDATE["expected_base_branch"],
        "holder_expected_base_sha": CANDIDATE["expected_base_sha"],
        "run_id": RUN_ID,
        "task_token": TOKEN,
    }


def test_exact_flat_protocol_event_is_unchanged() -> None:
    command = EVENT_PREFIX + json.dumps({
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "REVIEW_UNAVAILABLE",
        "holder_candidate_sha": CANDIDATE["candidate_sha"],
        "holder_expected_base_branch": CANDIDATE["expected_base_branch"],
        "holder_expected_base_sha": CANDIDATE["expected_base_sha"],
    }, separators=(",", ":"))
    assert normalize_runner_command(command) == command


def test_extra_nested_field_is_not_normalized_and_remains_fail_closed_for_carrier() -> None:
    command = nested_review_unavailable(unexpected="value")
    assert normalize_runner_command(command) == command


def test_other_event_is_not_normalized() -> None:
    payload = {
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "EXTERNAL_PASS",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate": CANDIDATE,
    }
    command = EVENT_PREFIX + json.dumps(payload, separators=(",", ":"))
    assert normalize_runner_command(command) == command


def test_malformed_or_incomplete_candidate_is_not_normalized() -> None:
    candidate = dict(CANDIDATE)
    candidate.pop("expected_base_sha")
    payload = {
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "REVIEW_UNAVAILABLE",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate": candidate,
    }
    command = EVENT_PREFIX + json.dumps(payload, separators=(",", ":"))
    assert normalize_runner_command(command) == command
