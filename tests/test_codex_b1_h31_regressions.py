import pytest

from control_engine.codex_b1 import (
    REQUEST_MARKER,
    CodexB1Error,
    classify_review_snapshot,
    request_id,
)

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H31"
REQUEST_ID = 310
REQUEST_AT = "2026-08-23T11:18:00Z"
REVIEW_AT = "2026-08-23T11:19:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _body(first_line: str) -> str:
    rid = request_id(task_id=TASK_ID, handover_id=HANDOVER_ID, candidate_sha=CANDIDATE)
    return (
        f"{first_line}\n\n"
        f"{REQUEST_MARKER}\n"
        f"request_id={rid}\n"
        f"task_id={TASK_ID}\n"
        f"handover_id={HANDOVER_ID}\n"
        f"candidate_sha={CANDIDATE}\n"
    )


def _request(first_line: str = "@codex review", *, comment_id: int = REQUEST_ID) -> dict:
    return {"id": comment_id, "body": _body(first_line), "created_at": REQUEST_AT}


def _review() -> dict:
    return {
        "id": 1,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _classify(issue_comments: list[dict]) -> object:
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_ID,
        issue_comments=issue_comments,
        reviews=[_review()],
        review_comments=[],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
    )


@pytest.mark.parametrize("first_line", [" @codex review", "@codex review ", "\t@codex review"])
def test_exact_trigger_rejects_whitespace_normalized_activation_line(first_line: str):
    with pytest.raises(CodexB1Error, match="full request identity"):
        _classify([_request(first_line)])


@pytest.mark.parametrize("first_line", [" @codex review", "@codex review "])
def test_whitespace_activation_pseudo_request_does_not_create_duplicate_ambiguity(first_line: str):
    result = _classify([
        _request(),
        _request(first_line, comment_id=410),
    ])
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
