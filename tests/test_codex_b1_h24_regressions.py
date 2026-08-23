from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
CURRENT_HANDOVER = "H24"
PRIOR_HANDOVER = "H23"
NEXT_HANDOVER = "H25"
CURRENT_AT = "2026-08-23T09:18:00Z"
PRIOR_AT = "2026-08-23T09:17:00Z"
NEXT_AT = "2026-08-23T09:19:00Z"


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


def _classify(*, issue_comments: list[dict], reviews: list[dict], review_comments: list[dict]):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=CURRENT_HANDOVER,
        candidate_sha=CANDIDATE,
        request_comment_id=200,
        issue_comments=issue_comments,
        reviews=reviews,
        review_comments=review_comments,
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )


def test_prior_review_with_duplicate_candidate_request_is_ambiguous_not_clean_pass():
    result = _classify(
        issue_comments=[
            _request(100, PRIOR_HANDOVER, PRIOR_AT),
            _request(200, CURRENT_HANDOVER, CURRENT_AT),
        ],
        reviews=[{
            "id": 1,
            "user": _bot(),
            "commit_id": CANDIDATE,
            "submitted_at": CURRENT_AT,
        }],
        review_comments=[],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None
    assert "same candidate" in result.summary


def test_prior_finding_with_duplicate_candidate_request_is_ambiguous_not_clean_pass():
    result = _classify(
        issue_comments=[
            _request(100, PRIOR_HANDOVER, PRIOR_AT),
            _request(200, CURRENT_HANDOVER, CURRENT_AT),
        ],
        reviews=[],
        review_comments=[{
            "user": _bot(),
            "commit_id": CANDIDATE,
            "body": "Prior-request finding with second-level timestamp collision.",
            "created_at": CURRENT_AT,
        }],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None
    assert result.findings == ()


def test_later_duplicate_candidate_request_is_ambiguous_for_current_request():
    result = _classify(
        issue_comments=[
            _request(200, CURRENT_HANDOVER, CURRENT_AT),
            _request(300, NEXT_HANDOVER, NEXT_AT),
        ],
        reviews=[{
            "id": 2,
            "user": _bot(),
            "commit_id": CANDIDATE,
            "submitted_at": NEXT_AT,
        }],
        review_comments=[],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None


def test_first_request_can_accept_same_second_exact_review_when_no_duplicate_candidate_request_exists():
    result = _classify(
        issue_comments=[_request(200, CURRENT_HANDOVER, CURRENT_AT)],
        reviews=[{
            "id": 3,
            "user": _bot(),
            "state": "COMMENTED",
            "commit_id": CANDIDATE,
            "submitted_at": CURRENT_AT,
        }],
        review_comments=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
