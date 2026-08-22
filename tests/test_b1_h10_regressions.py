import copy

import pytest

from control_engine.cloudflare_b1 import (
    CONTROL_ENGINE_REPOSITORY,
    CloudflareB1Error,
    SemanticBudgetMeasurement,
    build_semantic_pack,
    classify_execution_surface,
)
from control_engine.codex_b1 import INDETERMINATE_MARKER, classify_review_snapshot

CANDIDATE = "a" * 40


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
            "task_id": "T1",
            "handover_id": "H1",
            "candidate_sha": CANDIDATE,
        },
        "claim": {
            "active_run_id": "run-1",
            "active_role": "governance_release_assurance",
            "active_worker_instance": "B1",
            "start_proven": True,
        },
        "deterministic_contradictions": [],
    }


def _build(capsule: dict):
    return build_semantic_pack(
        task_id="T1",
        handover_id="H1",
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
    return {"id": 1, "user": _bot(), "commit_id": CANDIDATE, "body": "Codex Review"}


def _comment(body: str):
    return {
        "user": _bot(),
        "pull_request_review_id": 1,
        "commit_id": CANDIDATE,
        "body": body,
        "path": "control_engine/codex_b1.py",
        "line": 1,
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
    assert pack["task_id"] == "T1"
    assert pack["handover_id"] == "H1"
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
    ],
)
def test_semantic_pack_rejects_cross_lineage_or_wrong_authority_capsules(mutate):
    capsule = copy.deepcopy(_capsule())
    mutate(capsule)
    with pytest.raises(CloudflareB1Error):
        _build(capsule)


def test_definite_codex_finding_that_mentions_marker_is_fail():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[_review()],
        review_comments=[_comment(f"Definite defect: substring handling of {INDETERMINATE_MARKER} is unsafe")],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "FAIL"


def test_only_raw_finding_prefix_marks_codex_indeterminate():
    result = classify_review_snapshot(
        candidate_sha=CANDIDATE,
        reviews=[_review()],
        review_comments=[_comment(f"{INDETERMINATE_MARKER} exact required evidence is unavailable")],
        trigger_reactions=[],
    )
    assert result.status == "COMPLETE"
    assert result.verdict == "INDETERMINATE"
