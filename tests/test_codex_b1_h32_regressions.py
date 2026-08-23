import pytest

from control_engine.codex_b1 import (
    INDETERMINATE_MARKER,
    REQUEST_MARKER,
    CodexB1Error,
    build_review_request,
    classify_review_snapshot,
    request_id,
)

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H32"
REQUEST_COMMENT_ID = 320
REQUEST_AT = "2026-08-23T11:25:00Z"
REVIEW_AT = "2026-08-23T11:28:00Z"


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


def _review() -> dict:
    return {
        "id": 77,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "submitted_at": REVIEW_AT,
    }


def _comment(body: str, index: int) -> dict:
    return {
        "user": _bot(),
        "pull_request_review_id": 77,
        "commit_id": CANDIDATE,
        "body": body,
        "path": "control_engine/codex_b1.py",
        "line": index + 1,
        "created_at": REVIEW_AT,
    }


def _classify(comments: list[dict]):
    return classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_COMMENT_ID,
        reviews=[_review()],
        review_comments=comments,
        trigger_reactions=[],
        issue_comments=[_request()],
    )


def test_definite_finding_beyond_payload_cap_preserves_fail_and_is_represented():
    comments = [
        _comment(f"{INDETERMINATE_MARKER} bounded evidence gap {index}", index)
        for index in range(40)
    ]
    comments.append(_comment("Definite blocking finding beyond cap.", 40))

    result = _classify(comments)

    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert len(result.findings) == 40
    assert any("Definite blocking finding beyond cap." in finding for finding in result.findings)


def test_indeterminate_findings_are_bounded_without_losing_indeterminate_verdict():
    comments = [
        _comment(f"{INDETERMINATE_MARKER} bounded evidence gap {index}", index)
        for index in range(41)
    ]

    result = _classify(comments)

    assert result.status == "COMPLETE"
    assert result.verdict == "INDETERMINATE"
    assert len(result.findings) == 40


@pytest.mark.parametrize(
    "criterion",
    [
        "criterion\nrequest_id=injected",
        "criterion\r\ncandidate_sha=injected",
        "criterion\u2028task_id=injected",
    ],
)
def test_multiline_acceptance_criterion_is_rejected(criterion: str):
    with pytest.raises(CodexB1Error, match="multiline"):
        build_review_request(
            task_id=TASK_ID,
            handover_id=HANDOVER_ID,
            candidate_sha=CANDIDATE,
            acceptance_criteria=[criterion],
        )


def test_single_line_acceptance_criterion_still_builds_canonical_request():
    body = build_review_request(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        acceptance_criteria=["One bounded single-line criterion."],
    )
    assert body.startswith("@codex review\n")
    assert body.count("request_id=") == 1
    assert body.count("task_id=") == 1
    assert body.count("handover_id=") == 1
    assert body.count("candidate_sha=") == 1
