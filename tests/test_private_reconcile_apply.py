from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "private_reconcile_apply.py"
CLAIM = ROOT / "scripts" / "private_a1_claim_apply.py"
RECORD = ROOT / "scripts" / "private_a1_record_apply.py"
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"


def test_reconciler_is_deterministic_state_only():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "control_superseded_intake_reconcile_v1.py" in text
    assert "superseded_intake_reconcile" in text
    assert "control_project_intake_reconcile_v1.py" in text
    assert "dispatcher_reconcile" in text
    assert "queue_validate" in text
    assert "_remote_identity" in text
    assert "_persist(" in text
    assert "control/DISPATCH_QUEUE.json" in text
    assert "control/DISPATCH_RUNS.json" in text
    assert 'RECONCILE_CODE_REF = "control/171-intake-queue-reconciliation-v1"' in text
    assert 'RECONCILE_CODE_SHA = "265c6e607c3735f6e98bb74d1f1ba6162e5e9b79"' in text
    assert text.index("dispatcher_reconcile") < text.index("superseded_intake_reconcile")
    assert text.index("superseded_intake_reconcile") < text.index("project_intake_reconcile")
    for token in (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "scheduled_worker_a_v2_retry_guard",
        "control-zero-relay-implementation.yml",
        "control-zero-relay-assurance.yml",
        "claim_task",
        "claim_selected",
    ):
        assert token not in text
    assert "invoke semantic inference" in text.lower()


def test_claim_actuator_is_lifecycle_only_and_uses_canonical_claim():
    text = CLAIM.read_text(encoding="utf-8")
    assert '"claim"' in text
    assert '"chatgpt-interactive/canonical-a1"' in text
    assert '"--lease-minutes"' in text
    assert "_remote_identity" in text and "_persist(" in text
    assert '"IMPLEMENTATION_EXECUTING"' in text
    assert '"REPAIR_EXECUTING"' in text
    assert '"implementation_operations"' in text
    assert '"A1"' in text
    assert "principal_manual_relay_count" in text
    for token in ("CONTROL_CLOUDFLARE_API_TOKEN", "CONTROL_CLOUDFLARE_ACCOUNT_ID", "run_workers_ai_once", "@codex"):
        assert token not in text


def test_record_actuator_uses_pre_staged_private_result_and_canonical_record():
    text = RECORD.read_text(encoding="utf-8")
    assert '"worker-results"' in text
    assert '"record"' in text
    assert '"--result"' in text
    assert '"implementation_operations"' in text
    assert '"COMPLETED"' in text
    assert '"BLOCKED"' in text
    assert '"EXECUTION_UNAVAILABLE"' in text
    assert "_remote_identity" in text and "_persist(" in text
    assert "active_run_id" in text
    assert "principal_manual_relay_count" in text
    for token in ("CONTROL_CLOUDFLARE_API_TOKEN", "CONTROL_CLOUDFLARE_ACCOUNT_ID", "run_workers_ai_once", "@codex"):
        assert token not in text


def test_workflow_runs_reconcile_claim_record_lifecycle_but_not_worker_a_compute():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "private_reconcile_apply.py" in text
    assert "private_a1_claim_apply.py" in text
    assert "private_a1_record_apply.py" in text
    assert "CONTROL_GITHUB_APP_PRIVATE_KEY" in text
    assert "permission-contents: 'write'" in text
    assert "cron: '*/10 * * * *'" in text
    assert "issue_comment:" in text
    assert "CONTROL_RUNTIME_RECONCILE_V1" in text
    assert "CONTROL_A1_CLAIM_V1 " in text
    assert "CONTROL_A1_RECORD_V1 " in text
    assert "github.event.comment.user.login == 'market-predictions'" in text
    assert "github.event.comment.body == 'CONTROL_RUNTIME_RECONCILE_V1'" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_A1_CLAIM_V1 ')" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_A1_RECORD_V1 ')" in text
    for token in (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "scheduled_worker_a_v2_retry_guard.sh",
        "control-zero-relay-implementation.yml",
        "control-zero-relay-assurance.yml",
        "gh workflow run",
        "Reconcile, claim and execute one model-driven A1 task",
    ):
        assert token not in text
