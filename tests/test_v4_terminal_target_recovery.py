from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_authority_io import V4AuthorityBundle
from control_engine.v4_runtime_protocol import parse_public_command
from scripts import control_v4_owner_admin as owner_admin


NOW = datetime(2026, 9, 22, 20, 15, tzinfo=timezone.utc)
OLD_SHA = "1" * 40
NEW_SHA = "2" * 40
BASE_SHA = "3" * 40
CURRENT_BASE_SHA = "4" * 40
MISSION_SHA = "5" * 40
AUTHORITY_SHA = "6" * 40


def candidate(sha: str, pr: int) -> dict:
    return {
        "candidate_sha": sha,
        "candidate_pr_number": pr,
        "candidate_head_branch": f"candidate-{pr}",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def task(task_id: str, repository: str, pr: int, *, review_policy: str = "INTERNAL") -> dict:
    value = {
        "task_id": task_id,
        "mission_id": "M",
        "mission_revision": "2026-09-22-r1",
        "mission_contract_blob_sha": MISSION_SHA,
        "repository_authority_blob_sha": AUTHORITY_SHA,
        "gap_id": task_id.rsplit("--", 1)[-1],
        "repository": repository,
        "acceptance": ["Current target truth must reconcile without stalling unrelated work."],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": review_policy,
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": candidate(OLD_SHA, pr),
        "last_review": {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
            "verdict": "PASS",
            "reviewed_at": "2026-09-22T18:00:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-22T17:00:00Z",
        "updated_at": "2026-09-22T18:00:00Z",
    }
    if review_policy == "EXTERNAL":
        value["external_review"] = {
            "candidate_sha": OLD_SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE_SHA,
            "request_key": f"G1--{OLD_SHA}--main--{BASE_SHA}",
            "status": "PENDING",
            "request_ref": f"https://github.com/{repository}/pull/{pr}#issuecomment-1",
            "evidence_ref": None,
        }
    return value


def queue(*tasks: dict) -> dict:
    return {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": [],
        "tasks": list(tasks),
    }


def fake_state(q: dict) -> dict:
    return {
        "queue": q,
        "runtime_enabled": True,
        "integration_enabled": False,
        "main_sha": "7" * 40,
        "runtime_sha": "8" * 40,
        "queue_blob": "9" * 40,
        "repository_node_id": "R_test",
    }


def test_tick_parks_integrated_target_and_continues_to_next_task(monkeypatch) -> None:
    first = task("MISSION--M--2026-09-22-r1--G1", "example/integrated", 10)
    second = task("MISSION--M--2026-09-22-r1--G2", "example/open", 11)
    q = queue(first, second)
    writes: list[tuple[dict, str]] = []

    def fake_target(repository: str, pr_number: int):
        if repository == "example/integrated":
            raise carrier.TargetCandidateTerminalError(carrier.INTEGRATED_TARGET_BLOCKER)
        return candidate(NEW_SHA, pr_number)

    def fake_write(state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_target_pr_candidate", fake_target)
    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)

    state, result = carrier._tick(
        {"kind": "TICK", "run_id": "run-terminal", "yielded_task_tokens": []},
        fake_state(q),
        now=NOW,
    )

    parked = state["queue"]["tasks"][0]
    assert parked["status"] == "BLOCKED"
    assert parked["phase"] is None
    assert parked["blocker"] == carrier.INTEGRATED_TARGET_BLOCKER
    assert result["result"] == "WORK"
    assert result["repository"] == "example/open"
    assert state["queue"]["execution_lock"]["task_id"] == second["task_id"]
    assert writes


def authority_bundle(review_policy: str = "EXTERNAL") -> V4AuthorityBundle:
    mission = {
        "protocol_id": "MISSION_CONTRACT_V4",
        "mission_id": "M",
        "mission_revision": "2026-09-22-r1",
        "repository": "example/integrated",
        "desired_outcome": "Reconcile already integrated exact truth.",
        "gaps": [{
            "gap_id": "G1",
            "gap_state": "OPEN",
            "depends_on": [],
            "repository": "example/integrated",
            "acceptance": ["Exact integrated candidate and review evidence must be preserved."],
            "integration_policy": "HOLD_AFTER_PASS",
            "review_policy": review_policy,
        }],
        "authority_boundaries": ["No standing integration authority."],
        "principal_manual_relay_count": 0,
    }
    authority = {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V4",
        "repository": "example/integrated",
        "required_check_runs": [],
        "principal_manual_relay_count": 0,
    }
    return V4AuthorityBundle(
        missions=(mission,),
        authorities=(authority,),
        mission_blob_shas={"M": MISSION_SHA},
        authority_blob_shas={"example/integrated": AUTHORITY_SHA},
    )


def reconcile_command() -> dict:
    return {
        "operation": "RECONCILE_INTEGRATED",
        "internal_review_comment_id": 101,
        "external_review_request_comment_id": 201,
        "external_review_comment_id": 202,
        "repository": "example/integrated",
        "candidate_pr_number": 10,
        "candidate_sha": NEW_SHA,
        "candidate_head_branch": "candidate-10",
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
    }


def internal_review() -> dict:
    return {
        "candidate_sha": NEW_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "verdict": "PASS",
        "reviewed_at": "2026-09-22T18:30:00Z",
    }


def external_review() -> dict:
    return {
        "candidate_sha": NEW_SHA,
        "expected_base_branch": "main",
        "expected_base_sha": BASE_SHA,
        "request_key": f"G1--{NEW_SHA}--main--{BASE_SHA}",
        "status": "PASS",
        "request_ref": "https://github.com/example/integrated/pull/10#issuecomment-201",
        "evidence_ref": "https://github.com/example/integrated/pull/10#issuecomment-202",
    }


def test_external_integrated_reconciliation_records_exact_review_evidence() -> None:
    source = task(
        "MISSION--M--2026-09-22-r1--G1",
        "example/integrated",
        10,
        review_policy="EXTERNAL",
    )
    q = queue(source)
    result = owner_admin.reconcile_integrated_v4(
        q,
        authority_bundle(),
        reconcile_command(),
        internal_review(),
        external_review=external_review(),
        now=NOW,
    )
    reconciled = result["tasks"][0]
    assert reconciled["status"] == "DONE"
    assert reconciled["phase"] is None
    assert reconciled["candidate"] == owner_admin.candidate_identity(reconcile_command())
    assert reconciled["last_review"] == internal_review()
    assert reconciled["external_review"] == external_review()
    assert reconciled["blocker"] is None


def test_reconcile_parser_accepts_external_evidence_only_for_reconcile_operation() -> None:
    command = reconcile_command()
    raw = owner_admin.PREFIX + json.dumps(command, separators=(",", ":"))
    assert owner_admin.parse_owner_admin_command(raw) == command


def test_public_external_review_is_exact_bot_authored_unedited_and_head_bound(monkeypatch) -> None:
    source = task(
        "MISSION--M--2026-09-22-r1--G1",
        "example/integrated",
        10,
        review_policy="EXTERNAL",
    )
    q = queue(source)
    command = reconcile_command()
    request = {
        "issue_url": f"{owner_admin.API}/repos/example/integrated/issues/10",
        "html_url": "https://github.com/example/integrated/pull/10#issuecomment-201",
        "user": {"login": owner_admin.PRINCIPAL_LOGIN, "id": owner_admin.PRINCIPAL_USER_ID},
        "created_at": "2026-09-22T18:35:00Z",
        "updated_at": "2026-09-22T18:35:00Z",
        "body": (
            "@codex review\n\nCONTROL_V4_EXTERNAL_REVIEW_REQUEST\n"
            f"Fresh review of `{NEW_SHA}` against `main@{BASE_SHA}` for `M@2026-09-22-r1 / G1`."
        ),
    }
    evidence_comment = {
        "issue_url": f"{owner_admin.API}/repos/example/integrated/issues/10",
        "html_url": "https://github.com/example/integrated/pull/10#issuecomment-202",
        "user": {
            "login": owner_admin.EXTERNAL_REVIEW_BOT_LOGIN,
            "id": owner_admin.EXTERNAL_REVIEW_BOT_USER_ID,
        },
        "created_at": "2026-09-22T18:40:00Z",
        "updated_at": "2026-09-22T18:40:00Z",
        "body": f"Codex Review: Didn't find any major issues. :+1:\n\n**Reviewed commit:** `{NEW_SHA[:10]}`",
    }

    def fake_get(path: str):
        return dict(request if path.endswith("/201") else evidence_comment)

    monkeypatch.setattr(owner_admin, "_public_get", fake_get)
    evidence = owner_admin._public_external_review(command, q)
    assert evidence == external_review()
