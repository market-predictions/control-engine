from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-b-v2.yml"
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
HELPER = ROOT / "control_engine" / "scheduled_worker_b.py"


def test_workflow_is_main_only_public_liveness_backstop() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "schedule:" in text
    assert "cron: '*/10 * * * *'" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "github.repository == 'market-predictions/control-engine'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "permissions:\n  contents: read" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
    assert "persist-credentials: false" in text
    assert "timeout-minutes: 30" in text


def test_workflow_reuses_existing_github_app_and_provider_boundary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for value in (
        "vars.CONTROL_GITHUB_APP_ID",
        "secrets.CONTROL_GITHUB_APP_PRIVATE_KEY",
        "secrets.CONTROL_CLOUDFLARE_API_TOKEN",
        "secrets.CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "vars.CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
    ):
        assert value in text
    assert "secrets.CONTROL_GITHUB_WRITE_TOKEN" not in text
    assert "CONTROL_GITHUB_WRITE_TOKEN: ${{ steps.app-token.outputs.token }}" in text
    assert "permission-contents: 'write'" in text
    assert "permission-actions: 'read'" in text
    assert "permission-pull-requests: 'read'" in text


def test_actuator_reuses_one_private_state_plane_and_connected_lifecycle() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'CONTROL_PLANE_REPOSITORY="market-predictions/control-plane"' in text
    assert 'CONTROL_RUNTIME_REF="control-runtime-state"' in text
    assert 'CONTROL_CODE_REF="runtime/public-b-v2-code-r1"' in text
    assert 'CONTROL_CODE_SHA="728117701e20ba3762e984ef779a74effb3bcc55"' in text
    assert "control_connected_worker_runtime_v1.py\" claim" in text
    assert "control_connected_worker_runtime_v1.py\" complete" in text
    assert "--worker-instance B1" in text
    assert 'LEASE_SECONDS=900' in text
    assert "pull --rebase" not in text
    assert "--force" not in text
    assert "set -x" not in text


def test_preferred_selection_is_rechecked_immediately_before_claim() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    first = text.index("select-b1")
    second = text.index("select-b1", first + 1)
    claim = text.index('control_connected_worker_runtime_v1.py\" claim')
    assert first < second < claim
    assert "IDLE_B1_SELECTION_MOVED" in text


def test_model_execution_has_provider_but_not_private_github_credential() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    model_start = text.index("env -i")
    model_end = text.index("model_rc=$?", model_start)
    model_block = text[model_start:model_end]
    assert "CLOUDFLARE_API_TOKEN" in model_block
    assert "CLOUDFLARE_ACCOUNT_ID" in model_block
    assert "CONTROL_GITHUB_WRITE_TOKEN" not in model_block
    assert "--role assurance" in model_block
    assert "rm -rf \"$REVIEW_DIR/.git\" \"$CODE_DIR\" \"$STATE_DIR\"" in text


def test_terminal_path_is_fail_closed_and_ghost_checked() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "FAIL_CLOSED_B1_TERMINAL_COMPLETION" in text
    assert "assert-finalized" in text
    assert "FAIL_CLOSED_B1_GHOST_FINALIZATION" in text
    assert "COMPLETED_ONE_B1_${outcome}" in text
    assert "EXECUTION_UNAVAILABLE" in text
    assert "INDETERMINATE" in text


def _write_fake_private_modules(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "dispatcher").mkdir(parents=True)
    (root / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (root / "dispatcher" / "__init__.py").write_text("", encoding="utf-8")
    (root / "tools" / "control_queue_v1.py").write_text(
        "ROLE_B='governance_release_assurance'\n",
        encoding="utf-8",
    )
    (root / "tools" / "control_parallel_execution_v1.py").write_text(
        "INSTANCE_B1='B1'\n"
        "def validate_parallel_queue(queue): return None\n"
        "def select_task_for_instance(queue, role, worker):\n"
        "    for task in queue['tasks']:\n"
        "        if task.get('state') == 'ASSURANCE_QUEUED': return task\n"
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


def test_helper_resumes_only_b_unavailable(tmp_path: Path) -> None:
    code = tmp_path / "private-code"
    _write_fake_private_modules(code)
    queue_path = tmp_path / "queue.json"
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "b-retry",
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
            {
                "task_id": "a-unavailable",
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
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    report = tmp_path / "report.json"
    subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "resume-b-unavailable",
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
        "b-retry": "ASSURANCE_QUEUED",
        "a-unavailable": "EXECUTION_UNAVAILABLE",
    }
    assert json.loads(report.read_text(encoding="utf-8")) == {
        "resumed": ["b-retry"],
        "blocked": [],
    }


def test_helper_selects_and_proves_b1_claim(tmp_path: Path) -> None:
    code = tmp_path / "private-code"
    _write_fake_private_modules(code)
    queue_path = tmp_path / "queue.json"
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "b-task",
                "repository": "example/repo",
                "candidate_sha": "a" * 40,
                "candidate_pr": 7,
                "governance_issue": 8,
                "state": "ASSURANCE_QUEUED",
                "principal_manual_relay_count": 0,
            }
        ],
    }
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    selection = tmp_path / "selection.json"
    subprocess.run(
        [sys.executable, str(HELPER), "select-b1", "--code-dir", str(code), "--queue", str(queue_path), "--output", str(selection)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert json.loads(selection.read_text(encoding="utf-8"))["task_id"] == "b-task"

    queue["tasks"][0].update(
        {
            "state": "ASSURANCE_EXECUTING",
            "active_role": "governance_release_assurance",
            "active_worker_instance": "B1",
            "active_run_id": "run-1",
            "claim_started_at": "2026-08-21T21:00:00Z",
            "claim_expires_at": "2099-08-21T21:15:00Z",
        }
    )
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    binding = tmp_path / "binding.json"
    subprocess.run(
        [sys.executable, str(HELPER), "assert-claim", "--code-dir", str(code), "--queue", str(queue_path), "--task-id", "b-task", "--output", str(binding)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert json.loads(binding.read_text(encoding="utf-8"))["run_id"] == "run-1"
