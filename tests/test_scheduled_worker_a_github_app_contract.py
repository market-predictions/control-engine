from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
BRIDGE = ROOT / "scripts" / "private_minimal_core_apply.py"
KERNEL = ROOT / "control_engine" / "minimal_core.py"


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


def test_minimal_core_actuator_is_trusted_bounded_and_not_a_scheduler() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "push:" not in text
    assert "workflow_dispatch:" in text
    assert "issue_comment:" in text
    assert "github.event.comment.user.login == 'market-predictions'" in text
    assert "CONTROL_CORE_RECONCILE_V1" in text
    assert "CONTROL_CORE_CLAIM_V1 " in text
    assert "CONTROL_CORE_RECORD_V1 " in text
    assert "ref: main" in text
    assert "pull_request:" not in text
    assert "GITHUB_ACTIONS_WORKER_SCHEDULER=false" in text
    assert "CHATGPT_ROLE_WORKERS_WAKE=true" in text


def test_public_workflow_contains_no_semantic_compute_or_provider_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
        "run_workers_ai_once",
        "@codex",
        "scheduled_worker_a_v2_retry_guard.sh",
    ):
        assert forbidden not in text
    assert "GITHUB_ACTIONS_SEMANTIC_IMPLEMENTATION=false" in text
    assert "GITHUB_ACTIONS_SEMANTIC_ASSURANCE=false" in text
    assert "CONTROL_GITHUB_ROLE=DETERMINISTIC_LIFECYCLE_ONLY" in text
    assert "SECOND_QUEUE=false" in text
    assert "TASK_SPECIFIC_RECOVERY=false" in text


def test_minimal_core_bridge_is_single_state_only_cas_surface() -> None:
    bridge = BRIDGE.read_text(encoding="utf-8")
    kernel = KERNEL.read_text(encoding="utf-8")
    assert "_remote_identity" in bridge and "_persist(" in bridge
    assert "control/project-intake" not in bridge
    assert "control/handovers" not in bridge
    assert "control/claim-completions" not in bridge
    assert "CONTROL_MINIMAL_CORE_V1" in kernel
    assert "PASS" in kernel and "FAIL" in kernel and "INDETERMINATE" in kernel
    assert "LEASE_EXPIRED" in kernel
    for text in (bridge, kernel):
        assert "CONTROL_CLOUDFLARE_API_TOKEN" not in text
        assert "CONTROL_CLOUDFLARE_ACCOUNT_ID" not in text
        assert "run_workers_ai_once" not in text
        assert "@codex" not in text


def test_public_liveness_status_is_manual_actuator_only_and_non_semantic() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event_name == 'workflow_dispatch'" in text
    assert 'context="control/minimal-core"' in text
    assert "CONTROL_MINIMAL_CORE_OK" in text
    assert "CONTROL_MINIMAL_CORE_FAILED" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
