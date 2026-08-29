#!/usr/bin/env python3
"""Fail-closed validator for private Control workflow authority.

The complete workflow filename inventory is bound to trusted private `main`.
Retired semantic entrypoints must satisfy the tiny inert retirement-stub shape.
Every other active workflow must remain blob-identical to trusted main, except
for seven one-time Minimal Core convergence migrations whose exact trusted-main
source blob and frozen PR #208 target blob are pinned below. Once those target
blobs become private main, the exception cannot be replayed.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping


class RetiredWorkflowError(ValueError):
    pass


RETIRED_WORKFLOW_PATHS = (
    ".github/workflows/control-manual-run-delivery.yml",
    ".github/workflows/control-zero-relay-dispatch.yml",
    ".github/workflows/control-zero-relay-implementation.yml",
    ".github/workflows/control-zero-relay-assurance.yml",
    ".github/workflows/control-zero-relay-provider-preflight.yml",
)

# path -> (trusted private-main source blob, frozen PR #208 target blob)
CONVERGENCE_WORKFLOW_TRANSITIONS: dict[str, tuple[str, str]] = {
    ".github/workflows/audit-control-state-freshness.yml": (
        "97462e16d722e69f6170068e2b9e7d11eaa7e0c4",
        "eaab0e71bc7fcfcfe9aa0bf061e0bcd8c167be3c",
    ),
    ".github/workflows/control-provider-preflight-bootstrap.yml": (
        "4fdb9663ce16da55de65f7466e1f200ade398b69",
        "f021b705026dc18b5c6cf0323b0e97d913411ecc",
    ),
    ".github/workflows/validate-agentic-runtime.yml": (
        "727d85aec8d029ccf826d2c4c6dd758ecb608dd4",
        "ee98bd5a4c4378dea62890d22b65c99d7ee066c7",
    ),
    ".github/workflows/validate-provider-preflight-bootstrap.yml": (
        "e804414ee380731db0d41cfdf43288460ab0aae5",
        "d9ebd3f59a140be55863dee63ac118603e4d2835",
    ),
    ".github/workflows/validate-terminal-worker-completion.yml": (
        "1554419e64b3da0eeecb0df858574bbf4876f1b1",
        "984188d1d407c00588628977cfd0ae1801167804",
    ),
    ".github/workflows/validate-work-claim-lifecycle-standard.yml": (
        "a926886b75b5c04df20d9bdf07a8ed380ff6664b",
        "f2cb92f67e046ca8a346f259105119eae5b53c7c",
    ),
    ".github/workflows/validate-zero-relay-runtime.yml": (
        "5f2325281fed4afbb58648cde4d893209a8bfedf",
        "9ad04ce6d8775daf25030768f65573f14cef35c7",
    ),
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
    _require(top_level == ["name", "on", "permissions", "jobs"], "unexpected top-level workflow authority")

    try:
        on_index = lines.index("on:")
        permissions_index = lines.index("permissions:")
        jobs_index = lines.index("jobs:")
    except ValueError as exc:
        raise RetiredWorkflowError("missing canonical retirement section") from exc

    on_block = _block(lines, on_index, 0)
    _require(_direct(on_block, 2) == ["workflow_dispatch:"], "only workflow_dispatch trigger is allowed")
    _require(
        not any(line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2 for line in on_block),
        "workflow_dispatch inputs/options are forbidden",
    )

    permissions_block = _block(lines, permissions_index, 0)
    _require(_direct(permissions_block, 2) == ["contents: read"], "permissions must be exactly contents: read")
    _require(
        not any(line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2 for line in permissions_block),
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

    step_markers = [line.strip() for line in retired_block if _indent(line) == 6 and line.strip().startswith("- ")]
    _require(len(step_markers) == 1 and step_markers[0].startswith("- name: "), "exactly one rejection step is required")

    step_index = next(
        i for i in range(retired_index + 1, len(lines))
        if _indent(lines[i]) == 6 and lines[i].strip().startswith("- name: ")
    )
    step_block = _block(lines, step_index, 6)
    _require(_direct(step_block, 8) == ["shell: bash", "run: |"], "rejection step may contain only bash shell and run block")

    run_index = next(
        i for i in range(step_index + 1, len(lines))
        if _indent(lines[i]) == 8 and lines[i].strip() == "run: |"
    )
    commands = [line.strip() for line in _block(lines, run_index, 8) if line.strip() and not line.lstrip().startswith("#")]
    _require(len(commands) >= 2, "rejection run block is incomplete")
    _require(commands[0] == "set -euo pipefail", "rejection must start fail-fast")
    _require(commands[-1] == "exit 1", "rejection must terminate with exit 1")
    for command in commands[1:-1]:
        _require(re.fullmatch(r"echo '[^']*'", command) is not None, "only literal single-quoted explanatory echoes are allowed")


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError as exc:
        raise RetiredWorkflowError(f"git inspection failed: {' '.join(args)}") from exc


def _workflow_tree(repo: Path, revision: str) -> dict[str, tuple[str, str]]:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(repo), "ls-tree", "-r", "--full-tree", "-z", revision, "--", ".github/workflows"],
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
    transitions: Mapping[str, tuple[str, str]] = CONVERGENCE_WORKFLOW_TRANSITIONS,
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
    _require(set(transitions).isdisjoint(retired), "retired and migration workflow sets overlap")

    for path, candidate_identity in candidate.items():
        if path in retired:
            validate_retired_workflow(repo / path)
            continue
        if candidate_identity == trusted[path]:
            continue

        _require(path in transitions, f"active workflow differs from trusted main: {path}")
        source_blob, target_blob = transitions[path]
        _require(
            trusted[path] == ("100644", source_blob),
            f"migration source workflow identity differs from pinned trusted main: {path}",
        )
        _require(
            candidate_identity == ("100644", target_blob),
            f"migration target workflow identity differs from frozen candidate: {path}",
        )


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--repo":
        try:
            validate_control_workflow_inventory(Path(argv[1]), argv[2])
        except (OSError, RetiredWorkflowError) as exc:
            print(f"PRIVATE_CONTROL_WORKFLOW_VALIDATION=FAIL:{exc}", file=sys.stderr)
            return 1
        print("PRIVATE_CONTROL_WORKFLOW_VALIDATION=PASS")
        return 0

    if not argv:
        print("usage: validate_retired_control_workflows.py --repo <repo> <trusted-main-sha> | <workflow> [...]", file=sys.stderr)
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
