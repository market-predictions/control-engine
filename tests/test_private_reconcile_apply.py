from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_RECONCILE = ROOT / "scripts" / "private_reconcile_apply.py"
LEGACY_CLAIM = ROOT / "scripts" / "private_a1_claim_apply.py"
LEGACY_RECORD = ROOT / "scripts" / "private_a1_record_apply.py"
MINIMAL_BRIDGE = ROOT / "scripts" / "private_minimal_core_apply.py"
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"


def test_legacy_reconciler_remains_audit_compatible_but_is_not_active_path():
    text = LEGACY_RECONCILE.read_text(encoding="utf-8")
    assert "control_superseded_intake_reconcile_v1.py" in text
    assert "control_project_intake_reconcile_v1.py" in text
    assert "dispatcher_reconcile" in text
    assert "queue_validate" in text
    assert "_remote_identity" in text
    assert "_persist(" in text
    assert 'RECONCILE_CODE_REF = "control/171-intake-queue-reconciliation-v1"' in text
    assert 'RECONCILE_CODE_SHA = "265c6e607c3735f6e98bb74d1f1ba6162e5e9b79"' in text
    assert "private_reconcile_apply.py" not in WORKFLOW.read_text(encoding="utf-8")


def test_legacy_claim_and_record_remain_non_semantic_audit_artifacts():
    claim = LEGACY_CLAIM.read_text(encoding="utf-8")
    record = LEGACY_RECORD.read_text(encoding="utf-8")
    assert '"chatgpt-interactive/canonical-a1"' in claim
    assert "principal_manual_relay_count" in claim
    assert '"worker-results"' in record
    assert "principal_manual_relay_count" in record
    for text in (claim, record):
        for token in ("CONTROL_CLOUDFLARE_API_TOKEN", "CONTROL_CLOUDFLARE_ACCOUNT_ID", "run_workers_ai_once", "@codex"):
            assert token not in text


def test_minimal_bridge_replaces_three_active_lifecycle_surfaces_with_one():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    bridge = MINIMAL_BRIDGE.read_text(encoding="utf-8")
    assert "private_minimal_core_apply.py" in workflow
    assert "private_reconcile_apply.py" not in workflow
    assert "private_a1_claim_apply.py" not in workflow
    assert "private_a1_record_apply.py" not in workflow
    assert "CONTROL_CORE_RECONCILE_V1" in workflow
    assert "CONTROL_CORE_CLAIM_V1 A1" in workflow
    assert "CONTROL_CORE_CLAIM_V1 B1" in workflow
    assert "CONTROL_CORE_RECORD_V1 " in workflow
    assert "github.event.comment.user.login == 'market-predictions'" in workflow
    assert "_remote_identity" in bridge and "_persist(" in bridge
    assert "control/project-intake" not in bridge
    assert "control/handovers" not in bridge
    assert "control/claim-completions" not in bridge
    assert "CONTROL_GITHUB_APP_PRIVATE_KEY" in workflow
    assert "permission-contents: 'write'" in workflow
    assert "cron: '*/10 * * * *'" in workflow
    for token in (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "scheduled_worker_a_v2_retry_guard.sh",
        "control-zero-relay-implementation.yml",
        "control-zero-relay-assurance.yml",
        "gh workflow run",
    ):
        assert token not in workflow
