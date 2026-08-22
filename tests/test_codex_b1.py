import pytest

from control_engine.codex_b1 import (
    INDETERMINATE_MARKER,
    CodexB1Error,
    build_review_request,
    classify_review_snapshot,
    request_id,
)

CANDIDATE = "a" * 40


def bot(login="chatgpt-codex-connector[bot]"):
    return {"login": login}


def review(review_id=1, sha=CANDIDATE):
    return {"id": review_id, "user": bot(), "commit_id": sha, "body": "Codex Review"}


def comment(body, *, review_id=1, sha=CANDIDATE, path="src/x.py", line=7):
    return {
        "user": bot(),
        "pull_request_review_id": review_id,
        "commit_id": sha,
        "body": body,
        "path": path,
        "line": line,
    }


def reaction(content="+1"):
    return {"user": bot(), "content": content}


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


def test_clean_codex_reaction_maps_to_pass():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[],
        trigger_reactions=[reaction()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "PASS"
    assert result.findings == ()


def test_codex_finding_maps_to_fail():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[comment("This branch can bypass the expected-head guard.")],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"
    assert result.findings[0].startswith("src/x.py:7:")


def test_tagged_missing_evidence_maps_to_indeterminate():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[comment(f"{INDETERMINATE_MARKER} required CI evidence is unavailable")],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "INDETERMINATE"


def test_definite_finding_takes_precedence_over_indeterminate():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[review()],
        review_comments=[
            comment(f"{INDETERMINATE_MARKER} one check is unavailable"),
            comment("Candidate expands release authority."),
        ],
        trigger_reactions=[],
    )
    assert result.verdict == "FAIL"


def test_stale_review_never_authorizes_pass():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[review(sha="b" * 40)],
        review_comments=[],
        trigger_reactions=[reaction()],
    )
    assert result.status == "EXECUTION_UNAVAILABLE"
    assert result.verdict is None


def test_processing_reaction_is_pending_not_start_or_pass():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[],
        review_comments=[],
        trigger_reactions=[reaction("eyes")],
    )
    assert result.status == "PENDING"
    assert result.verdict is None


def test_non_codex_actor_is_ignored():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[{"id": 1, "user": {"login": "github-actions[bot]"}, "commit_id": CANDIDATE}],
        review_comments=[],
        trigger_reactions=[{"user": {"login": "github-actions[bot]"}, "content": "+1"}],
    )
    assert result.status == "PENDING"
