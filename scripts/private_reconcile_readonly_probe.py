#!/usr/bin/env python3
"""Read-only private reconciliation probe for Scheduled Worker A V2 diagnostics.

The probe fetches the pinned private Control code and current runtime state,
executes the same reconciliation stages locally, and writes a detailed receipt
only to private recovery issue #187. It never commits or pushes runtime state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from scripts import project_integration_executor as integration


RECOVERY_ISSUE = 187
MARKER = "<!-- scheduled-worker-a-v2-readonly-reconcile-probe -->"


def _tail(value: str, limit: int = 4000) -> str:
    value = value.strip()
    return value[-limit:] if len(value) > limit else value


def _post_receipt(token: str, lines: list[str]) -> None:
    body = "\n".join([MARKER, "### Scheduled Worker A V2 — read-only reconciliation probe", "", *lines])
    integration._api(
        token,
        "POST",
        f"repos/{integration.CONTROL_REPOSITORY}/issues/{RECOVERY_ISSUE}/comments",
        {"body": body},
    )


def _run_stage(name: str, cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"stage={name}; returncode={result.returncode}; stderr={_tail(result.stderr)}; stdout={_tail(result.stdout)}"
        )
    return result


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("PRIVATE_RECONCILE_PROBE=NO_TOKEN")
        return 78

    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    stage = "bootstrap"
    try:
        with tempfile.TemporaryDirectory(prefix="control-a-reconcile-probe-") as temp:
            root = Path(temp)
            code_dir = root / "code"
            state_dir = root / "state"
            private_tmp = root / "private"
            private_tmp.mkdir()

            stage = "fetch_private_code"
            integration._fetch_code(token, code_dir)

            stage = "fetch_private_runtime"
            integration._init_repo(state_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
            integration._run(["git", "config", "user.name", "control-reconcile-probe[bot]"], cwd=state_dir)
            integration._run(["git", "config", "user.email", "control-reconcile-probe[bot]@users.noreply.github.com"], cwd=state_dir)
            integration._reset_state(token, state_dir)
            observed_ref, observed_blob = integration._identity(state_dir)

            if str(Path.cwd()) not in sys.path:
                sys.path.insert(0, str(Path.cwd()))
            if str(code_dir.resolve()) not in sys.path:
                sys.path.insert(0, str(code_dir.resolve()))

            stage = "dispatcher_reconcile"
            _run_stage(
                stage,
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

            stage = "resume_a_unavailable"
            from control_engine.scheduled_worker_a import resume_a_unavailable

            resume_output = private_tmp / "resume-a.json"
            resume_a_unavailable(
                str(code_dir),
                str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                str(resume_output),
            )

            stage = "project_intake_reconcile"
            intake_report = private_tmp / "intake-report.json"
            _run_stage(
                stage,
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
                    str(intake_report),
                ],
            )

            stage = "queue_validate"
            _run_stage(
                stage,
                [
                    sys.executable,
                    str(code_dir / "dispatcher" / "cli.py"),
                    "validate",
                    "--queue",
                    str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                ],
            )

            stage = "write_scope_check"
            changed = sorted(integration._changed_paths(state_dir))
            allowed = {"control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"}
            for path in (state_dir / "control" / "project-intake").glob("*.json"):
                allowed.add(path.relative_to(state_dir).as_posix())
            allowed = integration._extend_reconcile_write_scope(allowed, set(changed))
            scope_ok = set(changed).issubset(allowed)

            remote_ref, remote_blob = integration._remote_identity(token, state_dir)
            cas_unchanged = (remote_ref, remote_blob) == (observed_ref, observed_blob)

            resume_payload: Any = {}
            if resume_output.exists():
                resume_payload = json.loads(resume_output.read_text(encoding="utf-8"))
            intake_payload: Any = {}
            if intake_report.exists():
                intake_payload = json.loads(intake_report.read_text(encoding="utf-8"))

            _post_receipt(
                token,
                [
                    f"Run: `{run_id}`",
                    "Result: **LOCAL_RECONCILIATION_OK**",
                    f"Observed runtime ref: `{observed_ref}`",
                    f"Observed queue blob: `{observed_blob}`",
                    f"Remote identity unchanged during probe: `{str(cas_unchanged).lower()}`",
                    f"Changed paths locally: `{json.dumps(changed)}`",
                    f"Write scope valid: `{str(scope_ok).lower()}`",
                    f"resume-a result: `{json.dumps(resume_payload, sort_keys=True)}`",
                    f"intake reconcile report: `{json.dumps(intake_payload, sort_keys=True)}`",
                    "No runtime commit or push was attempted by this probe.",
                ],
            )
            print("PRIVATE_RECONCILE_PROBE=LOCAL_OK")
            return 0
    except Exception as exc:
        message = f"stage={stage}; {type(exc).__name__}: {_tail(str(exc))}"
        try:
            _post_receipt(
                token,
                [
                    f"Run: `{run_id}`",
                    "Result: **FAILED**",
                    f"Failure: `{message}`",
                    "No runtime commit or push was attempted by this probe.",
                ],
            )
        except Exception:
            pass
        print(f"PRIVATE_RECONCILE_PROBE=FAILED_{stage.upper()}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
