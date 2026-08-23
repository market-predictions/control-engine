from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
STALE = "b" * 40
TASK_ID = "T1"
HANDOVER_ID = "H28"
REQUEST_AT = "2026-08-23T10:20:00Z"
TERMINAL_AT = "2026-08-23T10:21:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request() -> dict:
    rid = request_id(task_id=TASK_ID, handover_id=HANDOVER_ID, candidate_sha=CANDIDATE)
    return {
        "id": 200,
        "body": (
            f"@codex review\n\n{REQUEST_MARKER}\n"
            f"request_id={rid}\n"
            f"task_id={TASK_ID}\n"
            f"handover_id={HANDOVER_ID}\n"
            f"candidate_sha={CANDIDATE}\n"
        ),
        "created_at": REQUEST_AT,
    }


def _classify(*, reviews: list[dict]):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=200,
        reviews=reviews,
        review_comments=[],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
        issue_comments=[_request()],
    )


def test_clean_reaction_without_terminal_exact_head_review_stays_pending():
    result = _classify(reviews=[])
    assert result.status == "PENDING"
    assert result.verdict is None
    assert "no terminal exact-head review" in result.summary


def test_clean_reaction_with_only_stale_terminal_review_is_unavailable_not_pass():
    result = _classify(reviews=[{
        "id": 1,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": STALE,
        "submitted_at": TERMINAL_AT,
    }])
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None


def test_clean_reaction_with_terminal_exact_head_review_can_pass():
    result = _classify(reviews=[{
        "id": 2,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": TERMINAL_AT,
    }])
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.reviewed_commit == CANDIDATE
