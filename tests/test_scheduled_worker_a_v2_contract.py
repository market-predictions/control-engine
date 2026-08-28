from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
BRIDGE = ROOT / "scripts" / "private_minimal_core_apply.py"
KERNEL = ROOT / "control_engine" / "minimal_core.py"
BOUNDARY = ROOT / "docs" / "PUBLIC_PRIVATE_BOUNDARY_V1.md"
ACTUATOR = ROOT / "docs" / "PRIVATE_RUNTIME_ACTUATOR_V1.md"


def test_workflow_is_deterministic_actuator_not_worker_scheduler() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Control Minimal Core lifecycle actuator" in text
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "push:" not in text
    assert "workflow_dispatch:" in text
    assert "issue_comment:" in text
    assert "pull_request:" not in text
    assert "ref: main" in text
    assert "permissions:\n  contents: read\n  statuses: write" in text
    assert "persist-credentials: false" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
    assert "GITHUB_ACTIONS_WORKER_SCHEDULER=false" in text
    assert "CHATGPT_ROLE_WORKERS_WAKE=true" in text


def test_workflow_has_private_state_credentials_but_no_semantic_provider_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "vars.CONTROL_GITHUB_APP_ID" in text
    assert "secrets.CONTROL_GITHUB_APP_PRIVATE_KEY" in text
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ steps.app-token.outputs.token }}" in text
    assert "secrets.CONTROL_GITHUB_WRITE_TOKEN" not in text
    for forbidden in (
        "secrets.CONTROL_CLOUDFLARE_API_TOKEN",
        "secrets.CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
        "scheduled_worker_a_v2.sh",
        "scheduled_worker_a_v2_retry_guard.sh",
        "@codex",
    ):
        assert forbidden not in text


def test_single_bridge_handles_reconcile_claim_and_record_without_intake_projection() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")
    kernel = KERNEL.read_text(encoding="utf-8")
    assert "python scripts/private_minimal_core_apply.py reconcile" in workflow
    assert "python scripts/private_minimal_core_apply.py claim --worker-instance A1" in workflow
    assert "python scripts/private_minimal_core_apply.py claim --worker-instance A2" in workflow
    assert "python scripts/private_minimal_core_apply.py claim --worker-instance B1" in workflow
    assert "python scripts/private_minimal_core_apply.py record --task-id" in workflow
    assert "control_project_intake_reconcile_v1.py" not in workflow
    assert "control/project-intake" not in bridge
    assert "control/handovers" not in bridge
    assert "control/claim-completions" not in bridge
    assert "successor_by_outcome" in kernel
    assert "persisted_results" in kernel
    assert "LEASE_EXPIRED" in kernel
    assert "principal_manual_relay_count" in kernel


def test_trusted_actuator_commands_are_exact_and_only_a1_a2_b1_exist() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.comment.user.login == 'market-predictions'" in text
    assert "CONTROL_CORE_CLAIM_V1 A1" in text
    assert "CONTROL_CORE_CLAIM_V1 A2" in text
    assert "CONTROL_CORE_CLAIM_V1 B1" in text
    assert "A3" not in text
    assert "B2" not in text
    assert "B3" not in text


def test_boundary_preserves_private_authority_while_public_runner_is_ephemeral() -> None:
    boundary = BOUNDARY.read_text(encoding="utf-8")
    actuator = ACTUATOR.read_text(encoding="utf-8")
    assert "PUBLIC RUNNER != SECOND CONTROL AUTHORITY" in boundary
    assert "transiently process private Control state" in boundary
    assert "no private runtime state is persisted or exposed" in boundary.lower()
    assert "Pull-request and fork workflows never receive the private-state execution path" in actuator
    assert "public repository's built-in `GITHUB_TOKEN` remains `contents: read`" in actuator
    assert "principal_manual_relay_count=0" in actuator
