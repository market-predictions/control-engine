from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
WRONG = "b" * 40
REQUEST_AT = "2026-08-23T00:00:00Z"
REVIEW_AT = "2026-08-23T00:01:00Z"
TASK_ID = "T1"
HANDOVER_ID = "H1"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request() -> dict:
    rid = request_id(task_id=TASK_ID, handover_id=HANDOVER_ID, candidate_sha=CANDIDATE)
    return {
        "id": 100,
        "body": (
            f"@codex review\n\n{REQUEST_MARKER}\n"
            f"request_id={rid}\n"
            f"task_id={TASK_ID}\n"
            f"handover_id={HANDOVER_ID}\n"
            f"candidate_sha={CANDIDATE}\n"
        ),
        "created_at": REQUEST_AT,
    }


def test_explicit_wrong_head_comment_cannot_bind_through_exact_review_id():
    result = classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=100,
        issue_comments=[_request()],
        reviews=[
            {
                "id": 1,
                "user": _bot(),
                "commit_id": CANDIDATE,
                "submitted_at": REVIEW_AT,
            }
        ],
        review_comments=[
            {
                "user": _bot(),
                "pull_request_review_id": 1,
                "commit_id": WRONG,
                "body": "Wrong-head blocking finding.",
                "path": "control_engine/codex_b1.py",
                "line": 1,
                "created_at": REVIEW_AT,
            }
        ],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.findings == ()


def test_commitless_comment_can_still_bind_through_exact_review_id():
    result = classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=100,
        issue_comments=[_request()],
        reviews=[
            {
                "id": 1,
                "user": _bot(),
                "commit_id": CANDIDATE,
                "submitted_at": REVIEW_AT,
            }
        ],
        review_comments=[
            {
                "user": _bot(),
                "pull_request_review_id": 1,
                "body": "Current blocking finding without comment SHA.",
                "path": "control_engine/codex_b1.py",
                "line": 1,
                "created_at": REVIEW_AT,
            }
        ],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
