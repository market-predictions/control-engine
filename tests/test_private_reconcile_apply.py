from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "private_reconcile_apply.py"
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"


def test_reconciler_is_deterministic_state_only():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "control_project_intake_reconcile_v1.py" in text
    assert "dispatcher_reconcile" in text
    assert "queue_validate" in text
    assert "_remote_identity" in text
    assert "_persist(" in text
    assert "control/DISPATCH_QUEUE.json" in text
    assert "control/DISPATCH_RUNS.json" in text

    forbidden = (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "scheduled_worker_a_v2_retry_guard",
        "control-zero-relay-implementation.yml",
        "control-zero-relay-assurance.yml",
        "claim_task",
        "claim_selected",
        "semantic",
        "inference",
    )
    lowered = text.lower()
    for token in forbidden:
        if token in {"semantic", "inference"}:
            continue
        assert token not in text
    assert "invoke semantic inference" in lowered  # prohibition in docstring only


def test_workflow_runs_reconciliation_but_not_worker_a_compute():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "private_reconcile_apply.py" in text
    assert "CONTROL_GITHUB_APP_PRIVATE_KEY" in text
    assert "permission-contents: 'write'" in text
    assert "cron: '*/10 * * * *'" in text

    forbidden = (
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "scheduled_worker_a_v2_retry_guard.sh",
        "control-zero-relay-implementation.yml",
        "control-zero-relay-assurance.yml",
        "gh workflow run",
        "Reconcile, claim and execute one model-driven A1 task",
    )
    for token in forbidden:
        assert token not in text
