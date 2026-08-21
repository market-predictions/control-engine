from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
DIAGNOSTIC = ROOT / "scripts" / "private_intake_diagnostic.py"
MIGRATION = ROOT / "scripts" / "quarantine_zta_legacy_repair.py"


def test_scheduled_worker_uses_exact_pinned_github_app_token_action() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1" in text
    assert "app-id: ${{ vars.CONTROL_GITHUB_APP_ID }}" in text
    assert "private-key: ${{ secrets.CONTROL_GITHUB_APP_PRIVATE_KEY }}" in text
    assert "owner: ${{ github.repository_owner }}" in text
    assert "permission-contents: 'write'" in text
    assert "permission-issues: 'write'" in text
    app_block = text.split("Create short-lived Control GitHub App token", 1)[1].split("Setup Python", 1)[0]
    assert "permission-workflows" not in app_block
    assert "permission-pull-requests" not in app_block


def test_long_lived_pat_is_not_executable_bridge() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ steps.app-token.outputs.token }}" in text
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ secrets.CONTROL_GITHUB_WRITE_TOKEN }}" not in text
    runtime_block = text.split("Reconcile, claim and execute one A1 task", 1)[1].split("Publish non-sensitive liveness status", 1)[0]
    assert "github.token }}" not in runtime_block


def test_builtin_github_token_stays_contents_read_only_and_app_token_is_ephemeral() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n  statuses: write" in text
    top_permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: write" not in top_permissions
    assert "issues: write" not in top_permissions
    assert "actions: write" not in top_permissions
    assert "skip-token-revoke" not in text
    assert "pull_request:" not in text


def test_deployment_wake_is_main_only_and_actuator_path_bounded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "branches:\n      - main" in text
    assert "paths:" in text
    assert "'.github/workflows/scheduled-worker-a-v2.yml'" in text
    assert "'scripts/scheduled_worker_a_v2.sh'" in text
    assert "'scripts/github_app_preflight.sh'" in text
    assert "'scripts/private_intake_diagnostic.py'" in text
    assert "'scripts/quarantine_zta_legacy_repair.py'" in text
    assert "'control_engine/scheduled_worker_a.py'" in text


def test_private_intake_diagnostic_uses_only_app_token_and_private_issue_receipt() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    diagnostic = DIAGNOSTIC.read_text(encoding="utf-8")
    diagnostic_block = workflow.split("Publish private intake diagnostic receipt", 1)[1].split("Reconcile, claim and execute one A1 task", 1)[0]
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ steps.app-token.outputs.token }}" in diagnostic_block
    assert "github.token }}" not in diagnostic_block
    assert 'RECOVERY_ISSUE = 187' in diagnostic
    assert 'MARKER = "<!-- scheduled-worker-a-v2-private-intake-diagnostic -->"' in diagnostic
    assert "issues/{RECOVERY_ISSUE}/comments" in diagnostic
    assert "actions/upload-artifact" not in workflow
    assert "actions/cache" not in workflow


def test_legacy_zta_quarantine_is_exact_bounded_and_runs_before_reconciliation() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    migration = MIGRATION.read_text(encoding="utf-8")
    assert 'TASK_ID = "ZTA-PR7-WRANGLER-REPAIR"' in migration
    assert 'R1 = "ZTA-PR7-WRANGLER-REPAIR-R1"' in migration
    assert 'R2 = "ZTA-PR7-WRANGLER-REPAIR-R2"' in migration
    assert 'INTAKE_PATH = Path("control/project-intake/ZORGTECHADVIES_PR7.json")' in migration
    assert 'QUEUE_PATH = Path("control/DISPATCH_QUEUE.json")' in migration
    assert 'intent.get("handover_id") is None' in migration
    assert 'intent.get("assurance_result_ref") is None' in migration
    assert 'task["paused"] = True' in migration
    assert 'intake["queue_intent"] = None' in migration
    assert "--force" not in migration
    migration_pos = workflow.index("Quarantine exact legacy ZTA PR7 repair intake")
    diagnostic_pos = workflow.index("Publish private intake diagnostic receipt")
    runtime_pos = workflow.index("Reconcile, claim and execute one A1 task")
    assert migration_pos < diagnostic_pos < runtime_pos
    assert "steps.legacy-zta-migration.outcome == 'success'" in workflow
    assert "LEGACY_ZTA_MIGRATION_FAILED" in workflow


def test_public_liveness_status_is_bounded_and_does_not_echo_worker_output() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "context=\"control/swa-v2/${description}\"" in text
    assert "APP_TOKEN_CREATION_FAILED" in text
    assert "RUNTIME_SKIPPED_OR_UNCLASSIFIED" in text
    assert "status_class=RUNTIME_FAILED_NO_STATUS" in text
    assert 'printf \'%s\\n\' "$output"' in text
    assert 'echo "$output"' not in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
