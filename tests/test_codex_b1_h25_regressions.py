from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
CURRENT_HANDOVER = "H25"
NEXT_HANDOVER = "H26"
CURRENT_AT = "2026-08-23T09:44:00Z"
MALFORMED_AT = "2026-08-23T09:45:00Z"
FINDING_AT = "2026-08-23T09:46:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _valid_request(comment_id: int, handover_id: str, created_at: str) -> dict:
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


def _malformed_candidate_only_request(comment_id: int, created_at: str) -> dict:
    return {
        "id": comment_id,
        "body": (
            f"@codex review\n\n{REQUEST_MARKER}\n"
            f"candidate_sha={CANDIDATE}\n"
        ),
        "created_at": created_at,
    }


def _classify(*, issue_comments: list[dict], reviews: list[dict] | None = None, review_comments: list[dict] | None = None):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=CURRENT_HANDOVER,
        candidate_sha=CANDIDATE,
        request_comment_id=200,
        issue_comments=issue_comments,
        reviews=reviews or [],
        review_comments=review_comments or [],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )


def test_malformed_later_request_cannot_truncate_current_finding_window():
    result = _classify(
        issue_comments=[
            _valid_request(200, CURRENT_HANDOVER, CURRENT_AT),
            _malformed_candidate_only_request(250, MALFORMED_AT),
        ],
        reviews=[{
            "id": 1,
            "user": _bot(),
            "state": "COMMENTED",
            "commit_id": CANDIDATE,
            "submitted_at": FINDING_AT,
        }],
        review_comments=[{
            "user": _bot(),
            "pull_request_review_id": 1,
            "commit_id": CANDIDATE,
            "body": "Current-request finding after malformed pseudo-boundary.",
            "created_at": FINDING_AT,
        }],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert result.findings


def test_second_valid_same_candidate_request_fails_closed_instead_of_truncating():
    result = _classify(
        issue_comments=[
            _valid_request(200, CURRENT_HANDOVER, CURRENT_AT),
            _valid_request(300, NEXT_HANDOVER, MALFORMED_AT),
        ],
        review_comments=[{
            "user": _bot(),
            "commit_id": CANDIDATE,
            "body": "Finding belongs to an ambiguous duplicate candidate request.",
            "created_at": FINDING_AT,
        }],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None
    assert result.findings == ()


def test_malformed_prior_request_does_not_create_false_duplicate_ambiguity():
    result = _classify(
        issue_comments=[
            _malformed_candidate_only_request(100, "2026-08-23T09:43:00Z"),
            _valid_request(200, CURRENT_HANDOVER, CURRENT_AT),
        ],
        reviews=[{
            "id": 1,
            "user": _bot(),
            "state": "COMMENTED",
            "commit_id": CANDIDATE,
            "submitted_at": CURRENT_AT,
        }],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
