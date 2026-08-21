#!/usr/bin/env python3
"""One-shot fail-closed quarantine for the legacy ZTA PR7 repair intake.

The legacy R2 intake predates mandatory REPAIR lineage and is schema-invalid.
This migration does not invent a handover/result and does not execute the stale
repair. It nulls only the invalid superseding queue_intent and pauses the exact
pre-existing R1 queue task under exact observed-state CAS.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CONTROL_REPOSITORY = "market-predictions/control-plane"
RUNTIME_REF = "control-runtime-state"
CODE_REF = "control/171-intake-queue-reconciliation-v1"
CODE_SHA = "ca9c9759a07fd4943e31a94d81a3af7c1aaf9534"
INTAKE_PATH = Path("control/project-intake/ZORGTECHADVIES_PR7.json")
QUEUE_PATH = Path("control/DISPATCH_QUEUE.json")
TASK_ID = "ZTA-PR7-WRANGLER-REPAIR"
R1 = "ZTA-PR7-WRANGLER-REPAIR-R1"
R2 = "ZTA-PR7-WRANGLER-REPAIR-R2"
MARKER = "LEGACY_INTAKE_QUARANTINED: ZTA PR7 R2 repair closeout lacks mandatory assurance lineage; stale R1 repair is paused and no handover/result is fabricated"


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=True)


def private_git(token: str, args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return run(["git", "-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}", *args], cwd=cwd)


def git(cwd: Path, *args: str) -> str:
    return run(["git", *args], cwd=cwd).stdout.strip()


def now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("ZTA_LEGACY_QUARANTINE=NO_TOKEN")
        return 78

    with tempfile.TemporaryDirectory(prefix="control-zta-legacy-quarantine-") as tmp:
        root = Path(tmp)
        code = root / "code"
        state = root / "state"
        code.mkdir()
        state.mkdir()

        run(["git", "init", "-q"], cwd=code)
        run(["git", "remote", "add", "origin", f"https://github.com/{CONTROL_REPOSITORY}.git"], cwd=code)
        private_git(token, ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{CODE_REF}"], cwd=code)
        run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=code)
        if git(code, "rev-parse", "HEAD") != CODE_SHA:
            print("ZTA_LEGACY_QUARANTINE=CODE_SHA_MISMATCH")
            return 2

        run(["git", "init", "-q"], cwd=state)
        run(["git", "remote", "add", "origin", f"https://github.com/{CONTROL_REPOSITORY}.git"], cwd=state)
        run(["git", "config", "user.name", "control-scheduled-a-v2[bot]"], cwd=state)
        run(["git", "config", "user.email", "control-scheduled-a-v2[bot]@users.noreply.github.com"], cwd=state)
        private_git(token, ["fetch", "--quiet", "origin", f"refs/heads/{RUNTIME_REF}"], cwd=state)
        run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=state)

        observed_ref = git(state, "rev-parse", "HEAD")
        observed_blob = git(state, "rev-parse", f"{observed_ref}:{QUEUE_PATH.as_posix()}")

        intake_file = state / INTAKE_PATH
        queue_file = state / QUEUE_PATH
        intake = json.loads(intake_file.read_text(encoding="utf-8"))
        queue = json.loads(queue_file.read_text(encoding="utf-8"))
        if queue.get("principal_manual_relay_count") != 0 or intake.get("principal_manual_relay_count") != 0:
            print("ZTA_LEGACY_QUARANTINE=RELAY_INVARIANT_FAILED")
            return 2

        task = next((item for item in queue.get("tasks", []) if item.get("task_id") == TASK_ID), None)
        if task is None:
            print("ZTA_LEGACY_QUARANTINE=TASK_MISSING")
            return 2

        if intake.get("queue_intent") is None:
            if task.get("paused") is True and task.get("current_blocker") == MARKER:
                print("ZTA_LEGACY_QUARANTINE=ALREADY_APPLIED")
                return 0
            print("ZTA_LEGACY_QUARANTINE=NULL_INTENT_WITHOUT_EXPECTED_PAUSE")
            return 2

        intent = intake.get("queue_intent")
        expected = (
            intake.get("version") == "1.0"
            and intake.get("project_id") == "ZORGTECHADVIES_PR7"
            and intake.get("repository") == "solidprivacy-nl/zorgtechadvies"
            and isinstance(intent, dict)
            and intent.get("revision") == R2
            and intent.get("supersedes_revision") == R1
            and intent.get("task_id") == TASK_ID
            and intent.get("operation") == "REPAIR"
            and intent.get("candidate_pr") == 7
            and intent.get("candidate_sha") == "5f707f5cb2d60a2e7ee66e958fee652c1be00bab"
            and intent.get("handover_id") is None
            and intent.get("assurance_result_ref") is None
            and task.get("repository") == "solidprivacy-nl/zorgtechadvies"
            and task.get("state") == "REPAIR_QUEUED"
            and task.get("intake_revision") == R1
            and task.get("candidate_pr") == 7
            and task.get("active_run_id") is None
            and task.get("active_role") is None
        )
        if not expected:
            print("ZTA_LEGACY_QUARANTINE=EXPECTED_STATE_MISMATCH")
            return 2

        intake["queue_intent"] = None
        task["paused"] = True
        task["current_blocker"] = MARKER
        findings = list(task.get("last_findings", []))
        if MARKER not in findings:
            findings.append(MARKER)
        task["last_findings"] = findings
        task["updated_at"] = now_z()

        sys.path.insert(0, str(code))
        from tools.control_orchestration_v1 import validate_project_intake  # type: ignore
        from tools.control_queue_v1 import validate_queue  # type: ignore

        validate_project_intake(intake)
        validate_queue(queue)
        intake_file.write_text(json.dumps(intake, indent=2) + "\n", encoding="utf-8")
        queue_file.write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")

        changed = set(git(state, "diff", "--name-only").splitlines())
        allowed = {INTAKE_PATH.as_posix(), QUEUE_PATH.as_posix()}
        if changed != allowed:
            print("ZTA_LEGACY_QUARANTINE=WRITE_SCOPE_FAILED")
            return 2

        private_git(token, ["fetch", "--quiet", "origin", f"refs/heads/{RUNTIME_REF}"], cwd=state)
        current_ref = git(state, "rev-parse", "FETCH_HEAD")
        current_blob = git(state, "rev-parse", f"{current_ref}:{QUEUE_PATH.as_posix()}")
        if current_ref != observed_ref or current_blob != observed_blob:
            print("ZTA_LEGACY_QUARANTINE=CAS_CONFLICT")
            return 75

        run(["git", "add", "--", INTAKE_PATH.as_posix(), QUEUE_PATH.as_posix()], cwd=state)
        run(["git", "commit", "--quiet", "-m", "runtime: quarantine legacy ZTA PR7 repair intake"], cwd=state)
        try:
            private_git(token, ["push", "--quiet", "origin", f"HEAD:refs/heads/{RUNTIME_REF}"], cwd=state)
        except subprocess.CalledProcessError:
            print("ZTA_LEGACY_QUARANTINE=PUSH_CONFLICT")
            return 75

    print("ZTA_LEGACY_QUARANTINE=APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
