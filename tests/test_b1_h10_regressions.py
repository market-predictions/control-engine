import copy

import pytest

from control_engine.cloudflare_b1 import (
    CONTROL_ENGINE_REPOSITORY,
    CloudflareB1Error,
    SemanticBudgetMeasurement,
    build_semantic_pack,
    classify_execution_surface,
)
from control_engine.codex_b1 import (
    INDETERMINATE_MARKER,
    REQUEST_MARKER,
    classify_review_snapshot,
    request_id,
)

CANDIDATE = "a" * 40
TASK_ID = "T1"
HANDOVER_ID = "H1"
REQUEST_COMMENT_ID = 100
REQUEST_AT = "2026-08-23T00:00:00Z"
CURRENT_AT = "2026-08-23T00:01:00Z"


def _budget() -> SemanticBudgetMeasurement:
    return SemanticBudgetMeasurement(diff_bytes=100, contract_bytes=100, evidence_bytes=100, pack_bytes=1000)


def _capsule() -> dict:
    return {
        "protocol_id": "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1",
        "version": "1.0",
        "authority": {
            "logical_role": "governance_release_assurance",
            "worker_instance": "B1",
            "semantic_verdict_present": False,
            "merge_authority": False,
            "release_authority": False,
        },
        "task": {
            "task_id": TASK_ID,
            "handover_id": HANDOVER_ID,
            "candidate_sha": CANDIDATE,
            "acceptance_criteria_sha256": "19491d7bfff1ecf40598f9e0924131564c27eb0d06090c208402f0d01a803fe1",
        },
        "claim": {
            "state": "ASSURANCE_EXECUTING",
            "active_run_id": "run-1",
            "active_role": "governance_release_assurance",
            "active_worker_instance": "B1",
            "lease_current_at_observation": True,
            "start_proven": True,
        },
        "diff": {
            "sha256": "f623deed686a9b4387589d5d628fe8ee9111765fe9c82193f9b4a16d3348a002",
            "bytes": 5,
            "content_embedded": False,
        },
        "source_digests": {
            "diff_sha256": "f623deed686a9b4387589d5d628fe8ee9111765fe9c82193f9b4a16d3348a002",
        },
        "deterministic_contradictions": [],
    }


def _build(capsule: dict):
    return build_semantic_pack(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        assurance_contract="Return one exact-head verdict.",
        acceptance_criteria=["Exact current lineage is START_PROVEN."],
        capsule=capsule,
        diff="+safe",
        bounded_evidence={},
    )


def _bot():
    return {"login": "chatgpt-codex-connector[bot]"}


def _review():
    return {
        "id": 1,
        "user": _bot(),
        "state": "COMMENTED",
        "commit_id": CANDIDATE,
        "body": "Codex Review",
        "submitted_at": CURRENT_AT,
    }


def _comment(body: str):
    return {
        "user": _bot(),
        "pull_request_review_id": 1,
        "commit_id": CANDIDATE,
        "body": body,
        "path": "control_engine/codex_b1.py",
        "line": 1,
        "created_at": CURRENT_AT,
    }


def _request_comment():
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


def test_quarantine_write_actuator_requires_deep_review():
    path = "scripts/quarantine_zta_legacy_repair.py"
    decision = classify_execution_surface(
        repository=CONTROL_ENGINE_REPOSITORY,
        changed_files=[path],
        budget=_budget(),
    )
    assert decision.work_required is True
    assert decision.reasons == (f"CONTROL_AUTHORITY_PATH:{path}",)


def test_semantic_pack_accepts_exact_b0_task_handover_claim_lineage():
    pack = _build(_capsule())
    assert pack["task_id"] == TASK_ID
    assert pack["handover_id"] == HANDOVER_ID
    assert pack["candidate_sha"] == CANDIDATE


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(protocol_id="WRONG_PROTOCOL"),
        lambda value: value["task"].update(task_id="OTHER_TASK"),
        lambda value: value["task"].update(handover_id="OTHER_HANDOVER"),
        lambda value: value["authority"].update(logical_role="implementation_operations"),
        lambda value: value["authority"].update(worker_instance="B2"),
        lambda value: value["claim"].update(active_role="implementation_operations"),
        lambda value: value["claim"].update(active_worker_instance="B2"),
        lambda value: value["claim"].update(active_run_id=""),
        lambda value: value["claim"].update(state="ASSURANCE_QUEUED"),
        lambda value: value["claim"].update(lease_current_at_observation=False),
        lambda value: value["claim"].update(lease_current_at_observation=None),
        lambda value: value["task"].update(acceptance_criteria_sha256="0" * 64),
        lambda value: value["diff"].update(sha256="0" * 64),
        lambda value: value["source_digests"].update(diff_sha256="0" * 64),
    ],
)
def test_semantic_pack_rejects_cross_lineage_wrong_authority_or_stale_evidence(mutate):
    capsule = copy.deepcopy(_capsule())
    mutate(capsule)
    with pytest.raises(CloudflareB1Error):
        _build(capsule)


def test_semantic_pack_rejects_substituted_semantic_inputs():
    with pytest.raises(CloudflareB1Error, match="acceptance criteria"):
        build_semantic_pack(
            task_id=TASK_ID,
            handover_id=HANDOVER_ID,
            candidate_sha=CANDIDATE,
            assurance_contract="Return one exact-head verdict.",
            acceptance_criteria=["weaker criterion"],
            capsule=_capsule(),
            diff="+safe",
            bounded_evidence={},
        )
    with pytest.raises(CloudflareB1Error, match="diff"):
        build_semantic_pack(
            task_id=TASK_ID,
            handover_id=HANDOVER_ID,
            candidate_sha=CANDIDATE,
            assurance_contract="Return one exact-head verdict.",
            acceptance_criteria=["Exact current lineage is START_PROVEN."],
            capsule=_capsule(),
            diff="+different",
            bounded_evidence={},
        )


def test_definite_codex_finding_that_mentions_marker_is_fail():
    result = classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_COMMENT_ID,
        reviews=[_review()],
        review_comments=[_comment(f"Definite defect: substring handling of {INDETERMINATE_MARKER} is unsafe")],
        trigger_reactions=[],
        issue_comments=[_request_comment()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"


def test_only_raw_finding_prefix_marks_codex_indeterminate():
    result = classify_review_snapshot(
        task_id=TASK_ID,
        handover_id=HANDOVER_ID,
        candidate_sha=CANDIDATE,
        request_comment_id=REQUEST_COMMENT_ID,
        reviews=[_review()],
        review_comments=[_comment(f"{INDETERMINATE_MARKER} exact required evidence is unavailable")],
        trigger_reactions=[],
        issue_comments=[_request_comment()],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "INDETERMINATE"
