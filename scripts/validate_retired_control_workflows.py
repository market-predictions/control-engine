#!/usr/bin/env python3
"""Fail-closed validator for private Control workflow authority.

Retired entrypoints must match the tiny inert retirement-stub shape. Workflow
filenames stay exactly bound to trusted private `main`. Ordinary active workflows
must remain byte-identical to trusted main. A small, explicit set of existing
validation-only workflows may change during Minimal Core convergence, but only
under a strict read-only/no-secrets/no-schedule authority policy.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


class RetiredWorkflowError(ValueError):
    pass


RETIRED_WORKFLOW_PATHS = (
    ".github/workflows/control-manual-run-delivery.yml",
    ".github/workflows/control-zero-relay-dispatch.yml",
    ".github/workflows/control-zero-relay-implementation.yml",
    ".github/workflows/control-zero-relay-assurance.yml",
    ".github/workflows/control-zero-relay-provider-preflight.yml",
)

CONVERGENCE_VALIDATION_WORKFLOW_PATHS = (
    ".github/workflows/audit-control-state-freshness.yml",
    ".github/workflows/control-provider-preflight-bootstrap.yml",
    ".github/workflows/validate-agentic-runtime.yml",
    ".github/workflows/validate-provider-preflight-bootstrap.yml",
    ".github/workflows/validate-terminal-worker-completion.yml",
    ".github/workflows/validate-work-claim-lifecycle-standard.yml",
    ".github/workflows/validate-zero-relay-runtime.yml",
)

_ALLOWED_CONVERGENCE_TRIGGERS = {
    "pull_request",
    "push",
    "workflow_dispatch",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RetiredWorkflowError(message)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _block(lines: list[str], header_index: int, header_indent: int) -> list[str]:
    result: list[str] = []
    for line in lines[header_index + 1 :]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and _indent(line) <= header_indent:
            break
        result.append(line)
    return result


def _direct(block: list[str], indent: int) -> list[str]:
    return [
        line.strip()
        for line in block
        if line.strip() and not line.lstrip().startswith("#") and _indent(line) == indent
    ]


def validate_retired_workflow(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    _require("\t" not in text, "tabs are not allowed")
    _require("[RETIRED]" in lines[0] if lines else False, "name must declare [RETIRED]")
    _require("${{" not in text, "GitHub Actions expressions are forbidden in retired stubs")
    _require("write-all" not in text, "write-all permission is forbidden")
    _require(
        not re.search(r"(?m)^\s*[A-Za-z0-9_-]+:\s*write\s*$", text),
        "write permission is forbidden",
    )
    _require(not re.search(r"(?m)^\s*uses:\s*", text), "actions/uses steps are forbidden")

    top_level = [
        line.split(":", 1)[0]
        for line in lines
        if line and not line.startswith(" ") and not line.startswith("#") and ":" in line
    ]
    _require(
        top_level == ["name", "on", "permissions", "jobs"],
        "unexpected top-level workflow authority",
    )

    try:
        on_index = lines.index("on:")
        permissions_index = lines.index("permissions:")
        jobs_index = lines.index("jobs:")
    except ValueError as exc:
        raise RetiredWorkflowError("missing canonical retirement section") from exc

    on_block = _block(lines, on_index, 0)
    _require(
        _direct(on_block, 2) == ["workflow_dispatch:"],
        "only workflow_dispatch trigger is allowed",
    )
    _require(
        not any(
            line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2
            for line in on_block
        ),
        "workflow_dispatch inputs/options are forbidden",
    )

    permissions_block = _block(lines, permissions_index, 0)
    _require(
        _direct(permissions_block, 2) == ["contents: read"],
        "permissions must be exactly contents: read",
    )
    _require(
        not any(
            line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2
            for line in permissions_block
        ),
        "nested permission grants are forbidden",
    )

    jobs_block = _block(lines, jobs_index, 0)
    _require(_direct(jobs_block, 2) == ["retired:"], "exactly one retired job is required")
    retired_index = lines.index("  retired:", jobs_index + 1)
    retired_block = _block(lines, retired_index, 2)
    _require(
        _direct(retired_block, 4) == ["runs-on: ubuntu-latest", "steps:"],
        "retired job may contain only runner and steps",
    )

    step_markers = [
        line.strip()
        for line in retired_block
        if _indent(line) == 6 and line.strip().startswith("- ")
    ]
    _require(
        len(step_markers) == 1 and step_markers[0].startswith("- name: "),
        "exactly one rejection step is required",
    )

    step_index = next(
        i
        for i in range(retired_index + 1, len(lines))
        if _indent(lines[i]) == 6 and lines[i].strip().startswith("- name: ")
    )
    step_block = _block(lines, step_index, 6)
    _require(
        _direct(step_block, 8) == ["shell: bash", "run: |"],
        "rejection step may contain only bash shell and run block",
    )

    run_index = next(
        i
        for i in range(step_index + 1, len(lines))
        if _indent(lines[i]) == 8 and lines[i].strip() == "run: |"
    )
    run_block = _block(lines, run_index, 8)
    commands = [
        line.strip()
        for line in run_block
        if line.strip() and not line.lstrip().startswith("#")
    ]
    _require(len(commands) >= 2, "rejection run block is incomplete")
    _require(commands[0] == "set -euo pipefail", "rejection must start fail-fast")
    _require(commands[-1] == "exit 1", "rejection must terminate with exit 1")
    for command in commands[1:-1]:
        _require(
            re.fullmatch(r"echo '[^']*'", command) is not None,
            "only one literal single-quoted explanatory echo is allowed per command",
        )


def validate_read_only_convergence_workflow(path: Path) -> None:
    """Validate the authority envelope for a mutable validation-only workflow."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    _require("\t" not in text, "tabs are not allowed in convergence validation workflow")
    _require("write-all" not in text, "write-all permission is forbidden")
    _require(
        not re.search(r"(?m)^\s*[A-Za-z0-9_-]+:\s*write\s*$", text),
        "write permission is forbidden",
    )
    _require("${{ secrets." not in text, "secrets are forbidden in convergence validation workflow")
    _require("${{ vars." not in text, "repository variables are forbidden in convergence validation workflow")
    _require("${{ github.token }}" not in text, "explicit GitHub token use is forbidden")
    _require("CONTROL_PLANE_GITHUB_TOKEN" not in text, "private token use is forbidden")
    _require("persist-credentials: true" not in text, "checkout credentials may not persist")
    _require("actions/upload-artifact" not in text, "artifact upload is forbidden")
    _require("actions/download-artifact" not in text, "artifact download is forbidden")
    _require(
        re.search(r"(?i)\b(?:curl|wget|scp|rsync)\b", text) is None,
        "network transfer command is forbidden",
    )
    _require(re.search(r"(?i)\bgit\s+push\b", text) is None, "git push is forbidden")
    _require(re.search(r"(?i)\bgit\s+remote\b", text) is None, "git remote mutation is forbidden")

    try:
        on_index = lines.index("on:")
        permissions_index = lines.index("permissions:")
        lines.index("jobs:")
    except ValueError as exc:
        raise RetiredWorkflowError("missing convergence validation workflow section") from exc

    permission_headers = [i for i, line in enumerate(lines) if line.strip() == "permissions:"]
    _require(permission_headers == [permissions_index], "job/step permission overrides are forbidden")
    permissions_block = _block(lines, permissions_index, 0)
    _require(
        _direct(permissions_block, 2) == ["contents: read"],
        "permissions must be exactly contents: read",
    )
    _require(
        not any(
            line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2
            for line in permissions_block
        ),
        "nested permission grants are forbidden",
    )

    on_block = _block(lines, on_index, 0)
    direct_triggers = _direct(on_block, 2)
    trigger_names = {line.split(":", 1)[0] for line in direct_triggers if ":" in line}
    _require(bool(trigger_names), "at least one workflow trigger is required")
    _require(
        trigger_names <= _ALLOWED_CONVERGENCE_TRIGGERS,
        "convergence validation workflow has forbidden trigger authority",
    )

    checkout_count = text.count("uses: actions/checkout@")
    _require(checkout_count >= 1, "convergence validation workflow must checkout source")
    _require(
        checkout_count == text.count("persist-credentials: false"),
        "every checkout must disable persisted credentials",
    )


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), *args],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError as exc:
        raise RetiredWorkflowError(f"git inspection failed: {' '.join(args)}") from exc


def _workflow_tree(repo: Path, revision: str) -> dict[str, tuple[str, str]]:
    try:
        raw = subprocess.check_output(
            [
                "git",
                "-C",
                str(repo),
                "ls-tree",
                "-r",
                "--full-tree",
                "-z",
                revision,
                "--",
                ".github/workflows",
            ],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError as exc:
        raise RetiredWorkflowError("git workflow tree inspection failed") from exc

    result: dict[str, tuple[str, str]] = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            meta, raw_path = record.split(b"\t", 1)
            mode_raw, object_type_raw, object_sha_raw = meta.split(b" ", 2)
            mode = mode_raw.decode("ascii")
            object_type = object_type_raw.decode("ascii")
            object_sha = object_sha_raw.decode("ascii")
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise RetiredWorkflowError("unexpected git workflow tree entry") from exc
        if not path.endswith((".yml", ".yaml")):
            continue
        _require(object_type == "blob", f"workflow is not a blob: {path}")
        _require(mode == "100644", f"workflow has unexpected mode: {path}")
        result[path] = (mode, object_sha)
    return result


def validate_control_workflow_inventory(
    repo: Path,
    trusted_main_sha: str,
    retired_paths: tuple[str, ...] = RETIRED_WORKFLOW_PATHS,
    mutable_validation_paths: tuple[str, ...] = CONVERGENCE_VALIDATION_WORKFLOW_PATHS,
) -> None:
    _require(repo.is_dir(), "candidate repository is missing")
    _require(re.fullmatch(r"[0-9a-f]{40}", trusted_main_sha) is not None, "invalid trusted main SHA")
    candidate_sha = _git(repo, "rev-parse", "HEAD")
    _require(re.fullmatch(r"[0-9a-f]{40}", candidate_sha) is not None, "invalid candidate HEAD")
    _git(repo, "cat-file", "-e", f"{trusted_main_sha}^{{commit}}")

    candidate = _workflow_tree(repo, candidate_sha)
    trusted = _workflow_tree(repo, trusted_main_sha)
    _require(set(candidate) == set(trusted), "workflow filename inventory differs from trusted main")

    retired = set(retired_paths)
    mutable = set(mutable_validation_paths)
    _require(retired <= set(candidate), "required retired workflow is missing")
    _require(mutable <= set(candidate), "required convergence validation workflow is missing")
    _require(retired.isdisjoint(mutable), "retired and mutable validation workflow sets overlap")

    for path, candidate_identity in candidate.items():
        if path in retired:
            validate_retired_workflow(repo / path)
        elif candidate_identity != trusted[path]:
            _require(path in mutable, f"active workflow differs from trusted main: {path}")
            validate_read_only_convergence_workflow(repo / path)


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--repo":
        repo = Path(argv[1])
        trusted_main_sha = argv[2]
        try:
            validate_control_workflow_inventory(repo, trusted_main_sha)
        except (OSError, RetiredWorkflowError) as exc:
            print(f"PRIVATE_CONTROL_WORKFLOW_VALIDATION=FAIL:{exc}", file=sys.stderr)
            return 1
        print("PRIVATE_CONTROL_WORKFLOW_VALIDATION=PASS")
        return 0

    if not argv:
        print(
            "usage: validate_retired_control_workflows.py --repo <repo> <trusted-main-sha> | <workflow> [...]",
            file=sys.stderr,
        )
        return 2
    try:
        for raw in argv:
            validate_retired_workflow(Path(raw))
    except (OSError, RetiredWorkflowError) as exc:
        print(f"RETIRED_CONTROL_WORKFLOW_VALIDATION=FAIL:{exc}", file=sys.stderr)
        return 1
    print(f"RETIRED_CONTROL_WORKFLOW_VALIDATION=PASS count={len(argv)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
