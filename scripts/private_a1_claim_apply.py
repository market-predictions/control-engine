#!/usr/bin/env python3
"""Persist exactly one canonical A1 lifecycle claim; perform no semantic work."""

from __future__ import annotations

from datetime import datetime, timezone
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


LEASE_MINUTES = 75
A1_CONTROL_CODE_REF = "runtime/public-a1-code-r1"
A1_CONTROL_CODE_SHA = "a55e2a0d791ca55450ec135415e4aa9a48be361d"
AUTO_TASK_ID = "AUTO"


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed rc={result.returncode}: stderr={result.stderr.strip()[-2000:]} stdout={result.stdout.strip()[-2000:]}"
        )
    return result


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find(queue: dict, task_id: str) -> dict:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise RuntimeError("canonical task identity is not unique")
    return matches[0]


def _fetch_a1_code(token: str, code_dir: Path) -> None:
    """Fetch the immutable A1 lifecycle snapshot without repinning other actuators."""
    integration._init_repo(code_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
    integration._private_git(
        token,
        code_dir,
        ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{A1_CONTROL_CODE_REF}"],
    )
    integration._run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=code_dir)
    actual = integration._run(["git", "rev-parse", "HEAD"], cwd=code_dir).stdout.strip()
    if actual != A1_CONTROL_CODE_SHA:
        raise RuntimeError("private A1 lifecycle code SHA mismatch")


def _preferred_a1_task(code_dir: Path, queue_path: Path) -> str | None:
    selector = (
        "import json,sys; from pathlib import Path; "
        "from tools.control_queue_v1 import ROLE_A; "
        "from tools.control_parallel_execution_v1 import INSTANCE_A1, select_task_for_instance; "
        "q=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')); "
        "t=select_task_for_instance(q, ROLE_A, INSTANCE_A1); "
        "print('' if t is None else t['task_id'])"
    )
    result = integration._run(
        [sys.executable, "-c", selector, str(queue_path)],
        cwd=code_dir,
    )
    value = result.stdout.strip()
    return value or None


def _assert_current_a1_claim(queue: dict, task_id: str) -> dict:
    task = _find(queue, task_id)
    if task.get("state") not in {"IMPLEMENTATION_EXECUTING", "REPAIR_EXECUTING"}:
        raise RuntimeError("claimed task is not A-executing")
    if task.get("active_role") != "implementation_operations":
        raise RuntimeError("claim role is not implementation_operations")
    if task.get("active_worker_instance") != "A1":
        raise RuntimeError("claim worker instance is not A1")
    run_id = task.get("active_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise RuntimeError("claim run id missing")
    expires_raw = task.get("claim_expires_at")
    if not isinstance(expires_raw, str):
        raise RuntimeError("claim expiry missing")
    expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise RuntimeError("claim is not current")
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise RuntimeError("principal manual relay invariant changed")
    return task


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    requested_task_id = os.environ.get("CONTROL_TASK_ID", "").strip()
    if not token or not requested_task_id:
        print("CONTROL_A1_CLAIM=INVALID_INPUT")
        return 78

    try:
        with tempfile.TemporaryDirectory(prefix="control-a1-claim-") as temp:
            root = Path(temp)
            code_dir = root / "code"
            state_dir = root / "state"

            _fetch_a1_code(token, code_dir)
            integration._init_repo(state_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
            integration._run(["git", "config", "user.name", "control-a1-claim[bot]"], cwd=state_dir)
            integration._run(["git", "config", "user.email", "control-a1-claim[bot]@users.noreply.github.com"], cwd=state_dir)

            for attempt in range(1, integration.MAX_CAS_ATTEMPTS + 1):
                integration._reset_state(token, state_dir)
                observed = integration._identity(state_dir)
                queue_path = state_dir / "control" / "DISPATCH_QUEUE.json"
                runs_path = state_dir / "control" / "DISPATCH_RUNS.json"

                # Reconcile expired ownership before selecting. AUTO then asks the
                # canonical private selector for exactly the currently preferred
                # A1 task; no public priority or eligibility logic is duplicated.
                _run([
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "reconcile",
                    "--queue",
                    str(queue_path),
                    "--runs",
                    str(runs_path),
                ])
                task_id = requested_task_id
                if requested_task_id == AUTO_TASK_ID:
                    selected = _preferred_a1_task(code_dir, queue_path)
                    if selected is None:
                        if integration._remote_identity(token, state_dir) != observed:
                            continue
                        print("CONTROL_A1_CLAIM=NO_ELIGIBLE_WORK")
                        return 0
                    task_id = selected

                # Canonical dispatcher claim repeats expiry reconciliation and
                # enforces preferred-task, A1/capacity/resource, unique-run and
                # bounded-lease semantics before any private state is persisted.
                _run([
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "claim",
                    "--queue",
                    str(queue_path),
                    "--runs",
                    str(runs_path),
                    "--task-id",
                    task_id,
                    "--backend",
                    "chatgpt-interactive/canonical-a1",
                    "--lease-minutes",
                    str(LEASE_MINUTES),
                ])
                _run([
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "validate",
                    "--queue",
                    str(queue_path),
                ])
                queue = _load(queue_path)
                claimed = _assert_current_a1_claim(queue, task_id)

                if integration._remote_identity(token, state_dir) != observed:
                    continue
                if not integration._persist(
                    token,
                    state_dir,
                    message=f"runtime: canonical native ChatGPT A1 claim {task_id}",
                    paths=["control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"],
                    allowed={"control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"},
                ):
                    continue

                integration._reset_state(token, state_dir)
                readback = _assert_current_a1_claim(
                    _load(state_dir / "control" / "DISPATCH_QUEUE.json"), task_id
                )
                if readback.get("active_run_id") != claimed.get("active_run_id"):
                    raise RuntimeError("claim readback run id drifted")
                print("CONTROL_A1_CLAIM=START_PROVEN")
                print(f"CONTROL_A1_TASK_ID={task_id}")
                print(f"CONTROL_A1_RUN_ID={readback['active_run_id']}")
                print(f"CONTROL_A1_CLAIM_EXPIRES_AT={readback['claim_expires_at']}")
                print(f"CONTROL_A1_CLAIM_ATTEMPT={attempt}")
                return 0

            print("CONTROL_A1_CLAIM=CAS_CONFLICT")
            return 75
    except Exception as exc:
        print(f"CONTROL_A1_CLAIM=FAILED:{type(exc).__name__}:{str(exc)[-1200:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
