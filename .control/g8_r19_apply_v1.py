from __future__ import annotations

from pathlib import Path
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {text.count(old)}")
    return text.replace(old, new, 1)


def apply(root: Path) -> None:
    script = root / "scripts/canonical_b1_dual_executor_v1.py"
    tests = root / "tests/test_canonical_b1_dual_executor_v1.py"

    text = script.read_text(encoding="utf-8")
    old = '''    deadline = time.monotonic() + timeout_seconds
    last_summary = "No terminal Codex review evidence is present yet for the current request."
    while time.monotonic() < deadline:
        reviews = _gh_list_all(token, f"/repos/{repository}/pulls/{pr_number}/reviews")
        review_comments = _gh_list_all(token, f"/repos/{repository}/pulls/{pr_number}/comments")
        reactions = _gh_list_all(
            token,
            f"/repos/{repository}/issues/comments/{comment_id}/reactions",
            accept="application/vnd.github+json",
        )
        issue_comments = _gh_list_all(token, f"/repos/{repository}/issues/{pr_number}/comments")
        _validate_deep_snapshot_records(
            reviews=reviews,
            review_comments=review_comments,
            reactions=reactions,
            issue_comments=issue_comments,
            request_comment_id=comment_id,
            trusted_actuator_login=actuator_login,
        )
        decision = classify_trusted_review_snapshot(
            task_id=task["task_id"],
            handover_id=task["handover_id"],
            candidate_sha=candidate_sha,
            request_comment_id=comment_id,
            acceptance_criteria=task["acceptance_criteria"],
            trusted_actuator_login=actuator_login,
            reviews=reviews,
            review_comments=review_comments,
            trigger_reactions=reactions,
            issue_comments=issue_comments,
        )
        last_summary = decision.summary
        if decision.status == "COMPLETE" and decision.verdict is not None:
            return _result(
                task_id=task["task_id"],
                run_id=run_id,
                candidate_sha=candidate_sha,
                outcome=decision.verdict,
                summary=decision.summary,
                findings=list(decision.findings),
                evidence=[
                    "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1: START_PROVEN=true; deterministic_contradictions=[]",
                    f"route=DEEP; request_comment_id={comment_id}; trusted_actuator_login={actuator_login}",
                    f"reviewed_commit={decision.reviewed_commit or ''}",
                ],
            )
        if decision.status == "EXECUTION_UNAVAILABLE":
            raise CanonicalB1Error(decision.summary)
        time.sleep(15)
    raise CanonicalB1Error(f"DEEP terminal evidence timeout: {last_summary}")
'''
    new = '''    def read_snapshot():
        reviews = _gh_list_all(token, f"/repos/{repository}/pulls/{pr_number}/reviews")
        review_comments = _gh_list_all(token, f"/repos/{repository}/pulls/{pr_number}/comments")
        reactions = _gh_list_all(
            token,
            f"/repos/{repository}/issues/comments/{comment_id}/reactions",
            accept="application/vnd.github+json",
        )
        issue_comments = _gh_list_all(token, f"/repos/{repository}/issues/{pr_number}/comments")
        _validate_deep_snapshot_records(
            reviews=reviews,
            review_comments=review_comments,
            reactions=reactions,
            issue_comments=issue_comments,
            request_comment_id=comment_id,
            trusted_actuator_login=actuator_login,
        )
        return reviews, review_comments, reactions, issue_comments

    def classify_snapshot(reviews, review_comments, reactions, issue_comments):
        return classify_trusted_review_snapshot(
            task_id=task["task_id"],
            handover_id=task["handover_id"],
            candidate_sha=candidate_sha,
            request_comment_id=comment_id,
            acceptance_criteria=task["acceptance_criteria"],
            trusted_actuator_login=actuator_login,
            reviews=reviews,
            review_comments=review_comments,
            trigger_reactions=reactions,
            issue_comments=issue_comments,
        )

    deadline = time.monotonic() + timeout_seconds
    last_summary = "No terminal Codex review evidence is present yet for the current request."
    while time.monotonic() < deadline:
        reviews, review_comments, reactions, issue_comments = read_snapshot()
        decision = classify_snapshot(reviews, review_comments, reactions, issue_comments)
        last_summary = decision.summary

        if decision.status == "COMPLETE" and decision.verdict is not None:
            # Terminal completion was observed. Re-read all paginated evidence after that
            # observation so a blocker that became visible during the first sequential
            # collection cannot be hidden behind a fresh terminal review/reaction.
            reviews, review_comments, reactions, issue_comments = read_snapshot()
            decision = classify_snapshot(reviews, review_comments, reactions, issue_comments)
            last_summary = decision.summary

        if decision.status == "EXECUTION_UNAVAILABLE":
            raise CanonicalB1Error(decision.summary)
        if decision.status == "COMPLETE" and decision.verdict is not None:
            return _result(
                task_id=task["task_id"],
                run_id=run_id,
                candidate_sha=candidate_sha,
                outcome=decision.verdict,
                summary=decision.summary,
                findings=list(decision.findings),
                evidence=[
                    "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1: START_PROVEN=true; deterministic_contradictions=[]",
                    f"route=DEEP; request_comment_id={comment_id}; trusted_actuator_login={actuator_login}",
                    f"reviewed_commit={decision.reviewed_commit or ''}",
                ],
            )
        time.sleep(15)
    raise CanonicalB1Error(f"DEEP terminal evidence timeout: {last_summary}")
'''
    text = replace_once(text, old, new, "deep-loop")
    script.write_text(text, encoding="utf-8")

    text = tests.read_text(encoding="utf-8")
    marker = '''\n\n@pytest.mark.parametrize(\n    "malformed",\n'''
    regression = '''\n\ndef test_deep_refetches_paginated_findings_after_observing_completion(monkeypatch):
    monkeypatch.setenv("CONTROL_GITHUB_WRITE_TOKEN", "token")
    request_body = {"value": None}
    request_created_at = "2026-08-25T22:00:00Z"
    review_id = 1777
    review_comment_reads = {"count": 0}

    def fake_gh_json(token, method, path, payload=None, accept=None):
        if method == "POST":
            request_body["value"] = payload["body"]
            return {"id": 1321, "user": {"login": "market-predictions"}}
        if "/pulls/70/reviews?" in path:
            return [{
                "id": review_id,
                "user": {"login": "chatgpt-codex-connector"},
                "state": "COMMENTED",
                "submitted_at": "2026-08-25T22:00:10Z",
                "commit_id": CANDIDATE,
                "body": "Codex terminal exact-head review",
            }]
        if "/pulls/70/comments?" in path:
            review_comment_reads["count"] += 1
            if review_comment_reads["count"] == 1:
                return []
            return [{
                "id": 1888,
                "user": {"login": "chatgpt-codex-connector"},
                "pull_request_review_id": review_id,
                "commit_id": CANDIDATE,
                "body": "P1 BLOCKER VISIBLE ONLY AFTER COMPLETION OBSERVED",
                "created_at": "2026-08-25T22:00:11Z",
                "path": "scripts/canonical_b1_dual_executor_v1.py",
                "line": 568,
            }]
        if "/issues/comments/1321/reactions?" in path:
            return [{
                "id": 1999,
                "content": "+1",
                "user": {"login": "chatgpt-codex-connector[bot]"},
            }]
        if "/issues/70/comments?" in path:
            return [{
                "id": 1321,
                "user": {"login": "market-predictions"},
                "body": request_body["value"],
                "created_at": request_created_at,
                "updated_at": request_created_at,
            }]
        raise AssertionError((method, path))

    monkeypatch.setattr(mod, "_gh_json", fake_gh_json)
    result = mod._deep(
        task=_queue()["tasks"][0],
        run_id=RUN_ID,
        candidate_sha=CANDIDATE,
        repository="market-predictions/control-engine",
        pr_number=70,
        timeout_seconds=1,
    )

    assert review_comment_reads["count"] == 2
    assert result["outcome"] == "FAIL"
    assert any("VISIBLE ONLY AFTER COMPLETION" in finding for finding in result["findings"])
'''
    if marker not in text:
        raise SystemExit("test insertion marker not found")
    text = text.replace(marker, regression + marker, 1)
    tests.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: g8_r19_apply_v1.py <repo-root>")
    apply(Path(sys.argv[1]))
