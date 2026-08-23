from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H27"
REQUEST_AT = "2026-08-23T09:58:00Z"
PENDING_AT = "2026-08-23T09:59:00Z"
TERMINAL_AT = "2026-08-23T10:00:00Z"


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


def _classify(*, reviews: list[dict], clean: bool = True):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=200,
        reviews=reviews,
        review_comments=[],
        trigger_reactions=[{"user": _bot(), "content": "+1"}] if clean else [],
        issue_comments=[_request()],
    )


def test_commentless_pending_exact_head_review_blocks_clean_pass():
    result = _classify(reviews=[{
        "id": 1,
        "user": _bot(),
        "state": "PENDING",
        "commit_id": CANDIDATE,
        "created_at": PENDING_AT,
        "submitted_at": None,
    }])
    assert result.status == "PENDING"
    assert result.verdict is None
    assert result.findings == ()


def test_commentless_pending_commitless_review_blocks_clean_pass():
    result = _classify(reviews=[{
        "id": 2,
        "user": _bot(),
        "state": "PENDING",
        "created_at": PENDING_AT,
        "submitted_at": None,
    }])
    assert result.status == "PENDING"
    assert result.verdict is None


def test_terminal_exact_head_review_without_findings_allows_clean_pass():
    result = _classify(reviews=[{
        "id": 3,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": TERMINAL_AT,
    }])
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.reviewed_commit == CANDIDATE
