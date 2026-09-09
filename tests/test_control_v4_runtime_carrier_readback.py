from pathlib import Path

from scripts import control_v4_runtime_carrier as carrier


def test_runtime_write_treats_atomic_update_refs_success_as_commit_boundary() -> None:
    source = Path(carrier.__file__).read_text(encoding="utf-8")
    start = source.index("def _write_queue_exact")
    end = source.index("\ndef _assert_public_target_repository", start)
    body = source[start:end]

    assert "_update_refs_exact(" in body
    assert "return {**state" in body
    assert "_await_git_ref_head" not in body
    assert "_git_ref_head" not in body
    assert "mandatory private queue readback failed" not in body
    assert "private authority moved during runtime write" not in body


def test_tick_is_acquire_to_work_without_post_acquire_target_io() -> None:
    source = Path(carrier.__file__).read_text(encoding="utf-8")
    start = source.index("def _tick(")
    end = source.index("\ndef _validate_public_ref_for_task", start)
    body = source[start:end]

    assert "_write_queue_exact(state, acquired, reason=\"acquire\")" in body
    assert "safe_work_capsule(" in body
    assert "_target_pr_candidate(" not in body
    assert "_assert_public_target_repository(" not in body
    assert "reconcile_review_candidate_drift_v4(" not in body
    assert "unsupported-target-block" not in body


def test_target_candidate_checks_remain_on_semantic_event_boundaries() -> None:
    source = Path(carrier.__file__).read_text(encoding="utf-8")
    start = source.index("def _event(")
    end = source.index("\ndef _set_outputs", start)
    body = source[start:end]

    assert "_target_pr_candidate(" in body
    assert "reconcile_review_candidate_drift_v4(" in body
    assert 'event == "CANDIDATE_READY"' in body
