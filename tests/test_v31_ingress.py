import json

import pytest

from control_engine.ingress_v31 import IngressError, MARKER, parse_a1_command


def body(payload):
    return MARKER + "\n" + json.dumps(payload)


def test_claim_has_exact_bounded_shape():
    command = parse_a1_command(body({"command": "CLAIM", "task_id": "TASK-1"}))
    assert command.command == "CLAIM"
    assert command.task_id == "TASK-1"
    assert command.run_id is None


def test_record_accepts_result_object_but_no_role_or_worker_authority_fields():
    command = parse_a1_command(
        body({"command": "RECORD", "task_id": "TASK-1", "run_id": "run-1", "result": {"outcome": "COMPLETED"}})
    )
    assert command.result == {"outcome": "COMPLETED"}
    with pytest.raises(IngressError):
        parse_a1_command(
            body(
                {
                    "command": "RECORD",
                    "task_id": "TASK-1",
                    "run_id": "run-1",
                    "result": {"outcome": "COMPLETED"},
                    "role": "governance_release_assurance",
                }
            )
        )


def test_release_is_fail_closed_to_two_existing_reasons():
    command = parse_a1_command(
        body({"command": "RELEASE", "task_id": "TASK-1", "run_id": "run-1", "reason": "EXECUTION_UNAVAILABLE"})
    )
    assert command.reason == "EXECUTION_UNAVAILABLE"
    with pytest.raises(IngressError):
        parse_a1_command(body({"command": "RELEASE", "task_id": "TASK-1", "run_id": "run-1", "reason": "RETRY"}))


def test_codex_start_contains_only_task_identity():
    command = parse_a1_command(body({"command": "CODEX_START", "task_id": "TASK-B"}))
    assert command.command == "CODEX_START"
    assert command.task_id == "TASK-B"
    with pytest.raises(IngressError):
        parse_a1_command(body({"command": "CODEX_START", "task_id": "TASK-B", "verdict": "PASS"}))


def test_malformed_marker_json_extra_fields_and_multiline_identity_fail_closed():
    bad = [
        "WRONG\n{}",
        MARKER + "\nnot-json",
        body({"command": "CLAIM", "task_id": "TASK-1", "worker": "A1"}),
        body({"command": "CLAIM", "task_id": "TASK\n1"}),
    ]
    for value in bad:
        with pytest.raises(IngressError):
            parse_a1_command(value)
