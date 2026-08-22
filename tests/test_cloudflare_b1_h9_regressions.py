import pytest

from control_engine.cloudflare_b1 import (
    CONTROL_ENGINE_REPOSITORY,
    CloudflareB1ExecutionUnavailable,
    SemanticBudgetMeasurement,
    classify_execution_surface,
    parse_verdict_response,
)

CANDIDATE = "a" * 40
VALID_PASS = (
    '{"candidate_sha":"' + CANDIDATE + '","verdict":"PASS",'
    '"summary":"all criteria supported","findings":[]}'
)


def _budget() -> SemanticBudgetMeasurement:
    return SemanticBudgetMeasurement(diff_bytes=100, contract_bytes=100, evidence_bytes=100, pack_bytes=1000)


def _payload(*, finish_reason_marker="stop") -> dict:
    choice = {"message": {"role": "assistant", "content": VALID_PASS}}
    if finish_reason_marker != "__MISSING__":
        choice["finish_reason"] = finish_reason_marker
    return {"choices": [choice]}


def test_shared_b1_github_app_credential_preflight_requires_deep_review():
    path = "scripts/github_app_preflight.sh"
    decision = classify_execution_surface(
        repository=CONTROL_ENGINE_REPOSITORY,
        changed_files=[path],
        budget=_budget(),
    )
    assert decision.work_required is True
    assert decision.reasons == (f"CONTROL_AUTHORITY_PATH:{path}",)


@pytest.mark.parametrize("finish_reason", ["__MISSING__", "content_filter", "tool_calls"])
def test_only_explicit_stop_finish_reason_can_reach_semantic_verdict(finish_reason):
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        parse_verdict_response(_payload(finish_reason_marker=finish_reason), candidate_sha=CANDIDATE)
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_CONTRACT"


def test_length_finish_reason_retains_specific_truncation_code():
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        parse_verdict_response(_payload(finish_reason_marker="length"), candidate_sha=CANDIDATE)
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_OUTPUT_TRUNCATED"
