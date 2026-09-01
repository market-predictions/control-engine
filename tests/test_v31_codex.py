from datetime import datetime, timezone

import pytest

from control_engine.codex_v31 import (
    CLEAN_PREFIX,
    CodexEvidenceError,
    INDETERMINATE_MARKER,
    build_request,
    classify,
)


SHA = "a" * 40
TASK = "SUCCESSOR--ASSURANCE--abc"
RUN = "run-123"
CREATED = "2026-09-01T18:00:00Z"
BOT = {"login": "chatgpt-codex-connector[bot]"}


def request():
    return {
        "id": 10,
        "body": build_request(task_id=TASK, run_id=RUN, candidate_sha=SHA, acceptance=["exact candidate is correct"]),
        "created_at": CREATED,
        "updated_at": CREATED,
        "user": {"login": "control-kernel[bot]"},
    }


def decide(*, issue_comments=(), reviews=(), review_comments=(), req=None):
    return classify(
        task_id=TASK,
        run_id=RUN,
        candidate_sha=SHA,
        request=req or request(),
        issue_comments=list(issue_comments),
        reviews=list(reviews),
        review_comments=list(review_comments),
    )


def exact_review(state="COMMENTED"):
    return {
        "id": 50,
        "user": BOT,
        "state": state,
        "commit_id": SHA,
        "submitted_at": "2026-09-01T18:01:00Z",
    }


def finding(body):
    return {
        "id": 51,
        "user": BOT,
        "body": body,
        "commit_id": SHA,
        "pull_request_review_id": 50,
        "created_at": "2026-09-01T18:01:00Z",
        "path": "x.py",
        "line": 7,
    }


def clean(prefix=None, *, login="chatgpt-codex-connector[bot]"):
    reviewed = prefix or SHA[:10]
    return {
        "id": 60,
        "user": {"login": login},
        "body": f"{CLEAN_PREFIX}\n\n**Reviewed commit:** `{reviewed}`",
        "created_at": "2026-09-01T18:02:00Z",
    }


def test_clean_trusted_exact_head_signal_passes():
    decision = decide(issue_comments=[clean()])
    assert (decision.status, decision.verdict) == ("COMPLETE", "PASS")


def test_definite_exact_head_finding_fails_even_if_clean_signal_exists():
    decision = decide(
        issue_comments=[clean()],
        reviews=[exact_review()],
        review_comments=[finding("Material defect")],
    )
    assert decision.verdict == "FAIL"
    assert "x.py:7" in decision.findings[0]


def test_only_explicitly_prefixed_indeterminate_findings_are_indeterminate():
    decision = decide(reviews=[exact_review()], review_comments=[finding(INDETERMINATE_MARKER + " missing evidence")])
    assert decision.verdict == "INDETERMINATE"
    whitespace = decide(reviews=[exact_review()], review_comments=[finding(" " + INDETERMINATE_MARKER + " not a prefix")])
    assert whitespace.verdict == "FAIL"


def test_wrong_head_or_untrusted_clean_signal_never_passes():
    wrong = decide(issue_comments=[clean("b" * 10)])
    assert wrong.status == "EXECUTION_UNAVAILABLE"
    untrusted = decide(issue_comments=[clean(login="market-predictions")])
    assert untrusted.status == "PENDING"


def test_edited_request_and_duplicate_clean_evidence_fail_closed():
    edited = request()
    edited["updated_at"] = "2026-09-01T18:00:01Z"
    with pytest.raises(CodexEvidenceError):
        decide(req=edited)
    duplicate = decide(issue_comments=[clean(), {**clean(), "id": 61, "created_at": "2026-09-01T18:03:00Z"}])
    assert duplicate.status == "EXECUTION_UNAVAILABLE"


def test_changes_requested_is_fail_without_inline_comment():
    decision = decide(reviews=[exact_review("CHANGES_REQUESTED")])
    assert decision.verdict == "FAIL"


def test_stale_terminal_review_fails_closed_and_absent_evidence_stays_pending():
    stale = exact_review()
    stale["commit_id"] = "b" * 40
    assert decide(reviews=[stale]).status == "EXECUTION_UNAVAILABLE"
    assert decide().status == "PENDING"
