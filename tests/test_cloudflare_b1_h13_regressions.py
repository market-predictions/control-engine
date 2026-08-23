import hashlib
import json

import pytest

from control_engine.cloudflare_b1 import (
    CONTROL_ENGINE_REPOSITORY,
    CloudflareB1Error,
    CloudflareB1ExecutionUnavailable,
    SemanticBudgetMeasurement,
    build_semantic_pack,
    classify_execution_surface,
)

CANDIDATE = "a" * 40
CRITERIA = ["Exact current lineage is START_PROVEN."]
DIFF = "+safe"


def _json_digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _budget() -> SemanticBudgetMeasurement:
    return SemanticBudgetMeasurement(diff_bytes=100, contract_bytes=100, evidence_bytes=100, pack_bytes=1000)


def _capsule() -> dict:
    diff_digest = hashlib.sha256(DIFF.encode("utf-8")).hexdigest()
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
            "repository": CONTROL_ENGINE_REPOSITORY,
            "handover_id": "H1",
            "candidate_sha": CANDIDATE,
            "acceptance_criteria_sha256": _json_digest(CRITERIA),
        },
        "claim": {
            "state": "ASSURANCE_EXECUTING",
            "active_run_id": "run-1",
            "active_role": "governance_release_assurance",
            "active_worker_instance": "B1",
            "lease_current_at_observation": True,
            "start_proven": True,
        },
        "changed_files": ["tests/test_widget.py"],
        "diff": {
            "sha256": diff_digest,
            "bytes": len(DIFF.encode("utf-8")),
            "content_embedded": False,
        },
        "source_digests": {"diff_sha256": diff_digest},
        "deterministic_contradictions": [],
    }


def _build(capsule: dict):
    return build_semantic_pack(
        task_id="T1",
        handover_id="H1",
        candidate_sha=CANDIDATE,
        assurance_contract="Return one exact-head verdict.",
        acceptance_criteria=CRITERIA,
        capsule=capsule,
        diff=DIFF,
        bounded_evidence={},
    )


def test_standard_control_routing_requires_exact_b0_changed_files():
    capsule = _capsule()
    capsule["changed_files"] = ["control_engine/cloudflare_b1.py"]
    with pytest.raises(CloudflareB1Error, match="changed_files do not match B0 routing evidence"):
        classify_execution_surface(
            repository=CONTROL_ENGINE_REPOSITORY,
            changed_files=["tests/test_widget.py"],
            budget=_budget(),
            capsule=capsule,
        )


def test_standard_control_routing_rejects_missing_b0_capsule():
    with pytest.raises(CloudflareB1Error, match="B0 capsule is required"):
        classify_execution_surface(
            repository=CONTROL_ENGINE_REPOSITORY,
            changed_files=["tests/test_widget.py"],
            budget=_budget(),
        )


@pytest.mark.parametrize("invalid", [None, {}, ["UNRESOLVED"]])
def test_semantic_pack_requires_explicit_empty_contradiction_list(invalid):
    capsule = _capsule()
    capsule["deterministic_contradictions"] = invalid
    with pytest.raises(CloudflareB1Error, match="explicit empty contradiction list"):
        _build(capsule)


def test_semantic_pack_rejects_missing_contradiction_evidence():
    capsule = _capsule()
    del capsule["deterministic_contradictions"]
    with pytest.raises(CloudflareB1Error, match="explicit empty contradiction list"):
        _build(capsule)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_provider_response_must_be_utf8(monkeypatch, encoding):
    from control_engine import cloudflare_b1

    class NonUtf8Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit):
            assert limit == 1_000_001
            return json.dumps({"choices": []}).encode(encoding)

    monkeypatch.setattr(cloudflare_b1.urllib.request, "urlopen", lambda *_args, **_kwargs: NonUtf8Response())
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        cloudflare_b1.run_workers_ai_once(
            account_id="account_1",
            api_token="secret-token",
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        )
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_UNPARSEABLE"
