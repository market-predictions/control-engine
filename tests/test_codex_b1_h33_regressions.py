from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
STALE = "b" * 40
TASK_ID = "T1"
HANDOVER_ID = "H33"
REQUEST_COMMENT_ID = 330
REQUEST_AT = "2026-08-23T11:30:00Z"
REVIEW_AT = "2026-08-23T11:35:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request() -> dict:
    rid = request_id(task_id=TASK_ID, handover_id=HANDOVER_ID, candidate_sha=CANDIDATE)
    return {
        "id": REQUEST_COMMENT_ID,
        "body": (
            f"@codex review\n\n{REQUEST_MARKER}\n"
            f"request_id={rid}\n"
            f"task_id={TASK_ID}\n"
            f"handover_id={HANDOVER_ID}\n"
            f"candidate_sha={CANDIDATE}\n"
        ),
        "created_at": REQUEST_AT,
    }


def _terminal_review() -> dict:
    return {
        "id": 77,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _clean_reaction() -> dict:
    return {"user": _bot(), "content": "+1"}


def _classify(extra_reviews: list[dict]):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_COMMENT_ID,
        reviews=[_terminal_review(), *extra_reviews],
        review_comments=[],
        trigger_reactions=[_clean_reaction()],
        issue_comments=[_request()],
    )


def test_real_pending_review_without_timestamps_blocks_clean_pass():
    pending = {
        "id": 88,
        "user": _bot(),
        "state": "PENDING",
        "commit_id": CANDIDATE,
        "submitted_at": None,
    }

    result = _classify([pending])

    assert result.status == "PENDING"
    assert result.verdict is None


def test_timestamp_less_pending_review_blocks_even_with_stale_commit_metadata():
    pending = {
        "id": 89,
        "user": _bot(),
        "state": "PENDING",
        "commit_id": STALE,
        "submitted_at": None,
    }

    result = _classify([pending])

    assert result.status == "PENDING"
    assert result.verdict is None


def test_timestamped_pending_review_before_request_does_not_poison_current_pass():
    old_pending = {
        "id": 90,
        "user": _bot(),
        "state": "PENDING",
        "commit_id": CANDIDATE,
        "submitted_at": None,
        "created_at": "2026-08-23T11:20:00Z",
    }

    result = _classify([old_pending])

    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.reviewed_commit == CANDIDATE
