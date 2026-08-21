from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"


def test_scheduled_worker_uses_exact_pinned_github_app_token_action() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1" in text
    assert "app-id: ${{ vars.CONTROL_GITHUB_APP_ID }}" in text
    assert "private-key: ${{ secrets.CONTROL_GITHUB_APP_PRIVATE_KEY }}" in text
    assert "owner: ${{ github.repository_owner }}" in text
    assert "permission-contents: 'write'" in text
    assert "permission-workflows: 'write'" in text


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
    assert "'control_engine/scheduled_worker_a.py'" in text


def test_public_liveness_status_is_bounded_and_does_not_echo_worker_output() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "context=\"control/scheduled-worker-a-v2\"" in text
    assert "APP_TOKEN_CREATION_FAILED" in text
    assert "RUNTIME_SKIPPED_OR_UNCLASSIFIED" in text
    assert "status_class=RUNTIME_FAILED_NO_STATUS" in text
    assert 'printf \'%s\\n\' "$output"' in text
    assert 'echo "$output"' not in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
