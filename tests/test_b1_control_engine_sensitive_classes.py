import pytest

from control_engine.cloudflare_b1 import (
    CONTROL_ENGINE_REPOSITORY,
    SemanticBudgetMeasurement,
    classify_execution_surface,
)


def _budget() -> SemanticBudgetMeasurement:
    return SemanticBudgetMeasurement(diff_bytes=100, contract_bytes=100, evidence_bytes=100, pack_bytes=1000)


@pytest.mark.parametrize(
    "path",
    [
        "control_engine/new_executor.py",
        "scripts/new_control_actuator.py",
        ".github/workflows/cloudflare-assurance-preflight-v1.yml",
        ".github/workflows/groq-standby-preflight-v1.yml",
        "docs/PRIVATE_RUNTIME_ASSURANCE_ACTUATOR_V1.md",
        "schemas/control_project_progress_event_v1.schema.json",
        "ENGINE_MANIFEST.json",
        "ENGINE_BUNDLE_V1.json",
    ],
)
def test_control_engine_infrastructure_classes_route_deep_by_default(path):
    decision = classify_execution_surface(
        repository=CONTROL_ENGINE_REPOSITORY,
        changed_files=[path],
        budget=_budget(),
    )
    assert decision.work_required is True
    assert decision.reasons == (f"CONTROL_AUTHORITY_PATH:{path}",)


@pytest.mark.parametrize("path", ["tests/test_widget.py", "fixtures/example.json"])
def test_non_authority_test_and_fixture_paths_remain_standard_when_otherwise_safe(path):
    decision = classify_execution_surface(
        repository=CONTROL_ENGINE_REPOSITORY,
        changed_files=[path],
        budget=_budget(),
    )
    assert decision.cloudflare_eligible is True
    assert decision.reasons == ()
