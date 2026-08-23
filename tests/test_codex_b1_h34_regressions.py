from control_engine.codex_b1 import INDETERMINATE_MARKER, REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H34"
REQUEST_COMMENT_ID = 340
REQUEST_AT = "2026-08-23T12:20:00Z"
REVIEW_AT = "2026-08-23T12:27:00Z"


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


def _review(state: str) -> dict:
    return {
        "id": 77,
        "user": _bot(),
        "state": state,
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _reaction() -> dict:
    return {"user": _bot(), "content": "+1"}


def _comment(body: str) -> dict:
    return {
        "user": _bot(),
        "pull_request_review_id": 77,
        "commit_id": CANDIDATE,
        "body": body,
        "path": "control_engine/codex_b1.py",
        "line": 1,
        "created_at": REVIEW_AT,
    }


def _classify(state: str, comments: list[dict]):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_COMMENT_ID,
        reviews=[_review(state)],
        review_comments=comments,
        trigger_reactions=[_reaction()],
        issue_comments=[_request()],
    )


def test_changes_requested_without_inline_comment_is_fail_not_pass():
    result = _classify("CHANGES_REQUESTED", [])

    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert result.reviewed_commit == CANDIDATE
    assert any("CHANGES_REQUESTED" in finding for finding in result.findings)


def test_changes_requested_takes_precedence_over_indeterminate_inline_comment():
    result = _classify(
        "CHANGES_REQUESTED",
        [_comment(f"{INDETERMINATE_MARKER} reviewer reported an evidence gap")],
    )

    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert any("CHANGES_REQUESTED" in finding for finding in result.findings)


def test_commented_clean_terminal_review_with_reaction_still_passes():
    result = _classify("COMMENTED", [])

    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.reviewed_commit == CANDIDATE
