import json
from pathlib import Path

import pytest

from control_engine.v4_runtime_protocol import parse_public_command
from scripts import control_v4_runtime_carrier as carrier


def _source() -> str:
    return Path(carrier.__file__).read_text(encoding="utf-8")


def test_runtime_carrier_is_owner_main_issue106_only_with_no_scheduler_or_dispatch_surface() -> None:
    text = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text(encoding="utf-8")
    assert "issues: write" in text
    assert "contents: read" in text
    assert "schedule:" not in text
    assert "workflow_dispatch:" not in text
    assert "issue_comment:" in text
    assert "github.event.issue.number == 106" in text
    assert "github.actor == 'market-predictions'" in text


def test_strict_parser_accepts_canonical_multiline_tick_and_event_and_existing_space_framing() -> None:
    run_id = 'v4:6a9a7e0b18b08191876c134d83cfbba2:bdabf8391bbd1a6c:0123456789abcdef0123456789abcdef'
    tick_json = '{"run_id":"' + run_id + '","yielded_task_tokens":[]}'
    event_json = (
        '{"run_id":"' + run_id + '","task_token":"' + ('a' * 64)
        + '","event":"YIELD","repository":"market-predictions/weekly-etf-eu","action":"REPAIR"}'
    )

    assert parse_public_command("CONTROL_V4_RUNTIME_TICK\n" + tick_json)["kind"] == "TICK"
    assert parse_public_command("CONTROL_V4_RUNTIME_TICK " + tick_json)["kind"] == "TICK"
    assert parse_public_command("CONTROL_V4_RUNTIME_EVENT\n" + event_json)["kind"] == "EVENT"
    assert parse_public_command("CONTROL_V4_RUNTIME_EVENT " + event_json)["kind"] == "EVENT"


def test_private_runtime_write_is_one_file_exact_old_ref_cas_with_atomic_cas_as_commit_boundary() -> None:
    text = _source()
    assert 'RUNTIME_BRANCH = "control-runtime-state"' in text
    assert 'QUEUE_PATH = "control/DISPATCH_QUEUE.json"' in text
    assert '"base_tree": parent_tree' in text
    assert '"path": QUEUE_PATH' in text
    assert '"parents": [state["runtime_sha"]]' in text
    assert '"beforeOid": main_oid' in text
    assert '"afterOid": main_oid' in text
    assert '"beforeOid": runtime_before_oid' in text
    assert '"afterOid": runtime_after_oid' in text
    assert '_assert_current_command_fresh_at_ref_cas(source_queue)' in text

    write_start = text.index("def _write_queue_exact")
    write_end = text.index("\ndef _assert_public_target_repository", write_start)
    write_body = text[write_start:write_end]
    assert "_update_refs_exact(" in write_body
    assert "_await_git_ref_head" not in write_body
    assert "mandatory private queue readback failed" not in write_body
    assert "private authority moved during runtime write" not in write_body


def test_tick_has_no_post_acquire_target_network_dependency() -> None:
    text = _source()
    tick_start = text.index("def _tick(")
    tick_end = text.index("\ndef _validate_public_ref_for_task", tick_start)
    tick_body = text[tick_start:tick_end]
    assert 'state = _write_queue_exact(state, acquired, reason="acquire")' in tick_body
    assert "safe_work_capsule(" in tick_body
    assert "_target_pr_candidate(" not in tick_body
    assert "_assert_public_target_repository(" not in tick_body
    assert "reconcile_review_candidate_drift_v4(" not in tick_body


def test_event_keeps_live_target_verification_where_transition_semantics_need_it() -> None:
    text = _source()
    event_start = text.index("def _event(")
    event_end = text.index("\ndef _set_outputs", event_start)
    event_body = text[event_start:event_end]
    assert "_target_pr_candidate(" in event_body
    assert "reconcile_review_candidate_drift_v4(" in event_body
    assert 'event == "CANDIDATE_READY"' in event_body


def test_public_result_transport_never_exposes_private_queue_state() -> None:
    payload = {
        "protocol": "CONTROL_V4_RUNTIME_RESULT_V1",
        "result": "WORK",
        "run_id": "r",
        "task_token": "a" * 64,
        "action": "REPAIR",
        "repository": "market-predictions/weekly-etf-eu",
    }
    text = json.dumps(payload)
    assert "acceptance" not in text
    assert "mission_contract_blob_sha" not in text
    assert "execution_lock" not in text


def test_main_fail_closed_boundary_is_still_explicit() -> None:
    text = _source()
    assert "except StaleWriteError:" in text
    assert '"result": "RETRY"' in text
    assert "except StaleEventError:" in text
    assert '"result": "REJECTED"' in text
    assert "except (RuntimeProtocolError, V4ValidationError, CarrierError):" in text
    assert '"result": "ERROR"' in text
