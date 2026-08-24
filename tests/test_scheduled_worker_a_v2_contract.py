from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
RECONCILE = ROOT / "scripts" / "private_reconcile_apply.py"
CLAIM = ROOT / "scripts" / "private_a1_claim_apply.py"
BOUNDARY = ROOT / "docs" / "PUBLIC_PRIVATE_BOUNDARY_V1.md"
ACTUATOR = ROOT / "docs" / "PRIVATE_RUNTIME_ACTUATOR_V1.md"


def test_workflow_is_deterministic_lifecycle_backstop_not_semantic_worker() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Control deterministic runtime reconciler" in text
    assert "schedule:" in text
    assert "cron: '*/10 * * * *'" in text
    assert "workflow_dispatch:" in text
    assert "issue_comment:" in text
    assert "pull_request:" not in text
    assert "branches:\n      - main" in text
    assert "ref: main" in text
    assert "permissions:\n  contents: read\n  statuses: write" in text
    assert "persist-credentials: false" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text


def test_workflow_has_private_state_credentials_but_no_provider_a_credentials() -> None:
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
    ):
        assert forbidden not in text


def test_reconciliation_precedes_optional_claim_and_both_are_lifecycle_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    reconcile_pos = workflow.index("Reconcile canonical private runtime state")
    claim_pos = workflow.index("Persist exact preferred canonical A1 claim")
    assert reconcile_pos < claim_pos
    assert "python scripts/private_reconcile_apply.py" in workflow
    assert "python scripts/private_a1_claim_apply.py" in workflow

    reconcile = RECONCILE.read_text(encoding="utf-8")
    claim = CLAIM.read_text(encoding="utf-8")
    assert "control_project_intake_reconcile_v1.py" in reconcile
    assert "_remote_identity" in reconcile and "_persist(" in reconcile
    assert '"chatgpt-interactive/canonical-a1"' in claim
    assert '"--lease-minutes"' in claim
    assert "_remote_identity" in claim and "_persist(" in claim
    assert "principal_manual_relay_count" in claim
    for source in (reconcile, claim):
        assert "CONTROL_CLOUDFLARE_API_TOKEN" not in source
        assert "CONTROL_CLOUDFLARE_ACCOUNT_ID" not in source
        assert "run_workers_ai_once" not in source
        assert "@codex" not in source


def test_manual_claim_wake_is_exact_principal_authored_and_no_a3_exists() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.comment.user.login == 'market-predictions'" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_A1_CLAIM_V1 ')" in text
    assert "CONTROL_A1_CLAIM_V1 " in text
    assert "A3" not in text


def test_boundary_preserves_private_authority_while_public_runner_is_ephemeral() -> None:
    boundary = BOUNDARY.read_text(encoding="utf-8")
    actuator = ACTUATOR.read_text(encoding="utf-8")
    assert "PUBLIC RUNNER != SECOND CONTROL AUTHORITY" in boundary
    assert "transiently process private Control state" in boundary
    assert "no private runtime state is persisted or exposed" in boundary.lower()
    assert "Pull-request and fork workflows never receive the private-state execution path" in actuator
    assert "public repository's built-in `GITHUB_TOKEN` remains `contents: read`" in actuator
    assert "principal_manual_relay_count=0" in actuator
