from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
RECONCILE = ROOT / "scripts" / "private_reconcile_apply.py"
CLAIM = ROOT / "scripts" / "private_a1_claim_apply.py"


def test_lifecycle_surface_uses_exact_pinned_ephemeral_app_token() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1" in text
    assert "app-id: ${{ vars.CONTROL_GITHUB_APP_ID }}" in text
    assert "private-key: ${{ secrets.CONTROL_GITHUB_APP_PRIVATE_KEY }}" in text
    assert "owner: ${{ github.repository_owner }}" in text
    assert "permission-contents: 'write'" in text
    assert "permission-issues: 'write'" not in text
    assert "permission-actions: 'write'" not in text
    assert "permission-pull-requests: 'write'" not in text
    assert "skip-token-revoke" not in text


def test_builtin_token_is_read_only_and_private_writes_use_ephemeral_app_token() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n  statuses: write" in text
    top = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: write" not in top
    assert "issues: write" not in top
    assert "actions: write" not in top
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ steps.app-token.outputs.token }}" in text
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ secrets.CONTROL_GITHUB_WRITE_TOKEN }}" not in text


def test_runtime_reconcile_and_claim_wakes_are_trusted_and_bounded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron: '*/10 * * * *'" in text
    assert "workflow_dispatch:" in text
    assert "issue_comment:" in text
    assert "push:" in text
    assert "branches:\n      - main" in text
    assert "github.event.comment.user.login == 'market-predictions'" in text
    assert "github.event.comment.body == 'CONTROL_RUNTIME_RECONCILE_V1'" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_A1_CLAIM_V1 ')" in text
    assert "ref: main" in text
    assert "pull_request:" not in text


def test_public_workflow_contains_no_semantic_worker_a_compute_or_provider_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
        "scheduled_worker_a_v2_retry_guard.sh",
        "control-zero-relay-implementation.yml",
        "control-zero-relay-assurance.yml",
        "Reconcile, claim and execute one model-driven A1 task",
    ):
        assert forbidden not in text
    assert "WORKER_A_SEMANTIC_RUNTIME=CHATGPT_CHAT_ONLY" in text
    assert "GITHUB_ACTIONS_A_IMPLEMENTATION_INFERENCE=false" in text
    assert "PROVIDER_A_IMPLEMENTATION_INFERENCE=false" in text
    assert "CONTROL_GITHUB_ROLE=DETERMINISTIC_LIFECYCLE_ONLY" in text


def test_reconciler_and_claim_actuator_are_state_only_with_cas() -> None:
    reconcile = RECONCILE.read_text(encoding="utf-8")
    claim = CLAIM.read_text(encoding="utf-8")
    assert "control_project_intake_reconcile_v1.py" in reconcile
    assert "_remote_identity" in reconcile and "_persist(" in reconcile
    assert '"claim"' in claim
    assert '"chatgpt-interactive/canonical-a1"' in claim
    assert "_remote_identity" in claim and "_persist(" in claim
    assert '"implementation_operations"' in claim
    assert '"A1"' in claim
    assert "principal_manual_relay_count" in claim
    for text in (reconcile, claim):
        assert "CONTROL_CLOUDFLARE_API_TOKEN" not in text
        assert "CONTROL_CLOUDFLARE_ACCOUNT_ID" not in text
        assert "run_workers_ai_once" not in text
        assert "@codex" not in text


def test_public_liveness_status_is_non_semantic_and_bounded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'context="control/runtime-reconciler"' in text
    assert "DETERMINISTIC_RUNTIME_RECONCILE_OK" in text
    assert "DETERMINISTIC_RUNTIME_RECONCILE_FAILED" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
