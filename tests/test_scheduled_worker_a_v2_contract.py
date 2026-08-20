from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
SCRIPT = ROOT / "scripts" / "scheduled_worker_a_v2.sh"
HELPER = ROOT / "control_engine" / "scheduled_worker_a.py"
BOUNDARY = ROOT / "docs" / "PUBLIC_PRIVATE_BOUNDARY_V1.md"
ACTUATOR = ROOT / "docs" / "PRIVATE_RUNTIME_ACTUATOR_V1.md"


def test_workflow_is_main_only_scheduled_liveness_backstop() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron: '*/10 * * * *'" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.repository == 'market-predictions/control-engine'" in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "persist-credentials: false" in text
    assert "timeout-minutes: 60" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text


def test_workflow_uses_only_named_private_bridge_and_provider_secrets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for name in (
        "secrets.CONTROL_GITHUB_WRITE_TOKEN",
        "secrets.CONTROL_CLOUDFLARE_API_TOKEN",
        "secrets.CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "vars.CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
    ):
        assert name in text
    assert "bash -n scripts/scheduled_worker_a_v2.sh" in text
    assert "python -m py_compile control_engine/scheduled_worker_a.py" in text


def test_actuator_pins_private_state_machine_and_forbids_stale_replay() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'CONTROL_CODE_SHA="ca9c9759a07fd4943e31a94d81a3af7c1aaf9534"' in text
    assert 'GITHUB_REF:-}" != "refs/heads/main"' in text
    assert 'GITHUB_REPOSITORY:-}" != "$PUBLIC_REPOSITORY"' in text
    assert "observed_ref" in text and "observed_blob" in text
    assert "current_ref" in text and "current_blob" in text
    assert "RUNTIME_CAS_CONFLICT_RECONCILE" in text
    assert "RUNTIME_CAS_CONFLICT_CLAIM" in text
    assert "RUNTIME_CAS_CONFLICT_FINALIZE" in text
    assert "pull --rebase" not in text
    assert "--force" not in text
    assert "force push" not in text.lower()
    assert "set -x" not in text
    assert "LEASE_MINUTES=75" in text


def test_liveness_order_is_lease_then_unavailable_then_intake_then_selection() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    lease = text.index('dispatcher/cli.py" reconcile')
    unavailable = text.index("resume-a-unavailable")
    intake = text.index("control_project_intake_reconcile_v1.py")
    selection = text.index("select-a1")
    assert lease < unavailable < intake < selection


def test_private_write_scopes_and_model_credential_isolation_are_explicit() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "control/DISPATCH_QUEUE.json|control/DISPATCH_RUNS.json|control/project-intake/*.json" in text
    assert "control/DISPATCH_QUEUE.json|control/DISPATCH_RUNS.json" in text
    assert "env -i" in text
    model_start = text.index("env -i")
    model_end = text.index("model_rc=$?", model_start)
    model_block = text[model_start:model_end]
    assert "CLOUDFLARE_API_TOKEN" in model_block
    assert "CLOUDFLARE_ACCOUNT_ID" in model_block
    assert "CONTROL_GITHUB_WRITE_TOKEN" not in model_block
    assert "upload-artifact" not in text
    assert "PROJECT_INTEGRATION_EXECUTOR" in text


def test_missing_provider_credentials_cannot_create_a_claim() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    provider_gate = text.index("EXECUTION_UNAVAILABLE_IMPLEMENTATION_PROVIDER_CREDENTIAL")
    free_gate = text.index("EXECUTION_UNAVAILABLE_FREE_FAIL_CLOSED_ATTESTATION")
    first_claim = text.index('dispatcher/cli.py" claim')
    assert provider_gate < first_claim
    assert free_gate < first_claim


def test_boundary_preserves_private_authority_while_allowing_ephemeral_compute() -> None:
    boundary = BOUNDARY.read_text(encoding="utf-8")
    actuator = ACTUATOR.read_text(encoding="utf-8")
    assert "PUBLIC RUNNER != SECOND CONTROL AUTHORITY" in boundary
    assert "transiently process private Control state" in boundary
    assert "no private runtime state is persisted or exposed" in boundary.lower()
    assert "Pull-request and fork workflows never receive the private-state execution path" in actuator
    assert "public repository's built-in `GITHUB_TOKEN` remains `contents: read`" in actuator
    assert "principal_manual_relay_count=0" in actuator


def _write_fake_private_modules(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "dispatcher").mkdir(parents=True)
    (root / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (root / "dispatcher" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tools" / "control_queue_v1.py").write_text(
        "ROLE_A='implementation_operations'\n",
        encoding="utf-8",
    )
    (root / "tools" / "control_parallel_execution_v1.py").write_text(
        "INSTANCE_A1='A1'\n"
        "def validate_parallel_queue(queue): return None\n"
        "def select_task_for_instance(queue, role, worker):\n"
        "    for task in queue['tasks']:\n"
        "        if task.get('state') in {'IMPLEMENTATION_QUEUED','REPAIR_QUEUED'}: return task\n"
        "    return None\n"
        "def assert_claim_current(*args, **kwargs): return None\n",
        encoding="utf-8",
    )
    (root / "dispatcher" / "state.py").write_text(
        "def resume_unavailable(task):\n"
        "    result=dict(task)\n"
        "    if result.get('attempt',0) >= result.get('max_attempts',0):\n"
        "        result['state']='BLOCKED'\n"
        "    else:\n"
        "        result['state']=result['resume_state']\n"
        "    result['resume_state']=None\n"
        "    return result\n",
        encoding="utf-8",
    )


def test_helper_resumes_only_a_unavailable_and_blocks_exhausted(tmp_path: Path) -> None:
    code = tmp_path / "private-code"
    _write_fake_private_modules(code)
    queue_path = tmp_path / "queue.json"
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "a-retry",
                "state": "EXECUTION_UNAVAILABLE",
                "resume_state": "IMPLEMENTATION_QUEUED",
                "attempt": 1,
                "max_attempts": 3,
                "active_run_id": None,
                "active_role": None,
                "active_worker_instance": None,
                "claim_started_at": None,
                "claim_expires_at": None,
            },
            {
                "task_id": "a-exhausted",
                "state": "EXECUTION_UNAVAILABLE",
                "resume_state": "REPAIR_QUEUED",
                "attempt": 3,
                "max_attempts": 3,
                "active_run_id": None,
                "active_role": None,
                "active_worker_instance": None,
                "claim_started_at": None,
                "claim_expires_at": None,
            },
            {
                "task_id": "b-unavailable",
                "state": "EXECUTION_UNAVAILABLE",
                "resume_state": "ASSURANCE_QUEUED",
                "attempt": 1,
                "max_attempts": 3,
                "active_run_id": None,
                "active_role": None,
                "active_worker_instance": None,
                "claim_started_at": None,
                "claim_expires_at": None,
            },
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    report = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "resume-a-unavailable",
            "--code-dir",
            str(code),
            "--queue",
            str(queue_path),
            "--output",
            str(report),
        ],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    after = json.loads(queue_path.read_text(encoding="utf-8"))
    states = {item["task_id"]: item["state"] for item in after["tasks"]}
    assert states == {
        "a-retry": "IMPLEMENTATION_QUEUED",
        "a-exhausted": "BLOCKED",
        "b-unavailable": "EXECUTION_UNAVAILABLE",
    }
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result == {"resumed": ["a-retry"], "blocked": ["a-exhausted"]}


def test_helper_rejects_unavailable_a_with_ghost_ownership(tmp_path: Path) -> None:
    code = tmp_path / "private-code"
    _write_fake_private_modules(code)
    queue_path = tmp_path / "queue.json"
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "ghost",
                "state": "EXECUTION_UNAVAILABLE",
                "resume_state": "IMPLEMENTATION_QUEUED",
                "attempt": 1,
                "max_attempts": 3,
                "active_run_id": "still-owned",
                "active_role": "implementation_operations",
                "active_worker_instance": "A1",
                "claim_started_at": "x",
                "claim_expires_at": "y",
            }
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "resume-a-unavailable",
            "--code-dir",
            str(code),
            "--queue",
            str(queue_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr.startswith("ACTUATOR_CONTRACT_ERROR:")
    assert "still-owned" not in completed.stderr
