#!/usr/bin/env python3
"""Private-only intake validation receipt for Scheduled Worker A V2.

No private intake content is written to the public repository, logs, artifacts or
commit statuses. Concrete validation findings are written only to private Control
recovery issue #187 through the short-lived GitHub App installation token.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

CONTROL_REPOSITORY = "market-predictions/control-plane"
CONTROL_RUNTIME_REF = "control-runtime-state"
CONTROL_CODE_REF = "control/171-intake-queue-reconciliation-v1"
CONTROL_CODE_SHA = "ca9c9759a07fd4943e31a94d81a3af7c1aaf9534"
RECOVERY_ISSUE = 187
MARKER = "<!-- scheduled-worker-a-v2-private-intake-diagnostic -->"


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=capture,
        check=True,
    )


def private_git(token: str, args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return run(["git", "-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}", *args], cwd=cwd)


def gh(token: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GH_TOKEN"] = token
    return run(["gh", "api", *args], env=env)


def post_or_update_receipt(token: str, body: str) -> None:
    comments = gh(token, [f"repos/{CONTROL_REPOSITORY}/issues/{RECOVERY_ISSUE}/comments", "-f", "per_page=100"]).stdout
    existing_id: int | None = None
    for item in json.loads(comments):
        if MARKER in (item.get("body") or ""):
            existing_id = int(item["id"])
    if existing_id is None:
        gh(token, ["-X", "POST", f"repos/{CONTROL_REPOSITORY}/issues/{RECOVERY_ISSUE}/comments", "-f", f"body={body}"])
    else:
        gh(token, ["-X", "PATCH", f"repos/{CONTROL_REPOSITORY}/issues/comments/{existing_id}", "-f", f"body={body}"])


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("PRIVATE_INTAKE_DIAGNOSTIC=NO_TOKEN")
        return 0

    findings: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="control-private-intake-diagnostic-") as temp:
        root = Path(temp)
        code = root / "code"
        state = root / "state"
        code.mkdir()
        state.mkdir()

        run(["git", "init", "-q"], cwd=code)
        run(["git", "remote", "add", "origin", f"https://github.com/{CONTROL_REPOSITORY}.git"], cwd=code)
        private_git(token, ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{CONTROL_CODE_REF}"], cwd=code)
        run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=code)
        actual_sha = run(["git", "rev-parse", "HEAD"], cwd=code).stdout.strip()
        if actual_sha != CONTROL_CODE_SHA:
            print("PRIVATE_INTAKE_DIAGNOSTIC=CODE_SHA_MISMATCH")
            return 0

        run(["git", "init", "-q"], cwd=state)
        run(["git", "remote", "add", "origin", f"https://github.com/{CONTROL_REPOSITORY}.git"], cwd=state)
        private_git(token, ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{CONTROL_RUNTIME_REF}"], cwd=state)
        run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=state)

        sys.path.insert(0, str(code))
        from tools.control_orchestration_v1 import validate_project_intake  # type: ignore

        intake_dir = state / "control" / "project-intake"
        for path in sorted(intake_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # JSON parse/type only; details stay private.
                findings.append((path.name, f"JSON_LOAD_ERROR: {type(exc).__name__}: {exc}"))
                continue
            try:
                validate_project_intake(payload)
            except Exception as exc:
                findings.append((path.name, f"VALIDATION_ERROR: {type(exc).__name__}: {exc}"))

    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    run_attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "unknown")
    if findings:
        lines = [
            MARKER,
            "### Scheduled Worker A V2 — private intake diagnostic",
            "",
            f"Run: `{run_id}` attempt `{run_attempt}`",
            f"Invalid intake files: **{len(findings)}**",
            "",
        ]
        for filename, reason in findings[:25]:
            lines.append(f"- `{filename}` — `{reason}`")
        if len(findings) > 25:
            lines.append(f"- … {len(findings) - 25} additional invalid intake file(s) omitted")
        lines.extend(["", "This receipt contains no credentials, prompts, model output or private file contents."])
        post_or_update_receipt(token, "\n".join(lines))
        print("PRIVATE_INTAKE_DIAGNOSTIC=INVALID")
    else:
        body = "\n".join(
            [
                MARKER,
                "### Scheduled Worker A V2 — private intake diagnostic",
                "",
                f"Run: `{run_id}` attempt `{run_attempt}`",
                "All canonical `control/project-intake/*.json` records passed `validate_project_intake` at the pinned Control code SHA.",
            ]
        )
        post_or_update_receipt(token, body)
        print("PRIVATE_INTAKE_DIAGNOSTIC=VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
