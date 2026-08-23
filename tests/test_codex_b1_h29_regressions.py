from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
CURRENT_HANDOVER = "H29"
PRIOR_HANDOVER = "H28"
REQUEST_AT = "2026-08-23T10:29:00Z"
PRIOR_AT = "2026-08-23T10:20:00Z"
REVIEW_AT = "2026-08-23T10:32:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request(comment_id: int, handover_id: str, created_at: str) -> dict:
    rid = request_id(task_id=TASK_ID, handover_id=handover_id, candidate_sha=CANDIDATE)
    return {
        "id": comment_id,
        "body": (
            f"@codex review\n\n{REQUEST_MARKER}\n"
            f"request_id={rid}\n"
            f"task_id={TASK_ID}\n"
            f"handover_id={handover_id}\n"
            f"candidate_sha={CANDIDATE}\n"
        ),
        "created_at": created_at,
    }


def _classify(*, issue_comments: list[dict], reviews: list[dict]):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=CURRENT_HANDOVER,
        candidate_sha=CANDIDATE,
        request_comment_id=200,
        issue_comments=issue_comments,
        reviews=reviews,
        review_comments=[],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )


def test_prior_valid_same_candidate_request_makes_delayed_review_ownership_ambiguous():
    result = _classify(
        issue_comments=[
            _request(100, PRIOR_HANDOVER, PRIOR_AT),
            _request(200, CURRENT_HANDOVER, REQUEST_AT),
        ],
        reviews=[{
            "id": 1,
            "user": _bot(),
            "state": "COMMENTED",
            "commit_id": CANDIDATE,
            "submitted_at": REVIEW_AT,
        }],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None
    assert "same candidate" in result.summary


def test_missing_review_state_is_not_terminal_even_with_submitted_at():
    result = _classify(
        issue_comments=[_request(200, CURRENT_HANDOVER, REQUEST_AT)],
        reviews=[{
            "id": 2,
            "user": _bot(),
            "commit_id": CANDIDATE,
            "submitted_at": REVIEW_AT,
        }],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_null_review_state_is_not_terminal_even_with_submitted_at():
    result = _classify(
        issue_comments=[_request(200, CURRENT_HANDOVER, REQUEST_AT)],
        reviews=[{
            "id": 3,
            "user": _bot(),
            "state": None,
            "commit_id": CANDIDATE,
            "submitted_at": REVIEW_AT,
        }],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_explicit_terminal_exact_head_review_and_clean_reaction_can_pass():
    result = _classify(
        issue_comments=[_request(200, CURRENT_HANDOVER, REQUEST_AT)],
        reviews=[{
            "id": 4,
            "user": _bot(),
            "state": "COMMENTED",
            "commit_id": CANDIDATE,
            "submitted_at": REVIEW_AT,
        }],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
