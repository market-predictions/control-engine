from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
DIAGNOSTIC = ROOT / "scripts" / "private_intake_diagnostic.py"
MIGRATION = ROOT / "scripts" / "quarantine_zta_legacy_repair.py"
INTEGRATION = ROOT / "scripts" / "project_integration_executor.py"


def test_retired_workflow_has_no_github_app_or_private_write_bridge() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/create-github-app-token" not in text
    assert "CONTROL_GITHUB_WRITE_TOKEN" not in text
    assert "CONTROL_GITHUB_APP_ID" not in text
    assert "CONTROL_GITHUB_APP_PRIVATE_KEY" not in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "issues: write" not in text
    assert "actions: write" not in text


def test_retired_workflow_has_no_schedule_push_or_provider_execution() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "push:" not in text
    assert "workflow_dispatch:" in text
    assert "CONTROL_CLOUDFLARE_API_TOKEN" not in text
    assert "CONTROL_CLOUDFLARE_ACCOUNT_ID" not in text
    assert "CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED" not in text
    assert "inference_worker.py" not in text
    assert "scheduled_worker_a_v2_retry_guard.sh" not in text
    assert "Reconcile, claim and execute one model-driven A1 task" not in text


def test_retired_workflow_cannot_mutate_private_intake_or_integration_state() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Publish private intake diagnostic receipt" not in text
    assert "Quarantine exact legacy ZTA PR7 repair intake" not in text
    assert "Execute preferred deterministic PROJECT_INTEGRATION" not in text
    assert "private_intake_diagnostic.py" not in text
    assert "quarantine_zta_legacy_repair.py" not in text
    assert "project_integration_executor.py" not in text


def test_retirement_proof_is_bounded_and_nonsemantic() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.repository == 'market-predictions/control-engine'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "CONTROL_SCHEDULED_WORKER_A_V2=RETIRED_SEMANTIC_EXECUTOR" in text
    assert "WORKER_A_SEMANTIC_RUNTIME=CHATGPT_CHAT_ONLY" in text
    assert "GITHUB_ACTIONS_A_IMPLEMENTATION_INFERENCE=false" in text
    assert "PROVIDER_A_IMPLEMENTATION_INFERENCE=false" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text


def test_retired_support_scripts_remain_non_force_historical_components() -> None:
    diagnostic = DIAGNOSTIC.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")
    integration = INTEGRATION.read_text(encoding="utf-8")

    assert 'RECOVERY_ISSUE = 187' in diagnostic
    assert 'MARKER = "<!-- scheduled-worker-a-v2-private-intake-diagnostic -->"' in diagnostic
    assert "--force" not in migration
    assert 'TASK_ID = "ZTA-PR7-WRANGLER-REPAIR"' in migration
    assert "evaluate_claimed_project_integration" in integration
    assert '"sha": candidate_sha' in integration
    assert '"merge_method": "merge"' in integration
    assert "--force" not in integration
