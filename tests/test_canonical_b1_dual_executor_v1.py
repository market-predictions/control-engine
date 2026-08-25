from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path

import pytest

from control_engine.cloudflare_b1 import SemanticBudgetMeasurement, classify_execution_surface

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "canonical_b1_dual_executor_v1.py"
WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "canonical-b1-dual-executor-v1.yml"
spec = importlib.util.spec_from_file_location("canonical_b1_dual_executor_v1", SCRIPT)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

CANDIDATE = "a" * 40
RUN_ID = "run-test"
TASK_ID = "T-G8"


def _profile(status="ACTIVE"):
    return {
        "protocol_id": "CONTROL_ASSURANCE_EXECUTION_PROFILE_V1",
        "version": "1.0",
        "status": status,
        "lifecycle_authority": {
            "role": "governance_release_assurance",
            "worker_instance": "B1",
            "capacity": 1,
        },
        "standard": {
            "executor": "cloudflare-workers-ai",
            "model": "@cf/openai/gpt-oss-120b",
            "endpoint_class": "direct-workers-ai",
            "max_tokens": 1024,
            "tools_enabled": False,
            "semantic_calls_per_run": 1,
            "automatic_retry": False,
            "provider_fallback": False,
            "model_fallback": False,
            "paid_fallback": False,
        },
        "deep": {
            "executor": "native-codex-github-review",
            "request_marker": "CONTROL_B1_CODEX_DEEP_REQUEST_V1",
            "trusted_connector_logins": [
                "chatgpt-codex-connector",
                "chatgpt-codex-connector[bot]",
            ],
            "review_only": True,
            "exact_head_required": True,
            "trusted_request_envelope_required": True,
        },
        "principal_manual_relay_count": 0,
    }


def _queue(*, worker="B1", expires_delta=timedelta(minutes=10)):
    now = datetime.now(timezone.utc)
    fmt = lambda v: v.isoformat().replace("+00:00", "Z")
    return {
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": TASK_ID,
                "repository": "market-predictions/control-engine",
                "state": "ASSURANCE_EXECUTING",
                "active_role": "governance_release_assurance",
                "active_worker_instance": worker,
                "active_run_id": RUN_ID,
                "candidate_sha": CANDIDATE,
                "handover_id": "H-G8",
                "acceptance_criteria": ["exact candidate is reviewed"],
                "instruction": "review exact candidate",
                "claim_started_at": fmt(now - timedelta(minutes=1)),
                "claim_expires_at": fmt(now + expires_delta),
                "principal_manual_relay_count": 0,
                "candidate_pr": 70,
                "merge_policy": "AFTER_PASS_EXACT_HEAD",
                "project_integration_authorized": False,
            }
        ],
    }


def _required_profile_predicates():
    return [
        '.protocol_id == "CONTROL_ASSURANCE_EXECUTION_PROFILE_V1"',
        '.version == "1.0"',
        '.status == "ACTIVE"',
        '.lifecycle_authority.role == "governance_release_assurance"',
        '.lifecycle_authority.worker_instance == "B1"',
        '.lifecycle_authority.capacity == 1',
        '.standard.executor == "cloudflare-workers-ai"',
        '.standard.model == "@cf/openai/gpt-oss-120b"',
        '.standard.endpoint_class == "direct-workers-ai"',
        '.standard.semantic_calls_per_run == 1',
        '.standard.tools_enabled == false',
        '.standard.automatic_retry == false',
        '.standard.provider_fallback == false',
        '.standard.model_fallback == false',
        '.standard.paid_fallback == false',
        '.standard.max_tokens == 1024',
        '.deep.executor == "native-codex-github-review"',
        '.deep.request_marker == "CONTROL_B1_CODEX_DEEP_REQUEST_V1"',
        '(.deep.trusted_connector_logins | sort) == (["chatgpt-codex-connector", "chatgpt-codex-connector[bot]"] | sort)',
        '.deep.review_only == true',
        '.deep.exact_head_required == true',
        '.deep.trusted_request_envelope_required == true',
        '.principal_manual_relay_count == 0',
    ]


def test_candidate_profile_cannot_execute():
    with pytest.raises(mod.CanonicalB1Error, match="not ACTIVE"):
        mod._profile(_profile("CANDIDATE_GATE8"))


def test_active_profile_preserves_one_b1_and_no_fallback():
    value = mod._profile(_profile())
    assert value["lifecycle_authority"]["capacity"] == 1
    assert value["standard"]["semantic_calls_per_run"] == 1
    assert value["standard"]["automatic_retry"] is False
    assert value["standard"]["provider_fallback"] is False
    assert value["standard"]["model_fallback"] is False
    assert value["standard"]["paid_fallback"] is False


def test_active_profile_requires_exact_standard_token_budget():
    for value in (1, 1023, 1025, 2048):
        profile = _profile()
        profile["standard"]["max_tokens"] = value
        with pytest.raises(mod.CanonicalB1Error, match="max_tokens"):
            mod._profile(profile)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("standard", "executor", "other-executor"),
        ("standard", "endpoint_class", "other-endpoint"),
        ("deep", "executor", "other-deep-executor"),
        ("deep", "request_marker", "OTHER_REQUEST_MARKER"),
        ("deep", "trusted_request_envelope_required", False),
    ],
)
def test_active_profile_rejects_h9_omitted_contract_fields(section, field, value):
    profile = _profile()
    profile[section][field] = value
    with pytest.raises(mod.CanonicalB1Error):
        mod._profile(profile)


def test_workflow_full_profile_guard_precedes_reconcile_claim_and_terminal_mutations():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_PRIVATE_B_CODE_SHA: 01b3fb7e5905e61a8a96c2665d2d8afd74b4dd60" in text
    assert '[ "$(git -C "$b_code" rev-parse HEAD)" = "$CONTROL_PRIVATE_B_CODE_SHA" ]' in text

    claim = text.split("- name: Reconcile, select and claim exact preferred B1", 1)[1]
    claim = claim.split("- name: Collect exact evidence and execute deterministic route", 1)[0]
    terminal = text.split("- name: Revalidate exact claim and persist terminal result", 1)[1]
    terminal = terminal.split("- name: Publish bounded liveness", 1)[0]

    for predicate in _required_profile_predicates():
        assert predicate in claim
        assert predicate in terminal

    reconcile_loop = claim.split("for cas_attempt in 1 2 3; do", 1)[1]
    push = 'git -C "$state" push --quiet origin "HEAD:refs/heads/${CONTROL_RUNTIME_REF}"'
    assert reconcile_loop.index('assert_active_profile "$state"') < reconcile_loop.index(push)

    claim_call = 'control_connected_worker_runtime_v1.py" claim'
    selection = "python control_engine/scheduled_worker_b.py select-b1"
    last_guard_before_claim = claim.rfind('assert_active_profile "$state"', 0, claim.index(claim_call))
    assert claim.index(selection) < last_guard_before_claim < claim.index(claim_call)

    terminal_loop = terminal.split("for cas_attempt in 1 2 3; do", 1)[1]
    clone = 'git clone --quiet --single-branch --branch "$CONTROL_RUNTIME_REF" "$private_url" "$state"'
    guard = 'assert_active_profile "$state"'
    pr_snapshot = 'gh api "repos/${TARGET_REPOSITORY}/pulls/${TARGET_PR}" > "$RUNNER_TEMP/complete-pr.json"'
    ci_snapshot = 'gh api "repos/${TARGET_REPOSITORY}/actions/runs/${REQUIRED_CI_RUN_ID}" > "$RUNNER_TEMP/complete-ci.json"'
    complete = 'control_connected_worker_runtime_v1.py" complete'
    assert terminal_loop.index(clone) < terminal_loop.index(guard) < terminal_loop.index(pr_snapshot) < terminal_loop.index(ci_snapshot) < terminal_loop.index(complete)


def test_workflow_freezes_pr_evidence_snapshot_and_requires_exact_head_ci():
    text = WORKFLOW.read_text(encoding="utf-8")
    evidence = text.split("- name: Collect exact evidence and execute deterministic route", 1)[1]
    evidence = evidence.split("- name: Revalidate exact claim and persist terminal result", 1)[0]

    for token in (
        '"$RUNNER_TEMP/pr-before.json"',
        '.state == "open"',
        '.draft == true',
        '.merged != true',
        '.head.sha == $sha',
        '(.base.sha | type == "string" and test("^[0-9a-f]{40}$"))',
        '"$RUNNER_TEMP/pr-binding-before.json"',
        '"$RUNNER_TEMP/pr-binding-after.json"',
        'cmp -s "$RUNNER_TEMP/pr-binding-before.json" "$RUNNER_TEMP/pr-binding-after.json"',
        '.workflow_id == $workflow_id',
        '.id == $run_id',
        '.head_sha == $sha',
        '.status == "completed"',
        '.conclusion == "success"',
        '--argjson workflow_id "$CONTROL_CI_WORKFLOW_ID"',
        '--argjson run_id "$ci_run_id"',
        'printf \'ci_run_id=%s\\n\' "$ci_run_id" >> "$GITHUB_OUTPUT"',
        '--pr-json "$RUNNER_TEMP/pr-before.json"',
    ):
        assert token in evidence

    terminal = text.split("- name: Revalidate exact claim and persist terminal result", 1)[1]
    terminal = terminal.split("- name: Publish bounded liveness", 1)[0]
    for token in (
        'TARGET_BASE_SHA: ${{ steps.evidence.outputs.base_sha }}',
        'REQUIRED_CI_RUN_ID: ${{ steps.evidence.outputs.ci_run_id }}',
        '.draft == true',
        '.head.sha == $sha',
        '.base.sha == $base',
        '.workflow_id == $workflow_id',
        '.id == $run_id',
        '.status == "completed"',
        '.conclusion == "success"',
        '--argjson workflow_id "$CONTROL_CI_WORKFLOW_ID"',
        '--argjson run_id "$REQUIRED_CI_RUN_ID"',
    ):
        assert token in terminal

    loop = terminal.split("for cas_attempt in 1 2 3; do", 1)[1]
    assert loop.count('gh api "repos/${TARGET_REPOSITORY}/pulls/${TARGET_PR}" > "$RUNNER_TEMP/complete-pr.json"') == 1


def test_workflow_ci_binding_uses_immutable_workflow_id_not_display_name():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_CI_WORKFLOW_ID: 337765381" in text
    assert text.count('.workflow_id == $workflow_id') >= 2
    assert text.count('.id == $run_id') >= 2
    assert '.name == "Control Engine CI"' not in text
    assert 'REQUIRED_CI_RUN_ID: ${{ steps.evidence.outputs.ci_run_id }}' in text


def test_start_proven_rejects_wrong_worker_and_expired_lease():
    with pytest.raises(mod.CanonicalB1Error, match="role/worker"):
        mod._validate_claim(_queue(worker="B2"), TASK_ID, RUN_ID, CANDIDATE)
    with pytest.raises(mod.CanonicalB1Error, match="lease"):
        mod._validate_claim(_queue(expires_delta=timedelta(seconds=-1)), TASK_ID, RUN_ID, CANDIDATE)


def test_b0_binds_repository_changed_files_acceptance_and_diff():
    queue = _queue()
    task = mod._validate_claim(queue, TASK_ID, RUN_ID, CANDIDATE)
    diff = "+safe\n"
    capsule = mod._b0(
        queue=queue,
        task=task,
        run_id=RUN_ID,
        candidate_sha=CANDIDATE,
        changed_files=["scripts/canonical_b1_dual_executor_v1.py"],
        diff=diff,
    )
    assert capsule["protocol_id"] == "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1"
    assert capsule["task"]["repository"] == "market-predictions/control-engine"
    assert capsule["changed_files"] == ["scripts/canonical_b1_dual_executor_v1.py"]
    assert capsule["claim"]["start_proven"] is True
    assert capsule["deterministic_contradictions"] == []
    assert capsule["diff"]["bytes"] == len(diff.encode())
    assert len(capsule["task"]["acceptance_criteria_sha256"]) == 64


def test_activation_surface_routes_deep_deterministically():
    decision = classify_execution_surface(
        repository="market-predictions/control-engine",
        changed_files=["scripts/canonical_b1_dual_executor_v1.py"],
        budget=SemanticBudgetMeasurement(100, 100, 100, 1000),
    )
    assert decision.work_required is True
    assert any(reason.startswith("CONTROL_AUTHORITY_PATH:") for reason in decision.reasons)


def test_standard_executes_exactly_one_call_and_records_provenance(monkeypatch):
    calls = []

    def fake_run(**kwargs):
        calls.append(kwargs)
        return {
            "id": "response-1",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": json.dumps({
                    "candidate_sha": CANDIDATE,
                    "verdict": "PASS",
                    "summary": "supported",
                    "findings": [],
                })},
            }],
        }

    monkeypatch.setattr(mod, "run_workers_ai_once", fake_run)
    queue = _queue()
    task = mod._validate_claim(queue, TASK_ID, RUN_ID, CANDIDATE)
    capsule = mod._b0(
        queue=queue,
        task=task,
        run_id=RUN_ID,
        candidate_sha=CANDIDATE,
        changed_files=["README.md"],
        diff="+safe\n",
    )
    result = mod._standard(
        task=task,
        run_id=RUN_ID,
        candidate_sha=CANDIDATE,
        capsule=capsule,
        diff="+safe\n",
        evidence={},
        profile=_profile(),
    )
    assert result["outcome"] == "PASS"
    assert len(calls) == 1
    assert calls[0]["max_tokens"] == 1024
    provenance = next(x for x in result["evidence"] if x.startswith("CONTROL_STANDARD_EXECUTOR_PROVENANCE_V1:"))
    assert '"call_count":1' in provenance
    assert '"retry_count":0' in provenance
    assert '"provider_switches":0' in provenance
    assert '"paid_fallback":false' in provenance


def test_paginated_list_collects_every_page_before_return(monkeypatch):
    observed = []

    def fake_gh_json(token, method, path, payload=None, accept=None):
        observed.append(path)
        if "&page=1" in path:
            return [{"page": 1, "n": n} for n in range(100)]
        if "&page=2" in path:
            return [{"page": 2, "finding": "P1 BLOCKER"}]
        raise AssertionError(path)

    monkeypatch.setattr(mod, "_gh_json", fake_gh_json)
    items = mod._gh_list_all("token", "/repos/o/r/pulls/70/reviews")
    assert len(items) == 101
    assert items[-1]["finding"] == "P1 BLOCKER"
    assert observed == [
        "/repos/o/r/pulls/70/reviews?per_page=100&page=1",
        "/repos/o/r/pulls/70/reviews?per_page=100&page=2",
    ]


def test_paginated_list_fails_closed_on_non_list_later_page(monkeypatch):
    def fake_gh_json(token, method, path, payload=None, accept=None):
        if "&page=1" in path:
            return [{} for _ in range(100)]
        return {"message": "malformed page"}

    monkeypatch.setattr(mod, "_gh_json", fake_gh_json)
    with pytest.raises(mod.CanonicalB1Error, match="paginated list response invalid"):
        mod._gh_list_all("token", "/repos/o/r/issues/70/comments")


def test_deep_real_classifier_observes_page2_blocker_despite_clean_completion_reaction(monkeypatch):
    monkeypatch.setenv("CONTROL_GITHUB_WRITE_TOKEN", "token")
    observed = []
    request_body = {"value": None}
    request_created_at = "2026-08-24T22:00:00Z"
    review_id = 777

    def fake_gh_json(token, method, path, payload=None, accept=None):
        observed.append((method, path))
        if method == "POST":
            assert path == "/repos/market-predictions/control-engine/issues/70/comments"
            assert isinstance(payload, dict) and isinstance(payload.get("body"), str)
            request_body["value"] = payload["body"]
            return {"id": 321, "user": {"login": "market-predictions"}}

        if "/pulls/70/reviews?" in path:
            assert "&page=1" in path
            return [{
                "id": review_id,
                "user": {"login": "chatgpt-codex-connector"},
                "state": "COMMENTED",
                "submitted_at": "2026-08-24T22:00:10Z",
                "commit_id": CANDIDATE,
                "body": "Codex terminal exact-head review",
            }]

        if "/pulls/70/comments?" in path:
            if "&page=1" in path:
                return [{} for _ in range(100)]
            if "&page=2" in path:
                return [{
                    "id": 888,
                    "user": {"login": "chatgpt-codex-connector"},
                    "pull_request_review_id": review_id,
                    "commit_id": CANDIDATE,
                    "body": "P1 BLOCKER",
                    "created_at": "2026-08-24T22:00:11Z",
                    "path": "tests/test_canonical_b1_dual_executor_v1.py",
                    "line": 265,
                }]
            raise AssertionError(path)

        if "/issues/comments/321/reactions?" in path:
            assert "&page=1" in path
            return [{
                "id": 999,
                "content": "+1",
                "user": {"login": "chatgpt-codex-connector[bot]"},
            }]

        if "/issues/70/comments?" in path:
            assert "&page=1" in path
            assert request_body["value"] is not None
            return [{
                "id": 321,
                "user": {"login": "market-predictions"},
                "body": request_body["value"],
                "created_at": request_created_at,
                "updated_at": request_created_at,
            }]

        raise AssertionError((method, path))

    monkeypatch.setattr(mod, "_gh_json", fake_gh_json)
    task = _queue()["tasks"][0]
    result = mod._deep(
        task=task,
        run_id=RUN_ID,
        candidate_sha=CANDIDATE,
        repository="market-predictions/control-engine",
        pr_number=70,
        timeout_seconds=1,
    )

    assert result["outcome"] == "FAIL"
    assert any("P1 BLOCKER" in finding for finding in result["findings"])
    assert ("GET", "/repos/market-predictions/control-engine/pulls/70/comments?per_page=100&page=2") in observed
    assert ("GET", "/repos/market-predictions/control-engine/pulls/70/comments?per_page=100&page=3") not in observed


@pytest.mark.parametrize(
    "malformed",
    [
        {"commit_id": None},
        {"commit_id": CANDIDATE, "original_commit_id": "b" * 40},
        {"commit_id": CANDIDATE, "pull_request_review_id": None},
    ],
)
def test_deep_page2_malformed_trusted_comment_fails_closed_before_clean_pass(monkeypatch, malformed):
    monkeypatch.setenv("CONTROL_GITHUB_WRITE_TOKEN", "token")
    request_body = {"value": None}
    request_created_at = "2026-08-24T22:00:00Z"
    review_id = 777

    def fake_gh_json(token, method, path, payload=None, accept=None):
        if method == "POST":
            request_body["value"] = payload["body"]
            return {"id": 321, "user": {"login": "market-predictions"}}
        if "/pulls/70/reviews?" in path:
            return [{
                "id": review_id,
                "user": {"login": "chatgpt-codex-connector"},
                "state": "COMMENTED",
                "submitted_at": "2026-08-24T22:00:10Z",
                "commit_id": CANDIDATE,
                "body": "Codex terminal exact-head review",
            }]
        if "/pulls/70/comments?" in path:
            if "&page=1" in path:
                return [{} for _ in range(100)]
            item = {
                "id": 888,
                "user": {"login": "chatgpt-codex-connector"},
                "pull_request_review_id": review_id,
                "commit_id": CANDIDATE,
                "body": "P1 BLOCKER THAT MUST NOT DISAPPEAR",
                "created_at": "2026-08-24T22:00:11Z",
            }
            item.update(malformed)
            return [item]
        if "/issues/comments/321/reactions?" in path:
            return [{
                "id": 999,
                "content": "+1",
                "user": {"login": "chatgpt-codex-connector[bot]"},
            }]
        if "/issues/70/comments?" in path:
            return [{
                "id": 321,
                "user": {"login": "market-predictions"},
                "body": request_body["value"],
                "created_at": request_created_at,
                "updated_at": request_created_at,
            }]
        raise AssertionError((method, path))

    monkeypatch.setattr(mod, "_gh_json", fake_gh_json)
    with pytest.raises(mod.CanonicalB1Error, match="trusted DEEP review comment"):
        mod._deep(
            task=_queue()["tasks"][0],
            run_id=RUN_ID,
            candidate_sha=CANDIDATE,
            repository="market-predictions/control-engine",
            pr_number=70,
            timeout_seconds=1,
        )


def test_deep_ignores_malformed_untrusted_page2_noise(monkeypatch):
    request_start = "2026-08-24T22:00:00Z"
    mod._validate_deep_snapshot_records(
        reviews=[{
            "id": 777,
            "user": {"login": "chatgpt-codex-connector"},
            "state": "COMMENTED",
            "submitted_at": "2026-08-24T22:00:10Z",
            "commit_id": CANDIDATE,
        }, {"user": {"login": "random-user"}, "commit_id": None}],
        review_comments=[{"user": {"login": "random-user"}, "commit_id": None}],
        reactions=[{"user": {"login": "random-user"}, "content": None}],
        issue_comments=[{
            "id": 321,
            "user": {"login": "market-predictions"},
            "body": "request",
            "created_at": request_start,
            "updated_at": request_start,
        }, {"user": {"login": "random-user"}}],
        request_comment_id=321,
        trusted_actuator_login="market-predictions",
    )



def _valid_deep_records(*, comment_body="P1 BLOCKER", review_id=777, linked_review_id=777):
    request_start = "2026-08-24T22:00:00Z"
    return dict(
        reviews=[{
            "id": review_id,
            "user": {"login": "chatgpt-codex-connector"},
            "state": "COMMENTED",
            "submitted_at": "2026-08-24T22:00:10Z",
            "commit_id": CANDIDATE,
        }],
        review_comments=[{
            "id": 888,
            "user": {"login": "chatgpt-codex-connector"},
            "pull_request_review_id": linked_review_id,
            "commit_id": CANDIDATE,
            "body": comment_body,
            "created_at": "2026-08-24T22:00:11Z",
        }],
        reactions=[],
        issue_comments=[{
            "id": 321,
            "user": {"login": "market-predictions"},
            "body": "request",
            "created_at": request_start,
            "updated_at": request_start,
        }],
        request_comment_id=321,
        trusted_actuator_login="market-predictions",
    )


def test_trusted_review_comment_empty_body_fails_closed():
    with pytest.raises(mod.CanonicalB1Error, match="review comment malformed"):
        mod._validate_deep_snapshot_records(**_valid_deep_records(comment_body="   "))


def test_trusted_review_comment_requires_fetched_trusted_review_linkage():
    with pytest.raises(mod.CanonicalB1Error, match="review comment linkage"):
        mod._validate_deep_snapshot_records(**_valid_deep_records(linked_review_id=999))


def test_trusted_review_comment_valid_linkage_remains_accepted():
    mod._validate_deep_snapshot_records(**_valid_deep_records())


def test_workflow_uses_bounded_deep_lease_and_exact_designated_ci_run():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_PRIVATE_B_CODE_REF: runtime/public-b-v2-code-r3" in text
    assert "CONTROL_PRIVATE_B_CODE_SHA: 01b3fb7e5905e61a8a96c2665d2d8afd74b4dd60" in text
    assert "lease_seconds=900" in text
    assert 'if [ "$assurance_class" = DEEP ]; then lease_seconds=5400; fi' in text
    assert '--lease-seconds "$lease_seconds"' in text
    assert "steps.claim.outputs.designated_ci_run_id" in text
    assert 'ci_run_id="$DESIGNATED_CI_RUN_ID"' in text
    assert "sort_by(.id) | last" not in text
    assert "exactly one designated CI run identity is required" in text
