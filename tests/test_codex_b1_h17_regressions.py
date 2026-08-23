from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot

CANDIDATE = "a" * 40
SAME_AT = "2026-08-23T00:00:00Z"


def _request(comment_id: int) -> dict:
    return {
        "id": comment_id,
        "body": f"@codex review\n\n{REQUEST_MARKER}\ncandidate_sha={CANDIDATE}\n",
        "created_at": SAME_AT,
    }


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def test_later_same_timestamp_request_fails_closed_against_prior_finding():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        request_comment_id=101,
        issue_comments=[_request(100), _request(101)],
        reviews=[
            {
                "id": 1,
                "user": _bot(),
                "commit_id": CANDIDATE,
                "submitted_at": SAME_AT,
            }
        ],
        review_comments=[
            {
                "user": _bot(),
                "pull_request_review_id": 1,
                "commit_id": CANDIDATE,
                "body": "Earlier same-second blocking finding.",
                "path": "control_engine/codex_b1.py",
                "line": 1,
                "created_at": SAME_AT,
            }
        ],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None
    assert result.findings == ()
