import pytest

from control_engine.codex_b1 import CodexB1Error, build_review_request
from control_engine.codex_b1_strict import classify_trusted_review_snapshot

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H36"
REQUEST_ID = 360
REQUEST_AT = "2026-08-23T14:40:00Z"
REVIEW_AT = "2026-08-23T14:46:00Z"
ACTUATOR = "market-predictions"
CRITERIA = ["Review the exact current candidate only."]


def _bot() -> dict:
    return {"login": "chatgpt-codex-connector[bot]"}


def _request(*, user: str = ACTUATOR, body: str | None = None, comment_id: int = REQUEST_ID) -> dict:
    return {
        "id": comment_id,
        "user": {"login": user},
        "body": body if body is not None else build_review_request(
            task_id=TASK_ID,
            handover_id=HANDOVER_ID,
            candidate_sha=CANDIDATE,
            acceptance_criteria=CRITERIA,
        ),
        "created_at": REQUEST_AT,
        "updated_at": REQUEST_AT,
    }


def _review() -> dict:
    return {
        "id": 77,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _classify(issue_comments: list[dict]):
    return classify_trusted_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_ID,
        acceptance_criteria=CRITERIA,
        trusted_actuator_login=ACTUATOR,
        reviews=[_review()],
        review_comments=[],
        trigger_reactions=[{"user": _bot(), "content": "+1"}],
        issue_comments=issue_comments,
    )


def test_untrusted_same_candidate_pseudo_request_cannot_poison_ownership():
    rogue = _request(user="untrusted-user", comment_id=100)
    result = _classify([rogue, _request()])

    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.reviewed_commit == CANDIDATE


def test_exact_trigger_must_be_owned_by_trusted_actuator():
    with pytest.raises(CodexB1Error, match="trusted actuator"):
        _classify([_request(user="untrusted-user")])


def test_exact_trigger_must_equal_canonical_request_envelope():
    malformed = (
        "@codex review\n\n"
        "CONTROL_B1_CODEX_DEEP_REQUEST_V1\n"
        "request_id=deadbeef\n"
        f"task_id={TASK_ID}\n"
        f"handover_id={HANDOVER_ID}\n"
        f"candidate_sha={CANDIDATE}\n"
    )
    with pytest.raises(CodexB1Error, match="canonical request envelope"):
        _classify([_request(body=malformed)])
