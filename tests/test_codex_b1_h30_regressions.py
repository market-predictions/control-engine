import pytest

from control_engine.codex_b1 import (
    REQUEST_MARKER,
    CodexB1Error,
    classify_review_snapshot,
    request_id,
)

CANDIDATE = "a" * 40
WRONG = "b" * 40
TASK_ID = "T1"
HANDOVER_ID = "H30"
REQUEST_ID = 300
REQUEST_AT = "2026-08-23T10:40:00Z"
REVIEW_AT = "2026-08-23T10:41:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request(*, comment_id: int = REQUEST_ID, activation: bool = True, created_at: str = REQUEST_AT) -> dict:
    rid = request_id(task_id=TASK_ID, handover_id=HANDOVER_ID, candidate_sha=CANDIDATE)
    prefix = "@codex review\n\n" if activation else ""
    return {
        "id": comment_id,
        "body": (
            f"{prefix}{REQUEST_MARKER}\n"
            f"request_id={rid}\n"
            f"task_id={TASK_ID}\n"
            f"handover_id={HANDOVER_ID}\n"
            f"candidate_sha={CANDIDATE}\n"
        ),
        "created_at": created_at,
    }


def _terminal_review() -> dict:
    return {
        "id": 1,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _classify(*, issue_comments: list[dict], reviews: list[dict]) -> object:
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_ID,
        issue_comments=issue_comments,
        reviews=reviews,
        review_comments=[],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )


def test_exact_trigger_requires_codex_activation_directive():
    with pytest.raises(CodexB1Error, match="full request identity"):
        _classify(issue_comments=[_request(activation=False)], reviews=[])


def test_non_activation_pseudo_request_does_not_create_duplicate_ambiguity():
    result = _classify(
        issue_comments=[
            _request(),
            _request(comment_id=400, activation=False, created_at="2026-08-23T10:42:00Z"),
        ],
        reviews=[_terminal_review()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"


def test_stale_commit_pending_review_blocks_clean_pass():
    result = _classify(
        issue_comments=[_request()],
        reviews=[
            _terminal_review(),
            {
                "id": 2,
                "user": _bot(),
                "state": "PENDING",
                "commit_id": WRONG,
                "created_at": REVIEW_AT,
                "submitted_at": None,
            },
        ],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_malformed_commit_pending_review_blocks_clean_pass():
    result = _classify(
        issue_comments=[_request()],
        reviews=[
            _terminal_review(),
            {
                "id": 2,
                "user": _bot(),
                "state": "PENDING",
                "commit_id": "malformed",
                "created_at": REVIEW_AT,
                "submitted_at": None,
            },
        ],
    )
    assert result.status == "PENDING"
    assert result.verdict is None
