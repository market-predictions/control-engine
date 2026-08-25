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
            "trusted_connector_logins": [
                "chatgpt-codex-connector",
                "chatgpt-codex-connector[bot]",
            ],
            "review_only": True,
            "exact_head_required": True,
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


def test_workflow_pins_private_b_and_rechecks_active_profile_before_each_mutation():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_PRIVATE_B_CODE_SHA: 97ef7de0007b4886e336182c7a9a0ee20ae77455" in text
    assert '[ "$(git -C "$b_code" rev-parse HEAD)" = "$CONTROL_PRIVATE_B_CODE_SHA" ]' in text
    assert text.count('assert_active_profile "$state"') >= 3

    terminal = text.split("- name: Revalidate exact claim and persist terminal result", 1)[1]
    terminal = terminal.split("- name: Publish bounded liveness", 1)[0]
    loop = terminal.split("for cas_attempt in 1 2 3; do", 1)[1]
    clone = 'git clone --quiet --single-branch --branch "$CONTROL_RUNTIME_REF" "$private_url" "$state"'
    guard = 'assert_active_profile "$state"'
    complete = 'control_connected_worker_runtime_v1.py" complete'
    assert loop.index(clone) < loop.index(guard) < loop.index(complete)

    required_terminal_contract = [
        '.protocol_id == "CONTROL_ASSURANCE_EXECUTION_PROFILE_V1"',
        '.version == "1.0"',
        '.status == "ACTIVE"',
        '.lifecycle_authority.role == "governance_release_assurance"',
        '.lifecycle_authority.worker_instance == "B1"',
        '.lifecycle_authority.capacity == 1',
        '.standard.model == "@cf/openai/gpt-oss-120b"',
        '.standard.semantic_calls_per_run == 1',
        '.standard.tools_enabled == false',
        '.standard.automatic_retry == false',
        '.standard.provider_fallback == false',
        '.standard.model_fallback == false',
        '.standard.paid_fallback == false',
        '.standard.max_tokens == 1024',
        '(.deep.trusted_connector_logins | sort) == (["chatgpt-codex-connector", "chatgpt-codex-connector[bot]"] | sort)',
        '.deep.review_only == true',
        '.deep.exact_head_required == true',
        '.principal_manual_relay_count == 0',
    ]
    for predicate in required_terminal_contract:
        assert predicate in terminal


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
