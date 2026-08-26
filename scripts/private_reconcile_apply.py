#!/usr/bin/env python3
"""Apply deterministic private Control intake reconciliation only.

This actuator may reconcile canonical runtime state, but it is deliberately not
Worker A: it cannot claim implementation work, invoke semantic inference, repair
candidate code, assure, integrate, merge, release, or create another state plane.
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


RECONCILE_CODE_REF = "control/171-intake-queue-reconciliation-v1"
RECONCILE_CODE_SHA = "03f22d679a4bcea36870df83a6b7c5c35f1c2d35"


def _run_stage(name: str, cmd: list[str]) -> None:
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip()[-3000:]
        stdout = result.stdout.strip()[-3000:]
        raise RuntimeError(f"stage={name}; rc={result.returncode}; stderr={stderr}; stdout={stdout}")


def _fetch_reconcile_code(token: str, code_dir: Path) -> None:
    """Fetch the immutable reconciliation snapshot without repinning other actuators."""
    integration._init_repo(code_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
    integration._private_git(
        token,
        code_dir,
        ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{RECONCILE_CODE_REF}"],
    )
    integration._run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=code_dir)
    actual = integration._run(["git", "rev-parse", "HEAD"], cwd=code_dir).stdout.strip()
    if actual != RECONCILE_CODE_SHA:
        raise RuntimeError("private reconciliation code SHA mismatch")


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("CONTROL_RUNTIME_RECONCILER=NO_TOKEN")
        return 78

    try:
        with tempfile.TemporaryDirectory(prefix="control-runtime-reconcile-") as temp:
            root = Path(temp)
            code_dir = root / "code"
            state_dir = root / "state"
            report = root / "intake-report.json"
            supersession_report = root / "supersession-report.json"

            _fetch_reconcile_code(token, code_dir)
            integration._init_repo(state_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
            integration._run(["git", "config", "user.name", "control-runtime-reconciler[bot]"], cwd=state_dir)
            integration._run(["git", "config", "user.email", "control-runtime-reconciler[bot]@users.noreply.github.com"], cwd=state_dir)

            for attempt in range(1, integration.MAX_CAS_ATTEMPTS + 1):
                integration._reset_state(token, state_dir)
                observed = integration._identity(state_dir)

                _run_stage(
                    "dispatcher_reconcile",
                    [
                        sys.executable,
                        str(code_dir / "dispatcher" / "cli.py"),
                        "reconcile",
                        "--queue",
                        str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                        "--runs",
                        str(state_dir / "control" / "DISPATCH_RUNS.json"),
                    ],
                )
                _run_stage(
                    "superseded_intake_reconcile",
                    [
                        sys.executable,
                        str(code_dir / "tools" / "control_superseded_intake_reconcile_v1.py"),
                        "--queue",
                        str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                        "--intake-dir",
                        str(state_dir / "control" / "project-intake"),
                        "--write",
                        "--report",
                        str(supersession_report),
                    ],
                )
                _run_stage(
                    "project_intake_reconcile",
                    [
                        sys.executable,
                        str(code_dir / "tools" / "control_project_intake_reconcile_v1.py"),
                        "--queue",
                        str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                        "--intake-dir",
                        str(state_dir / "control" / "project-intake"),
                        "--handover-dir",
                        str(state_dir / "control" / "handovers"),
                        "--worker-result-dir",
                        str(state_dir / "control" / "worker-results"),
                        "--write",
                        "--report",
                        str(report),
                    ],
                )
                _run_stage(
                    "queue_validate",
                    [
                        sys.executable,
                        str(code_dir / "dispatcher" / "cli.py"),
                        "validate",
                        "--queue",
                        str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                    ],
                )

                changed = integration._changed_paths(state_dir)
                allowed = {
                    "control/DISPATCH_QUEUE.json",
                    "control/DISPATCH_RUNS.json",
                }
                allowed = integration._extend_reconcile_write_scope(allowed, changed)
                if not changed.issubset(allowed):
                    raise RuntimeError("deterministic reconciliation write scope exceeded")

                if integration._remote_identity(token, state_dir) != observed:
                    continue

                if integration._persist(
                    token,
                    state_dir,
                    message="runtime: deterministically reconcile canonical project intake",
                    paths=["control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json", "control/project-intake"],
                    allowed=allowed,
                ):
                    payload = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
                    supersession = (
                        json.loads(supersession_report.read_text(encoding="utf-8"))
                        if supersession_report.exists()
                        else {}
                    )
                    created = payload.get("created", payload.get("created_task_ids", []))
                    updated = payload.get("updated", payload.get("updated_task_ids", []))
                    superseded = supersession.get("superseded", [])
                    deferred_active = supersession.get("deferred_active", [])
                    print("CONTROL_RUNTIME_RECONCILER=SUCCESS")
                    print(f"CONTROL_RUNTIME_RECONCILER_ATTEMPT={attempt}")
                    print(f"CONTROL_RUNTIME_RECONCILER_CREATED={json.dumps(created, sort_keys=True)}")
                    print(f"CONTROL_RUNTIME_RECONCILER_UPDATED={json.dumps(updated, sort_keys=True)}")
                    print(f"CONTROL_RUNTIME_RECONCILER_SUPERSEDED={json.dumps(superseded, sort_keys=True)}")
                    print(f"CONTROL_RUNTIME_RECONCILER_DEFERRED_ACTIVE={json.dumps(deferred_active, sort_keys=True)}")
                    return 0

            print("CONTROL_RUNTIME_RECONCILER=CAS_CONFLICT")
            return 75
    except Exception as exc:
        print(f"CONTROL_RUNTIME_RECONCILER=FAILED:{type(exc).__name__}:{str(exc)[-1500:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
