from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
HELPER = ROOT / "control_engine" / "scheduled_worker_b.py"


def test_completion_retry_is_bounded_and_stops_at_immutable_completion() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("for completion_attempt in")
    end = text.index('if [ "$completion_done" != true ]', start)
    block = text[start:end]
    assert '$(seq 1 "$MAX_CAS_ATTEMPTS")' in block
    assert "fetch_state" in block
    assert "assert-finalized" in block
    assert 'if [ -f "$STATE_DIR/$completion_rel" ]' in block
    assert "FAIL_CLOSED_B1_FINALIZATION_RECOVERY_REQUIRED" in block
    assert "assert-claim" in block
    assert "connected_complete" in block


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
        "def select_task_for_instance(*args, **kwargs): return None\n"
        "def assert_claim_current(*args, **kwargs): return None\n",
        encoding="utf-8",
    )


def _run_finalized(code: Path, queue_path: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "assert-finalized",
            "--code-dir",
            str(code),
            "--queue",
            str(queue_path),
            "--task-id",
            "b-task",
            "--run-id",
            run_id,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_final_readback_requires_exact_consumed_completion(tmp_path: Path) -> None:
    code = tmp_path / "code"
    _write_fake_private_modules(code)
    result_ref = "control/worker-results/CONTROL-H1.json"
    task = {
        "task_id": "b-task",
        "state": "ASSURANCE_PASS",
        "principal_manual_relay_count": 0,
        "active_run_id": None,
        "active_role": None,
        "active_worker_instance": None,
        "claim_started_at": None,
        "claim_expires_at": None,
        "last_terminal_completion_run_id": "run-1",
        "last_terminal_completion_result_ref": result_ref,
        "assurance_result_ref": f"control-runtime-state:{result_ref}",
    }
    queue = {"version": "1.0", "principal_manual_relay_count": 0, "tasks": [task]}
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")

    assert _run_finalized(code, queue_path, "run-1").returncode == 0

    del task["last_terminal_completion_run_id"]
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    failed = _run_finalized(code, queue_path, "run-1")
    assert failed.returncode == 2
    assert "ACTUATOR_CONTRACT_ERROR" in failed.stderr
