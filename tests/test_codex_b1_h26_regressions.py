from control_engine.codex_b1 import REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H26"
REQUEST_AT = "2026-08-23T09:50:00Z"
COMMENT_AT = "2026-08-23T09:51:00Z"


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


def _comment(body: str, *, review_id: int = 1) -> dict:
    return {
        "user": _bot(),
        "pull_request_review_id": review_id,
        "commit_id": CANDIDATE,
        "body": body,
        "created_at": COMMENT_AT,
    }


def _classify(*, reviews: list[dict], comments: list[dict], clean: bool = True):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=200,
        reviews=reviews,
        review_comments=comments,
        trigger_reactions=[{"user": _bot(), "content": "+1"}] if clean else [],
        issue_comments=[_request()],
    )


def test_pending_review_comment_cannot_become_fail_or_allow_clean_pass():
    result = _classify(
        reviews=[{
            "id": 1,
            "user": _bot(),
            "state": "PENDING",
            "commit_id": CANDIDATE,
            "created_at": COMMENT_AT,
            "submitted_at": None,
        }],
        comments=[_comment("Draft blocking finding.")],
    )
    assert result.status == "PENDING"
    assert result.verdict is None
    assert result.findings == ()


def test_pending_tagged_comment_cannot_become_indeterminate():
    result = _classify(
        reviews=[{
            "id": 1,
            "user": _bot(),
            "state": "PENDING",
            "commit_id": CANDIDATE,
            "created_at": COMMENT_AT,
            "submitted_at": None,
        }],
        comments=[_comment("CONTROL_B1_INDETERMINATE: draft evidence")],
        clean=False,
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_submitted_terminal_exact_review_allows_finding_to_fail():
    result = _classify(
        reviews=[{
            "id": 1,
            "user": _bot(),
            "state": "COMMENTED",
            "commit_id": CANDIDATE,
            "submitted_at": COMMENT_AT,
        }],
        comments=[_comment("Submitted blocking finding.")],
        clean=False,
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert result.findings


def test_unbound_exact_head_comment_blocks_clean_pass_until_terminal_review_exists():
    result = _classify(
        reviews=[],
        comments=[_comment("Exact-head comment without submitted review.", review_id=99)],
    )
    assert result.status == "PENDING"
    assert result.verdict is None
