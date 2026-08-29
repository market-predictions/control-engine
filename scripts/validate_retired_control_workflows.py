#!/usr/bin/env python3
"""Fail-closed validator for private Control workflow authority.

Retired entrypoints must match the tiny inert retirement-stub shape. Every other
workflow is active authority and must remain byte-identical to trusted private
`main`; candidates may not add, remove, rename or mutate active workflows through
this deterministic validation carrier.
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
    _require(retired <= set(candidate), "required retired workflow is missing")

    for path, candidate_identity in candidate.items():
        if path in retired:
            validate_retired_workflow(repo / path)
        else:
            _require(
                candidate_identity == trusted[path],
                f"active workflow differs from trusted main: {path}",
            )


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
