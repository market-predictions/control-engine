from pathlib import Path

from scripts import control_v4_runtime_carrier as carrier


def _source() -> str:
    return Path(carrier.__file__).read_text(encoding="utf-8")


def test_runtime_write_treats_atomic_update_refs_success_as_commit_boundary() -> None:
    source = _source()
    start = source.index("def _write_queue_exact")
    end = source.index("\ndef _assert_public_target_repository", start)
    body = source[start:end]

    assert "_update_refs_exact(" in body
    assert "return {**state" in body
    assert "_await_git_ref_head" not in body
    assert "_git_ref_head" not in body
    assert "mandatory private queue readback failed" not in body
    assert "private authority moved during runtime write" not in body


def test_new_acquisition_has_no_fallible_network_io_or_result_build_after_holder_cas() -> None:
    source = _source()
    start = source.index("def _tick(")
    end = source.index("\ndef _validate_public_ref_for_task", start)
    body = source[start:end]

    cas = 'state = _write_queue_exact(state, acquired, reason=reason)'
    assert cas in body
    before, after = body.split(cas, 1)

    assert "_target_pr_candidate(" in before
    assert "_assert_public_target_repository(" in before
    assert "safe_work_capsule(" in before
    assert "_target_pr_candidate(" not in after
    assert "_assert_public_target_repository(" not in after
    assert "safe_work_capsule(" not in after
    assert "reconcile_review_candidate_drift_v4(" not in after
    assert "_public_get(" not in after
    assert "return state, work_result" in after


def test_semantic_candidate_drift_verification_is_event_side() -> None:
    source = _source()
    tick_start = source.index("def _tick(")
    tick_end = source.index("\ndef _validate_public_ref_for_task", tick_start)
    tick_body = source[tick_start:tick_end]
    event_start = source.index("def _event(")
    event_end = source.index("\ndef _set_outputs", event_start)
    event_body = source[event_start:event_end]

    assert "reconcile_review_candidate_drift_v4(" not in tick_body
    assert "reconcile_review_candidate_drift_v4(" in event_body
    assert "_target_pr_candidate(" in event_body
    assert 'event == "CANDIDATE_READY"' in event_body
