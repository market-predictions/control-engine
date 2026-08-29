from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "private-control-deterministic-validation-v1.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_carrier_preserves_single_existing_operator_surface_and_read_only_permissions() -> None:
    text = workflow_text()
    assert "CONTROL_PRIVATE_VALIDATE_V1 " in text
    assert "workflow_dispatch:" in text
    assert "issue_comment:" in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "pull-requests: write" not in text
    assert "github.event.comment.user.login == 'market-predictions'" in text
    assert "github.ref == 'refs/heads/main'" in text


def test_carrier_is_exact_sha_bound_and_uses_ephemeral_private_read_token_only_for_fetch() -> None:
    text = workflow_text()
    assert "[[ \"$candidate_sha\" =~ ^[0-9a-f]{40}$ ]]" in text
    assert "[[ \"$CANDIDATE_SHA\" =~ ^[0-9a-f]{40}$ ]]" in text
    assert "permission-contents: 'read'" in text
    assert "test \"$(git -C \"$repo\" rev-parse HEAD)\" = \"$CANDIDATE_SHA\"" in text
    assert "unset CONTROL_GITHUB_READ_TOKEN auth_header" in text
    assert text.index("unset CONTROL_GITHUB_READ_TOKEN auth_header") < text.index("python -m py_compile")


def test_carrier_validates_current_minimal_core_feed_and_doctrine_not_retired_runtime_profile() -> None:
    text = workflow_text()
    assert "test_control_minimal_mission_feed_v1.py" in text
    assert "test_mission_contract_v1.py" in text
    assert "tools/control_minimal_mission_feed_v1.py" in text
    assert "tools/mission_contract_v1.py" in text
    assert "profile=CONTROL_MINIMAL_CORE_V1" in text
    assert "runtime_model=CONTROL_MINIMAL_CORE_V1" in text
    assert "mandatory_convergence_cleanup=true" in text
    assert ":20  GitHub deterministic reconcile -> Feed queue" in text
    assert ":30  ChatGPT A1" in text
    assert ":35  ChatGPT A2" in text
    assert ":55  ChatGPT B1" in text

    for retired_test in (
        "test_control_queue_v1.py",
        "test_control_orchestration_v1.py",
        "test_control_stale_queue_inertness_v1.py",
    ):
        assert retired_test not in text


def test_carrier_fails_closed_without_private_source_or_test_log_leakage() -> None:
    text = workflow_text()
    assert ') >"$log" 2>&1' in text
    assert "CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=FAIL" in text
    assert "CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=PASS" in text
    assert "cat \"$log\"" not in text
    assert "upload-artifact" not in text
    assert "private-validation.log" in text
    assert "trap 'rm -rf \"$root\"' EXIT" in text


def test_carrier_proves_legacy_entrypoints_remain_fail_closed() -> None:
    text = workflow_text()
    for path in (
        ".github/workflows/control-manual-run-delivery.yml",
        ".github/workflows/control-zero-relay-dispatch.yml",
        ".github/workflows/control-zero-relay-implementation.yml",
        ".github/workflows/control-zero-relay-assurance.yml",
        ".github/workflows/control-zero-relay-provider-preflight.yml",
    ):
        assert path in text
    assert "grep -Fq '[RETIRED]'" in text
    assert "! grep -Fq 'contents: write'" in text
    assert "! grep -Fq 'actions: write'" in text
