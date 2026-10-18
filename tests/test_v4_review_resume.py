"""Delayed reviews may reach READY, never acquire work or bypass review/CI."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from control_engine.v4_authority_io import V4AuthorityBundle
from scripts import control_v4_owner_admin as admin
from scripts import control_v4_review_resume as resume


REPO = "market-predictions/weekly-etf"
HEAD, BASE = "c" * 40, "d" * 40
NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
CHECKS = ["assurance-contract", "validate-product-boundary"]


@pytest.fixture
def case(monkeypatch):
    candidate = dict(candidate_sha=HEAD, candidate_pr_number=131,
        candidate_head_branch="control/feature", expected_base_branch="main", expected_base_sha=BASE)
    mission = dict(protocol_id="MISSION_CONTRACT_V4", mission_id="M", mission_revision="2026-10-18-r1",
        repository=REPO, desired_outcome="Deliver a real authorized change.",
        gaps=[dict(gap_id="G1", gap_state="OPEN", depends_on=[], repository=REPO,
            acceptance=["Useful change verified"], integration_policy="HOLD_AFTER_PASS", review_policy="EXTERNAL")],
        authority_boundaries=["No automatic integration"], principal_manual_relay_count=0)
    authority = dict(protocol_id="CONTROL_REPOSITORY_AUTHORITY_V4", repository=REPO,
        required_check_runs=CHECKS.copy(), principal_manual_relay_count=0)
    internal = dict(candidate_sha=HEAD, expected_base_branch="main", expected_base_sha=BASE,
        verdict="PASS", reviewed_at="2026-10-18T10:00:00Z")
    request_ref = f"https://github.com/{REPO}/pull/131#issuecomment-100"
    external = dict(candidate_sha=HEAD, expected_base_branch="main", expected_base_sha=BASE,
        request_key=f"G1--{HEAD}--main--{BASE}", status="PENDING", request_ref=request_ref, evidence_ref=None)
    task = dict(task_id="MISSION--M--2026-10-18-r1--G1", mission_id="M", mission_revision="2026-10-18-r1",
        mission_contract_blob_sha="a" * 40, repository_authority_blob_sha="b" * 40, gap_id="G1",
        repository=REPO, acceptance=["Useful change verified"], integration_policy="HOLD_AFTER_PASS",
        review_policy="EXTERNAL", convergence_required=False, status="ACTIVE", phase="REVIEW",
        candidate=candidate, last_review=internal, external_review=external, blocker=None,
        created_at="2026-10-18T09:00:00Z", updated_at="2026-10-18T10:01:00Z")
    queue = dict(version="4.0", principal_manual_relay_count=0, execution_lock=None, migration_facts=[], tasks=[task])
    bundle = V4AuthorityBundle((mission,), (authority,), {"M": "a" * 40}, {REPO: "b" * 40})
    state = dict(queue=queue, bundle=bundle, main_sha="1" * 40, runtime_sha="2" * 40,
        repository_node_id="R_1", queue_blob="3" * 40)
    bot = dict(login="chatgpt-codex-connector[bot]", id=199175422)
    request = dict(id=100, user=dict(login="market-predictions", id=267922695),
        issue_url=f"https://api.github.com/repos/{REPO}/issues/131", html_url=request_ref,
        created_at="2026-10-18T10:01:00Z", updated_at="2026-10-18T10:01:00Z",
        body=f"CONTROL_V4_EXTERNAL_REVIEW_REQUEST {HEAD} {BASE} M@2026-10-18-r1 G1 @codex review")
    passed = dict(id=101, user=bot,
        issue_url=f"https://api.github.com/repos/{REPO}/issues/131",
        html_url=f"https://github.com/{REPO}/pull/131#issuecomment-101",
        created_at="2026-10-18T10:07:00Z", updated_at="2026-10-18T10:07:00Z",
        body=f"Codex Review: Didn't find any major issues.\n**Reviewed commit:** `{HEAD[:10]}`")
    runs = [dict(id=i + 1, name=name, head_sha=HEAD, status="completed", conclusion="success",
        completed_at="2026-10-18T10:05:00Z", app=dict(id=15368, slug="github-actions"))
        for i, name in enumerate(CHECKS)]
    pr = dict(number=131, head=dict(sha=HEAD, ref="control/feature"), base=dict(sha=BASE, ref="main"),
        state="open", merged_at=None, mergeable=True, draft=False)
    routes = {
        f"repos/{REPO}": dict(full_name=REPO, private=False),
        f"repos/{REPO}/pulls/131": pr,
        f"repos/{REPO}/branches/main": dict(commit=dict(sha=BASE)),
        f"repos/{REPO}/issues/comments/100": request,
        f"repos/{REPO}/issues/comments/101": passed,
        f"repos/{REPO}/issues/131/comments?per_page=100": [request, passed],
        f"repos/{REPO}/pulls/131/reviews?per_page=100": [],
        f"repos/{REPO}/pulls/131/comments?per_page=100": [],
        f"repos/{REPO}/commits/{HEAD}/check-runs?filter=latest&per_page=100": dict(total_count=len(runs), check_runs=runs),
    }
    monkeypatch.setattr(admin, "_public_get", lambda path: deepcopy(routes[path]))
    return state, task, routes, request, passed, runs, pr


def evidence(case):
    state, task, *_ = case
    return resume.completion_evidence(state, task)


def test_delayed_exact_review_and_required_ci_reach_ready_without_claim(case):
    state, task, *_ = case
    original = deepcopy(state["queue"])
    result = resume.finish_review(state, task, evidence(case), now=NOW)
    assert state["queue"] == original
    assert result["execution_lock"] is None
    assert result["principal_manual_relay_count"] == 0
    assert result["tasks"][0]["status"] == "READY"
    assert result["tasks"][0]["external_review"]["status"] == "PASS"
    assert result["tasks"][0]["last_review"] == task["last_review"]
    assert not resume.eligible(result["tasks"][0])


@pytest.mark.parametrize("change", ["empty", "missing", "red", "running", "wrong_head", "wrong_app", "duplicate", "truncated"])
def test_required_ci_cannot_be_inferred_or_weakened(case, change):
    state, task, routes, request, passed, runs, pr = case
    checks = routes[f"repos/{REPO}/commits/{HEAD}/check-runs?filter=latest&per_page=100"]
    if change == "empty": state["bundle"].authorities[0]["required_check_runs"] = []
    elif change == "missing": runs.pop(); checks["total_count"] = len(runs)
    elif change == "red": runs[0]["conclusion"] = "failure"
    elif change == "running": runs[0]["status"] = "in_progress"
    elif change == "wrong_head": runs[0]["head_sha"] = "e" * 40
    elif change == "wrong_app": runs[0]["app"]["id"] = 99
    elif change == "duplicate": runs.append(deepcopy(runs[0])); checks["total_count"] = len(runs)
    elif change == "truncated": checks["total_count"] = 101
    with pytest.raises(admin.OwnerAdminError): evidence(case)


@pytest.mark.parametrize("change", ["wrong_head", "wrong_base", "draft", "closed", "merged", "unmergeable"])
def test_target_drift_and_terminal_pr_never_pass(case, change):
    *_, pr = case
    if change == "wrong_head": pr["head"]["sha"] = "e" * 40
    elif change == "wrong_base": pr["base"]["sha"] = "f" * 40
    elif change == "draft": pr["draft"] = True
    elif change == "closed": pr["state"] = "closed"
    elif change == "merged": pr["merged_at"] = "2026-10-18T11:00:00Z"
    elif change == "unmergeable": pr["mergeable"] = None
    with pytest.raises(admin.OwnerAdminError): evidence(case)


@pytest.mark.parametrize("change", ["spoof", "edited_pass", "old_head", "prior_pass", "edited_request", "wrong_request", "internal_missing"])
def test_review_provenance_and_freshness_are_binding(case, change):
    state, task, routes, request, passed, runs, pr = case
    if change == "spoof": passed["user"]["id"] = 99
    elif change == "edited_pass": passed["updated_at"] = "2026-10-18T11:00:00Z"
    elif change == "old_head": passed["body"] = passed["body"].replace(HEAD[:10], "e" * 10)
    elif change == "prior_pass": passed["created_at"] = passed["updated_at"] = "2026-10-18T09:59:00Z"
    elif change == "edited_request": request["updated_at"] = "2026-10-18T11:00:00Z"
    elif change == "wrong_request": request["body"] = "@codex review"
    elif change == "internal_missing": task["last_review"] = None
    with pytest.raises(admin.OwnerAdminError): evidence(case)


def test_findings_on_same_head_override_clean_receipt(case):
    state, task, routes, request, passed, runs, pr = case
    routes[f"repos/{REPO}/pulls/131/comments?per_page=100"].append(
        dict(user=passed["user"], commit_id=HEAD, body="P1: wrong calculation"))
    with pytest.raises(resume.ReviewPending, match="findings need an engineer"): evidence(case)


def test_github_remapped_finding_from_repaired_commit_does_not_block_fresh_pass(case):
    state, task, routes, request, passed, runs, pr = case
    # Observed on real Weekly ETF PR #131: commit_id moved to the repaired head,
    # while original_commit_id still names the commit that actually had the bug.
    routes[f"repos/{REPO}/pulls/131/comments?per_page=100"].append(
        dict(user=passed["user"], commit_id=HEAD, original_commit_id="e" * 40,
             body="Finding on the previous candidate; repaired and re-reviewed"))
    assert evidence(case)["external_review"]["status"] == "PASS"


def test_other_active_holder_is_never_released_or_reused(case):
    state, task, *_ = case
    proof = evidence(case)
    state["queue"]["execution_lock"] = dict(run_id="another-native-run", task_id=task["task_id"],
        started_at="2026-10-18T11:50:00Z", expires_at="2026-10-18T13:20:00Z")
    with pytest.raises(resume.ReviewPending, match="live holder"): resume.finish_review(state, task, proof, now=NOW)


def test_interrupted_chat_expired_claim_is_released_only_with_same_task_completion(case):
    state, task, *_ = case
    proof = evidence(case)
    state["queue"]["execution_lock"] = dict(run_id="original-native-run", task_id=task["task_id"],
        started_at="2026-10-18T09:30:00Z", expires_at="2026-10-18T11:00:00Z")
    original = deepcopy(state["queue"])
    result = resume.finish_review(state, task, proof, now=NOW)
    assert state["queue"] == original
    assert result["execution_lock"] is None
    assert result["tasks"][0]["status"] == "READY"


def test_expired_foreign_claim_is_never_touched(case):
    state, task, *_ = case
    state["queue"]["execution_lock"] = dict(run_id="other-native-run", task_id="different-task",
        started_at="2026-10-18T09:30:00Z", expires_at="2026-10-18T11:00:00Z")
    with pytest.raises(resume.ReviewPending, match="another task"):
        resume._unheld_queue(state["queue"], task, now=NOW)


@pytest.mark.parametrize("field,value", [("status", "DONE"), ("phase", "REPAIR"), ("blocker", "HOLD"),
    ("repository", "market-predictions/agent"), ("integration_policy", "AUTO_AFTER_PASS")])
def test_only_existing_waiting_scope_is_eligible(case, field, value):
    state, task, *_ = case
    task[field] = value
    assert not resume.eligible(task)


def native_env(monkeypatch):
    for key, value in dict(GITHUB_REPOSITORY=admin.PUBLIC_REPOSITORY, GITHUB_REF="refs/heads/main",
        GITHUB_EVENT_NAME="schedule", GITHUB_RUN_ATTEMPT="1").items(): monkeypatch.setenv(key, value)


def test_background_execution_and_duplicate_wake_are_idempotent(case, monkeypatch, capsys):
    state, task, *_ = case
    native_env(monkeypatch)
    monkeypatch.setattr(resume, "_load_state", lambda: state)
    writes = []
    def write(old, new, command, *, pre_ref_cas):
        pre_ref_cas()
        writes.append(deepcopy(new))
        state["queue"] = new
        return "9" * 40
    monkeypatch.setattr(admin, "_write_queue_exact", write)
    assert resume.main() == 0
    assert "CONTROL_V4_REVIEW_RESUME=READY" in capsys.readouterr().out
    assert resume.main() == 0
    assert "CONTROL_V4_REVIEW_RESUME=NO_WORK" in capsys.readouterr().out
    assert len(writes) == 1


def test_waiting_first_eight_tasks_do_not_starve_a_later_clean_review(case, monkeypatch):
    state, task, *_ = case
    # Eight genuine waiting states precede the clean review in canonical order.
    siblings = []
    for i in range(2, 10):
        sibling = deepcopy(task)
        sibling.update(task_id=f"MISSION--M--2026-10-18-r1--G{i}", gap_id=f"G{i}")
        sibling["candidate"]["candidate_pr_number"] = 131 + i
        sibling["external_review"]["request_key"] = f"G{i}--{HEAD}--main--{BASE}"
        gap = deepcopy(state["bundle"].missions[0]["gaps"][0])
        gap["gap_id"] = f"G{i}"
        state["bundle"].missions[0]["gaps"].append(gap)
        siblings.append(sibling)
    state["queue"]["tasks"] = siblings + [task]
    native_env(monkeypatch)
    class Clock(datetime):
        current = NOW
        @classmethod
        def now(cls, tz=None): return cls.current
    monkeypatch.setattr(resume, "datetime", Clock)
    monkeypatch.setattr(resume, "_load_state", lambda: state)
    real_completion = resume.completion_evidence
    observed = []
    def complete(current, selected):
        observed.append(selected["task_id"])
        if selected["task_id"] != task["task_id"]:
            raise resume.ReviewPending("stale evidence still awaiting engineering")
        return real_completion(current, selected)
    monkeypatch.setattr(resume, "completion_evidence", complete)
    writes = []
    def write(old, new, command, *, pre_ref_cas):
        pre_ref_cas()
        writes.append(new)
        state["queue"] = new
        return "9" * 40
    monkeypatch.setattr(admin, "_write_queue_exact", write)
    for hour in range(2):
        Clock.current = NOW + timedelta(hours=hour)
        assert resume.main() == 0
        if writes: break
    assert len(writes) == 1
    assert state["queue"]["tasks"][-1]["status"] == "READY"
    assert all(t["status"] == "ACTIVE" for t in state["queue"]["tasks"][:-1])


def test_late_evidence_change_rejects_commit_without_retry(case, monkeypatch, capsys):
    state, task, routes, request, passed, runs, pr = case
    native_env(monkeypatch)
    monkeypatch.setattr(resume, "_load_state", lambda: state)
    original = deepcopy(state["queue"])
    def write(old, new, command, *, pre_ref_cas):
        runs[0]["conclusion"] = "failure"
        pre_ref_cas()
        pytest.fail("changed evidence must prevent CAS")
    monkeypatch.setattr(admin, "_write_queue_exact", write)
    assert resume.main() == 0
    assert "PENDING" in capsys.readouterr().out
    assert state["queue"] == original


def test_stale_private_cas_is_terminal_and_not_retried(case, monkeypatch):
    state, task, *_ = case
    native_env(monkeypatch)
    monkeypatch.setattr(resume, "_load_state", lambda: state)
    writes = []
    def write(*args, **kwargs):
        writes.append(True)
        raise admin.StaleWriteError("another run acquired task")
    monkeypatch.setattr(admin, "_write_queue_exact", write)
    assert resume.main() == 1
    assert writes == [True]


def test_existing_writer_rechecks_review_after_object_creation_before_atomic_cas(case, monkeypatch):
    state, task, routes, request, passed, runs, pr = case
    proof = evidence(case)
    result = resume.finish_review(state, task, proof, now=NOW)
    monkeypatch.setenv("CONTROL_PLANE_TOKEN", "inert-test-token")
    monkeypatch.setattr(admin, "_branch_head", lambda repository, branch, private: (state["main_sha"] if branch == "main" else state["runtime_sha"]) if private else BASE)
    monkeypatch.setattr(admin, "_private_get", lambda path: {"tree": {"sha": "4" * 40}})
    objects = []
    def post(path, payload):
        objects.append(path)
        if path.endswith("/git/commits"):
            runs[0]["conclusion"] = "failure"
        return {"sha": "5" * 40}
    monkeypatch.setattr(admin, "_private_post", post)
    monkeypatch.setattr(admin, "_request_json", lambda *a, **kw: pytest.fail("CAS must not run after CI failure"))
    with pytest.raises(resume.ReviewPending):
        admin._write_queue_exact(state, result, proof["command"], pre_ref_cas=lambda: evidence(case))
    assert len(objects) == 3


def test_existing_writer_atomically_fences_both_private_refs(case, monkeypatch):
    state, task, *_ = case
    proof = evidence(case)
    result = resume.finish_review(state, task, proof, now=NOW)
    monkeypatch.setenv("CONTROL_PLANE_TOKEN", "inert-test-token")
    monkeypatch.setattr(admin, "_branch_head", lambda repository, branch, private: (state["main_sha"] if branch == "main" else state["runtime_sha"]) if private else BASE)
    monkeypatch.setattr(admin, "_private_get", lambda path: {"tree": {"sha": "4" * 40}})
    monkeypatch.setattr(admin, "_private_post", lambda *a, **kw: {"sha": "5" * 40})
    writes = []
    def graphql(url, **kwargs):
        writes.append(kwargs["payload"]["variables"]["input"]["refUpdates"])
        return {"data": {"updateRefs": {"clientMutationId": "ok"}}}
    monkeypatch.setattr(admin, "_request_json", graphql)
    assert admin._write_queue_exact(state, result, proof["command"], pre_ref_cas=lambda: evidence(case)) == "5" * 40
    assert writes == [[
        {"name": "refs/heads/main", "beforeOid": state["main_sha"], "afterOid": state["main_sha"], "force": False},
        {"name": "refs/heads/control-runtime-state", "beforeOid": state["runtime_sha"], "afterOid": "5" * 40, "force": False},
    ]]


def test_issue_comment_cannot_invoke_background_authority(case, monkeypatch):
    native_env(monkeypatch)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "issue_comment")
    monkeypatch.setattr(resume, "_load_state", lambda: pytest.fail("no private read before admission"))
    assert resume.main() == 1


def test_native_schedule_is_narrow_and_replaces_work_pilot():
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text()
    job = workflow.split("\n  review-resume:\n")[1].split("\n  interactive-control-start:\n")[0]
    assert "cron: '30 * * * *'" in workflow
    assert "github.event_name == 'schedule'" in job
    assert "inputs.mode == 'review-resume'" in job
    assert "repositories: control-plane" in job
    assert "permission-contents: write" in job
    assert "contents: read" in job
    assert "scripts/control_v4_review_resume.py" in job
    assert "legacy-work" not in workflow
    assert "human-start-probe:" not in workflow
    assert "permission-pull-requests" not in job
