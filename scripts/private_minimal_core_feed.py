#!/usr/bin/env python3
"""Run canonical private Mission Feed against the one Minimal Core runtime queue.

This public script is deterministic lifecycle plumbing only. Mission policy and
selection remain in trusted private control-plane@main. No semantic work runs
here and no worker claim is created.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_engine import minimal_core as core
from scripts import project_integration_executor as integration

CONTROL_REPOSITORY = integration.CONTROL_REPOSITORY
RUNTIME_REF = integration.CONTROL_RUNTIME_REF
MAIN_REF = "main"
QUEUE_REL = "control/DISPATCH_QUEUE.json"
PRIVATE_FEED_REL = "tools/control_minimal_mission_feed_v1.py"
PRIVATE_FEED_MODULE = "tools.control_minimal_mission_feed_v1"
MISSION_DIR_REL = "control/missions"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _init_repo(path: Path) -> None:
    integration._init_repo(path, f"https://github.com/{CONTROL_REPOSITORY}.git")


def _reset_ref(token: str, repo_dir: Path, ref: str) -> str:
    result = integration._private_git(
        token,
        repo_dir,
        ["fetch", "--quiet", "origin", f"refs/heads/{ref}"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"private {ref} fetch unavailable")
    integration._run(["git", "reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=repo_dir)
    integration._run(["git", "clean", "-fdq"], cwd=repo_dir)
    return integration._run(["git", "rev-parse", "HEAD"], cwd=repo_dir).stdout.strip()


def _remote_ref_sha(token: str, repo_dir: Path, ref: str) -> str:
    result = integration._private_git(
        token,
        repo_dir,
        ["fetch", "--quiet", "origin", f"refs/heads/{ref}"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"private {ref} ref fetch unavailable")
    return integration._run(["git", "rev-parse", "FETCH_HEAD"], cwd=repo_dir).stdout.strip()


def command_feed(token: str) -> int:
    with tempfile.TemporaryDirectory(prefix="control-minimal-feed-") as temp:
        temp_root = Path(temp)
        runtime_dir = temp_root / "runtime"
        main_dir = temp_root / "main"
        report_path = temp_root / "feed-report.json"
        _init_repo(runtime_dir)
        _init_repo(main_dir)
        integration._run(["git", "config", "user.name", "control-minimal-core[bot]"], cwd=runtime_dir)
        integration._run(["git", "config", "user.email", "control-minimal-core[bot]@users.noreply.github.com"], cwd=runtime_dir)

        for attempt in range(1, integration.MAX_CAS_ATTEMPTS + 1):
            _reset_ref(token, runtime_dir, RUNTIME_REF)
            observed_runtime = integration._identity(runtime_dir)
            observed_main = _reset_ref(token, main_dir, MAIN_REF)
            feed_script = main_dir / PRIVATE_FEED_REL
            mission_dir = main_dir / MISSION_DIR_REL
            if not feed_script.is_file() or not mission_dir.is_dir():
                raise RuntimeError("trusted private Mission Feed is not available on main")

            result = integration._run(
                [
                    sys.executable,
                    "-m",
                    PRIVATE_FEED_MODULE,
                    "--mission-dir",
                    str(mission_dir),
                    "--queue",
                    str(runtime_dir / QUEUE_REL),
                    "--write",
                    "--report",
                    str(report_path),
                ],
                cwd=main_dir,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError("trusted private Mission Feed failed")

            queue = _load(runtime_dir / QUEUE_REL)
            core.validate(queue)
            changed = integration._changed_paths(runtime_dir)
            if not changed:
                report = _load(report_path)
                print("CONTROL_MINIMAL_CORE_FEED=" + report["outcome"])
                print("CONTROL_MINIMAL_CORE_FEED_MATERIALIZED=" + json.dumps(report["materialized"]))
                print("CONTROL_MINIMAL_CORE_FEED_DEFERRED=" + json.dumps(report["deferred_repository_busy"]))
                print(f"CONTROL_MINIMAL_CORE_FEED_CAS_ATTEMPT={attempt}")
                return 0
            if changed != {QUEUE_REL}:
                raise RuntimeError("Mission Feed runtime write scope exceeded")

            if _remote_ref_sha(token, main_dir, MAIN_REF) != observed_main:
                continue
            if integration._remote_identity(token, runtime_dir) != observed_runtime:
                continue
            if not integration._persist(
                token,
                runtime_dir,
                message="runtime: feed Control Minimal Core mission work",
                paths=[QUEUE_REL],
                allowed={QUEUE_REL},
            ):
                continue

            integration._reset_state(token, runtime_dir)
            readback = _load(runtime_dir / QUEUE_REL)
            core.validate(readback)
            report = _load(report_path)
            for task_id in report["materialized"]:
                matches = [item for item in readback.get("tasks", []) if item.get("task_id") == task_id]
                if len(matches) != 1 or matches[0].get("status") != core.STATUS_QUEUED or matches[0].get("claim") is not None:
                    raise RuntimeError("Mission Feed readback proof failed")
            print("CONTROL_MINIMAL_CORE_FEED=" + report["outcome"])
            print("CONTROL_MINIMAL_CORE_FEED_MATERIALIZED=" + json.dumps(report["materialized"]))
            print("CONTROL_MINIMAL_CORE_FEED_DEFERRED=" + json.dumps(report["deferred_repository_busy"]))
            print(f"CONTROL_MINIMAL_CORE_FEED_MAIN_SHA={observed_main}")
            print(f"CONTROL_MINIMAL_CORE_FEED_CAS_ATTEMPT={attempt}")
            return 0

        raise RuntimeError("CONTROL_MINIMAL_CORE_FEED_CAS_CONFLICT")


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("CONTROL_MINIMAL_CORE_FEED=NO_TOKEN")
        return 78
    try:
        return command_feed(token)
    except Exception as exc:
        print(f"CONTROL_MINIMAL_CORE_FEED=FAILED:{type(exc).__name__}:{str(exc)[-1200:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
