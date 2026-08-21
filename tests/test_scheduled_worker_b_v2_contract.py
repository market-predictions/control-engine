from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-b-v2.yml"
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
HELPER = ROOT / "control_engine" / "scheduled_worker_b.py"


def test_public_workflow_is_main_only_and_secret_safe() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "cron: '*/10 * * * *'" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "github.repository == 'market-predictions/control-engine'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "permissions:\n  contents: read" in text
    assert "persist-credentials: false" in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text
    for value in (
        "vars.CONTROL_GITHUB_APP_ID",
        "secrets.CONTROL_GITHUB_APP_PRIVATE_KEY",
        "secrets.CONTROL_CLOUDFLARE_API_TOKEN",
        "secrets.CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "vars.CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
    ):
        assert value in text


def test_actuator_reuses_existing_control_primitives() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'CONTROL_RUNTIME_REF="control-runtime-state"' in text
    assert 'CONTROL_CODE_REF="runtime/public-b-v2-code-r1"' in text
    assert 'CONTROL_CODE_SHA="728117701e20ba3762e984ef779a74effb3bcc55"' in text
    assert 'LEASE_MINUTES=15' in text
    assert 'dispatcher/cli.py\" resume' in text
    assert 'dispatcher/cli.py\" claim' in text
    assert "connected_complete" in text
    assert "--worker-instance B1" in text
    assert "pull --rebase" not in text
    assert "--force" not in text
    assert "set -x" not in text


def test_claim_matches_proven_worker_a_cas_shape() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    first = text.index("select-b1")
    second = text.index("select-b1", first + 1)
    claim = text.index('dispatcher/cli.py\" claim')
    persist = text.index('"runtime: Scheduled Worker B V2 claim B1"', claim)
    readback = text.index("assert-claim", persist)
    assert first < second < claim < persist < readback
    assert "assert_claim_write_scope" in text
    assert "RUNTIME_CAS_CONFLICT_CLAIM" in text


def test_inference_isolated_from_private_github_credential() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("env -i")
    end = text.index("model_rc=$?", start)
    model = text[start:end]
    assert "CLOUDFLARE_API_TOKEN" in model
    assert "CLOUDFLARE_ACCOUNT_ID" in model
    assert "CONTROL_GITHUB_WRITE_TOKEN" not in model
    assert "GH_TOKEN" not in model
    assert "--role assurance" in model
    assert "rm -rf \"$REVIEW_DIR/.git\" \"$CODE_DIR\" \"$STATE_DIR\"" in text


def _write_fake_private_modules(root: Path) -> None:
    (root / "tools").mkdir(parents=True)
    (root / "tools" / "__init__.py").write_text("", encoding="utf-8")
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


def test_helper_only_identifies_b_resumable_records(tmp_path: Path) -> None:
    code = tmp_path / "code"
    _write_fake_private_modules(code)
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "b",
                "state": "EXECUTION_UNAVAILABLE",
                "resume_state": "ASSURANCE_QUEUED",
                "active_run_id": None,
                "active_role": None,
                "active_worker_instance": None,
                "claim_started_at": None,
                "claim_expires_at": None,
            },
            {
                "task_id": "a",
                "state": "EXECUTION_UNAVAILABLE",
                "resume_state": "IMPLEMENTATION_QUEUED",
                "active_run_id": None,
                "active_role": None,
                "active_worker_instance": None,
                "claim_started_at": None,
                "claim_expires_at": None,
            },
        ],
    }
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    output = tmp_path / "resumable.txt"
    subprocess.run(
        [sys.executable, str(HELPER), "list-resumable-b", "--code-dir", str(code), "--queue", str(queue_path), "--output", str(output)],
        check=True,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert output.read_text(encoding="utf-8") == "b\n"
    assert json.loads(queue_path.read_text(encoding="utf-8")) == queue


def test_helper_selects_and_proves_b1_claim(tmp_path: Path) -> None:
    code = tmp_path / "code"
    _write_fake_private_modules(code)
    task = {
        "task_id": "b-task",
        "repository": "example/repo",
        "candidate_sha": "a" * 40,
        "candidate_pr": 7,
        "governance_issue": 8,
        "state": "ASSURANCE_QUEUED",
        "principal_manual_relay_count": 0,
    }
    queue = {"version": "1.0", "principal_manual_relay_count": 0, "tasks": [task]}
    queue_path = tmp_path / "queue.json"
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

    task.update(
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
