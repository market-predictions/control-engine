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
REQUEST_COMMENT_ID = 100
REQUEST_AT = "2026-08-23T00:00:00Z"
CURRENT_AT = "2026-08-23T00:01:00Z"
NEXT_AT = "2026-08-23T00:02:00Z"
LATER_AT = "2026-08-23T00:03:00Z"
OLD_AT = "2026-08-22T23:59:00Z"


def bot(login="chatgpt-codex-connector[bot]"):
    return {"login": login}


def review(review_id=1, sha=CANDIDATE, *, submitted_at=CURRENT_AT):
    return {
        "id": review_id,
        "user": bot(),
        "commit_id": sha,
        "body": "Codex Review",
        "submitted_at": submitted_at,
    }


def comment(body, *, review_id=1, sha=CANDIDATE, path="src/x.py", line=7, created_at=CURRENT_AT):
    return {
        "user": bot(),
        "pull_request_review_id": review_id,
        "commit_id": sha,
        "body": body,
        "path": path,
        "line": line,
        "created_at": created_at,
    }


def reaction(content="+1"):
    return {"user": bot(), "content": content}


def request_comment(
    comment_id=REQUEST_COMMENT_ID,
    *,
    candidate=CANDIDATE,
    created_at=REQUEST_AT,
):
    return {
        "id": comment_id,
        "body": f"@codex review\n\n{REQUEST_MARKER}\ncandidate_sha={candidate}\n",
        "created_at": created_at,
    }


def classify(**kwargs):
    issue_comments = kwargs.pop("issue_comments", [request_comment()])
    return classify_review_snapshot(
        request_comment_id=REQUEST_COMMENT_ID,
        issue_comments=issue_comments,
        **kwargs,
    )


def test_request_is_bounded_exact_identity_and_review_only():
    body = build_review_request(
        task_id="T1",
        handover_id="H1",
        candidate_sha=CANDIDATE,
        acceptance_criteria=["Exact head", "No mutation"],
    )
    assert body.startswith("@codex review\n")
    assert f"candidate_sha={CANDIDATE}" in body
    assert "Do not modify code or PR metadata" in body
    assert request_id(task_id="T1", handover_id="H1", candidate_sha=CANDIDATE) in body


def test_request_rejects_invalid_identity_and_unbounded_criteria():
    with pytest.raises(CodexB1Error):
        build_review_request(task_id="T", handover_id="H", candidate_sha="bad", acceptance_criteria=["x"])
    with pytest.raises(CodexB1Error):
        build_review_request(
            task_id="T",
            handover_id="H",
            candidate_sha=CANDIDATE,
            acceptance_criteria=["x"] * 41,
        )


def test_classification_requires_exact_request_comment_identity():
    with pytest.raises(CodexB1Error, match="absent"):
        classify_review_snapshot(
            candidate_sha=CANDIDATE,
            request_comment_id=REQUEST_COMMENT_ID,
            reviews=[],
            review_comments=[],
            trigger_reactions=[],
            issue_comments=[],
        )
    with pytest.raises(CodexB1Error, match="candidate_sha"):
        classify_review_snapshot(
            candidate_sha=CANDIDATE,
            request_comment_id=REQUEST_COMMENT_ID,
            reviews=[],
            review_comments=[],
            trigger_reactions=[],
            issue_comments=[request_comment(candidate="b" * 40)],
        )


def test_clean_codex_reaction_on_exact_trigger_maps_to_pass():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[],
        trigger_reactions=[reaction()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.findings == ()


def test_historical_clean_issue_comment_cannot_authorize_pass():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[],
        review_comments=[],
        trigger_reactions=[],
        issue_comments=[
            request_comment(),
            {
                "id": 99,
                "user": bot(),
                "body": "Codex Review: Didn't find any major issues",
                "created_at": OLD_AT,
            },
        ],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_unbound_historical_review_comment_cannot_create_finding():
    old = {
        "user": bot(),
        "pull_request_review_id": 99,
        "body": "Old blocking finding with no commit metadata.",
        "path": "src/old.py",
        "line": 3,
        "created_at": CURRENT_AT,
    }
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[],
        review_comments=[old],
        trigger_reactions=[],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_codex_finding_maps_to_fail():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[comment("This branch can bypass the expected-head guard.")],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert result.findings[0].startswith("src/x.py:7:")


def test_tagged_missing_evidence_maps_to_indeterminate():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[comment(f"{INDETERMINATE_MARKER} required CI evidence is unavailable")],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "INDETERMINATE"


def test_definite_finding_takes_precedence_over_indeterminate():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[
            comment(f"{INDETERMINATE_MARKER} one check is unavailable"),
            comment("Candidate expands release authority."),
        ],
        trigger_reactions=[],
    )
    assert result.verdict == "FAIL"


def test_stale_review_never_authorizes_pass_without_current_trigger_reaction():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review(sha="b" * 40)],
        review_comments=[],
        trigger_reactions=[],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None


def test_current_trigger_reaction_is_request_bound_even_with_old_review_history():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review(sha="b" * 40)],
        review_comments=[],
        trigger_reactions=[reaction()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"


def test_prior_same_head_finding_cannot_poison_new_request_clean_pass():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[
            review(review_id=1, submitted_at=OLD_AT),
            review(review_id=2, submitted_at=CURRENT_AT),
        ],
        review_comments=[
            comment("Old blocking finding.", review_id=1, created_at=OLD_AT),
        ],
        trigger_reactions=[reaction()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.findings == ()


def test_later_same_head_finding_cannot_poison_exact_request_clean_pass():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review(review_id=2, submitted_at=LATER_AT)],
        review_comments=[comment("Later request blocking finding.", review_id=2, created_at=LATER_AT)],
        trigger_reactions=[reaction()],
        issue_comments=[
            request_comment(),
            request_comment(101, created_at=NEXT_AT),
        ],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.findings == ()


def test_current_same_head_finding_still_fails_current_request_and_later_is_excluded():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[
            review(review_id=1, submitted_at=CURRENT_AT),
            review(review_id=2, submitted_at=LATER_AT),
        ],
        review_comments=[
            comment("Current blocking finding.", review_id=1, created_at=CURRENT_AT),
            comment("Later blocking finding.", review_id=2, created_at=LATER_AT),
        ],
        trigger_reactions=[],
        issue_comments=[
            request_comment(),
            request_comment(101, created_at=NEXT_AT),
        ],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert len(result.findings) == 1
    assert "Current blocking finding" in result.findings[0]


def test_same_timestamp_adjacent_requests_fail_closed():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[],
        review_comments=[],
        trigger_reactions=[],
        issue_comments=[
            request_comment(),
            request_comment(101, created_at=REQUEST_AT),
        ],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None


def test_timestamp_less_review_evidence_is_not_current_request_evidence():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[review(submitted_at=None)],
        review_comments=[comment("Unscoped finding.", created_at=None)],
        trigger_reactions=[],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_processing_reaction_is_pending_not_start_or_pass():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[],
        review_comments=[],
        trigger_reactions=[reaction("eyes")],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_non_codex_actor_is_ignored():
    result = classify(
        candidate_sha=CANDIDATE,
        reviews=[{
            "id": 1,
            "user": {"login": "github-actions[bot]"},
            "commit_id": CANDIDATE,
            "submitted_at": CURRENT_AT,
        }],
        review_comments=[],
        trigger_reactions=[{"user": {"login": "github-actions[bot]"}, "content": "+1"}],
    )
    assert result.status == "PENDING"
