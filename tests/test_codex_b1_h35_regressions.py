import pytest

from control_engine.codex_b1 import CodexB1Error, REQUEST_MARKER, classify_review_snapshot, request_id

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H35"
REQUEST_COMMENT_ID = 350
REQUEST_AT = "2026-08-23T12:30:00Z"
REVIEW_AT = "2026-08-23T12:37:00Z"


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request(*, updated_at: str | None) -> dict:
    rid = request_id(task_id=TASK_ID, handover_id=HANDOVER_ID, candidate_sha=CANDIDATE)
    item = {
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
    if updated_at is not None:
        item["updated_at"] = updated_at
    return item


def _review() -> dict:
    return {
        "id": 78,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _reaction() -> dict:
    return {"user": _bot(), "content": "+1"}


def _classify(request: dict):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_COMMENT_ID,
        reviews=[_review()],
        review_comments=[],
        trigger_reactions=[_reaction()],
        issue_comments=[request],
    )


def test_edited_exact_trigger_is_rejected_before_old_evidence_can_authorize_pass():
    with pytest.raises(CodexB1Error, match="edited after creation"):
        _classify(_request(updated_at="2026-08-23T12:31:00Z"))


def test_unedited_real_github_trigger_remains_valid():
    result = _classify(_request(updated_at=REQUEST_AT))

    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"


def test_legacy_fixture_without_updated_at_remains_supported():
    result = _classify(_request(updated_at=None))

    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
