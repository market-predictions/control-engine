#!/usr/bin/env python3
"""Apply one pre-staged private A1 worker result through canonical state logic.

This actuator performs lifecycle/state mutation only. Native ChatGPT creates the
semantic result privately; this code verifies exact claim ownership and asks the
pinned private dispatcher to record it. It never performs model inference.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import project_integration_executor as integration


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed rc={result.returncode}: stderr={result.stderr.strip()[-1500:]} stdout={result.stdout.strip()[-1500:]}"
        )
    return result


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _task(queue: dict, task_id: str) -> dict:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise RuntimeError("canonical task identity is not unique")
    return matches[0]


def _assert_staged_result(queue: dict, result: dict, task_id: str) -> str:
    task = _task(queue, task_id)
    if task.get("state") not in {"IMPLEMENTATION_EXECUTING", "REPAIR_EXECUTING"}:
        raise RuntimeError("A1 result target is not executing")
    if task.get("active_role") != "implementation_operations":
        raise RuntimeError("A1 result target role mismatch")
    if task.get("active_worker_instance") != "A1":
        raise RuntimeError("A1 result target worker mismatch")
    run_id = task.get("active_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("A1 result target run id missing")
    if result.get("version") != "1.0":
        raise RuntimeError("staged result version mismatch")
    if result.get("task_id") != task_id or result.get("run_id") != run_id:
        raise RuntimeError("staged result identity mismatch")
    if result.get("role") != "implementation_operations":
        raise RuntimeError("staged result role mismatch")
    if result.get("outcome") not in {"COMPLETED", "BLOCKED", "EXECUTION_UNAVAILABLE"}:
        raise RuntimeError("staged A1 result outcome is not lifecycle-safe")
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise RuntimeError("principal manual relay invariant changed")
    return run_id


def _assert_terminal_readback(queue: dict, task_id: str, run_id: str) -> None:
    task = _task(queue, task_id)
    if task.get("active_run_id") is not None:
        raise RuntimeError("recorded task retained active_run_id")
    if task.get("active_role") is not None or task.get("active_worker_instance") is not None:
        raise RuntimeError("recorded task retained active ownership")
    if task.get("claim_started_at") is not None or task.get("claim_expires_at") is not None:
        raise RuntimeError("recorded task retained lease metadata")
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise RuntimeError("principal manual relay invariant changed")
    if not run_id:
        raise RuntimeError("record readback run id missing")


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    task_id = os.environ.get("CONTROL_TASK_ID", "").strip()
    if not token or not task_id:
        print("CONTROL_A1_RECORD=INVALID_INPUT")
        return 78

    result_rel = Path("control") / "worker-results" / f"{task_id}.json"
    try:
        with tempfile.TemporaryDirectory(prefix="control-a1-record-") as temp:
            root = Path(temp)
            code_dir = root / "code"
            state_dir = root / "state"
            integration._fetch_code(token, code_dir)
            integration._init_repo(state_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
            integration._run(["git", "config", "user.name", "control-a1-record[bot]"], cwd=state_dir)
            integration._run(["git", "config", "user.email", "control-a1-record[bot]@users.noreply.github.com"], cwd=state_dir)

            for attempt in range(1, integration.MAX_CAS_ATTEMPTS + 1):
                integration._reset_state(token, state_dir)
                observed = integration._identity(state_dir)
                result_path = state_dir / result_rel
                if not result_path.is_file():
                    raise RuntimeError("pre-staged private A1 result is missing")
                queue = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
                result = _load(result_path)
                run_id = _assert_staged_result(queue, result, task_id)

                _run([
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "record",
                    "--queue",
                    str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                    "--runs",
                    str(state_dir / "control" / "DISPATCH_RUNS.json"),
                    "--task-id",
                    task_id,
                    "--result",
                    str(result_path),
                ])
                _run([
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "validate",
                    "--queue",
                    str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                ])
                if integration._remote_identity(token, state_dir) != observed:
                    continue
                if not integration._persist(
                    token,
                    state_dir,
                    message=f"runtime: record native ChatGPT A1 result {task_id}",
                    paths=["control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"],
                    allowed={"control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"},
                ):
                    continue

                integration._reset_state(token, state_dir)
                readback = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
                _assert_terminal_readback(readback, task_id, run_id)
                print("CONTROL_A1_RECORD=RECORDED")
                print(f"CONTROL_A1_TASK_ID={task_id}")
                print(f"CONTROL_A1_RUN_ID={run_id}")
                print(f"CONTROL_A1_RECORD_ATTEMPT={attempt}")
                return 0

            print("CONTROL_A1_RECORD=CAS_CONFLICT")
            return 75
    except Exception as exc:
        print(f"CONTROL_A1_RECORD=FAILED:{type(exc).__name__}:{str(exc)[-1200:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
