"""Review readback must never become semantic acceptance or a second workflow."""
import json

from scripts import control_v4_runtime_carrier as carrier


SHA = "a" * 40
OLD = "b" * 40
BASE = "c" * 40
CANDIDATE = {
    "candidate_sha": SHA,
    "candidate_pr_number": 130,
    "candidate_head_branch": "candidate",
    "expected_base_branch": "main",
    "expected_base_sha": BASE,
}


def summary(*, sha=SHA, status="completed", findings=False, unresolved=False, author="chatgpt-codex-connector[bot]"):
    value = {
        "code_review": {
            "commit_sha": sha,
            "status": status,
            "has_any_findings": findings,
            "has_unresolved_findings": unresolved,
        }
    }
    return {
        "user": {"login": author},
        "body": "<!-- codex-review-state:v1 " + json.dumps(value) + " -->",
    }


def check_run(*, status="completed", conclusion="success"):
    return {"check_runs": [{"status": status, "conclusion": conclusion}]}


def read(monkeypatch, *, comments, checks=None):
    calls = []
    def github_get(path):
        calls.append(path)
        return comments if "/issues/" in path else (checks if checks is not None else check_run())
    monkeypatch.setattr(carrier, "_public_get", github_get)
    result = carrier._read_review_observation("market-predictions/weekly-etf", CANDIDATE, dict(CANDIDATE))
    assert all("/pulls/" not in x for x in calls)  # existing carrier bound live PR first
    assert all("a" * 40 in x or "/issues/130/" in x for x in calls)
    assert result["candidate_sha"] == SHA
    assert result["advisory_only"] is True
    return result


def test_completed_no_findings_and_ci_green(monkeypatch):
    result = read(monkeypatch, comments=[summary()])
    assert result["codex"] == "COMPLETED_NO_FINDINGS"
    assert result["ci"] == "OBSERVED_CHECKS_GREEN"
    assert "verdict" not in result and "authorized" not in result


def test_findings_never_cleared_by_green_ci(monkeypatch):
    result = read(monkeypatch, comments=[summary(findings=True)])
    assert result["codex"] == "COMPLETED_FINDINGS"
    assert result["ci"] == "OBSERVED_CHECKS_GREEN"


def test_inflight_never_treated_as_finished(monkeypatch):
    result = read(monkeypatch, comments=[summary(status="running", findings=None, unresolved=None)],
                  checks=check_run(status="in_progress", conclusion=None))
    assert result["codex"] == "RUNNING"
    assert result["ci"] == "RUNNING"


def test_prior_head_and_spoofed_comments_never_prove_review(monkeypatch):
    result = read(monkeypatch, comments=[
        summary(sha=OLD),
        summary(author="other-user"),
    ])
    assert result["codex"] == "STALE_REVIEW"


def test_changed_candidate_short_circuits_before_all_network(monkeypatch):
    def no_network(_):
        raise AssertionError("must not access review for stale candidate")
    monkeypatch.setattr(carrier, "_public_get", no_network)
    altered = {**CANDIDATE, "candidate_sha": OLD}
    status = carrier._read_review_observation("market-predictions/weekly-etf", CANDIDATE, altered)
    assert status["codex"] == "STALE_CANDIDATE"
    assert status["ci"] == "UNKNOWN"


def test_api_failure_is_non_authoritative_unknown(monkeypatch):
    def error(_):
        raise carrier.CarrierError("GitHub unavailable")
    monkeypatch.setattr(carrier, "_public_get", error)
    status = carrier._read_review_observation("market-predictions/weekly-etf", CANDIDATE, dict(CANDIDATE))
    assert status["codex"] == status["ci"] == "UNKNOWN"


def test_missing_review_is_not_a_pass_and_failed_ci_stays_visible(monkeypatch):
    status = read(monkeypatch, comments=[], checks=check_run(conclusion="failure"))
    assert status["codex"] == "NOT_OBSERVED"
    assert status["ci"] == "OBSERVED_CHECKS_NOT_GREEN"


def test_ambiguous_or_overfull_response_cannot_approve(monkeypatch):
    ambiguous = read(monkeypatch, comments=[summary(), summary()])
    assert ambiguous["codex"] == "UNKNOWN"
    overfull = read(monkeypatch, comments=[summary()] * 100)
    assert overfull["codex"] == "UNKNOWN"


def test_observation_attached_only_to_review_before_atomic_write():
    text = open(carrier.__file__, encoding="utf-8").read()
    tick = text.split("def _tick(", 1)[1].split("def _validate_public_ref_for_task", 1)[0]
    before_cas, after_cas = tick.split('state = _write_queue_exact(state, acquired, reason=reason)', 1)
    assert 'task.get("phase") == "REVIEW"' in before_cas
    assert '_read_review_observation(task["repository"], candidate, observed)' in before_cas
    assert 'work_result["review_observation"] = observation' in before_cas
    assert "_public_get(" not in after_cas
    assert "review_observation" not in after_cas
