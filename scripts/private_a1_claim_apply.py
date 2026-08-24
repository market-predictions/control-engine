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
    task_id = os.environ.get("CONTROL_TASK_ID", "").strip()
    if not token or not task_id:
        print("CONTROL_A1_CLAIM=INVALID_INPUT")
        return 78

    try:
        with tempfile.TemporaryDirectory(prefix="control-a1-claim-") as temp:
            root = Path(temp)
            code_dir = root / "code"
            state_dir = root / "state"

            integration._fetch_code(token, code_dir)
            integration._init_repo(state_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
            integration._run(["git", "config", "user.name", "control-a1-claim[bot]"], cwd=state_dir)
            integration._run(["git", "config", "user.email", "control-a1-claim[bot]@users.noreply.github.com"], cwd=state_dir)

            for attempt in range(1, integration.MAX_CAS_ATTEMPTS + 1):
                integration._reset_state(token, state_dir)
                observed = integration._identity(state_dir)

                # Canonical dispatcher claim performs expiry reconciliation,
                # preferred-task enforcement, A1/capacity/resource selection,
                # unique run creation and bounded lease assignment.
                result = _run([
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "claim",
                    "--queue",
                    str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                    "--runs",
                    str(state_dir / "control" / "DISPATCH_RUNS.json"),
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
                    str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                ])
                queue = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
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
