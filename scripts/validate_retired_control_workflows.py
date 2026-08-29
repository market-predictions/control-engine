#!/usr/bin/env python3
"""Fail-closed structural validator for retired private Control workflows.

The validator intentionally supports only the tiny retirement-stub shape used by
Control. It is not a general YAML parser. A retired entrypoint is valid only when
manual invocation can execute exactly one inert job whose only shell actions are
safe explanatory echoes followed by `exit 1`.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


class RetiredWorkflowError(ValueError):
    pass


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
    return [line.strip() for line in block if line.strip() and not line.lstrip().startswith("#") and _indent(line) == indent]


def validate_retired_workflow(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    _require("\t" not in text, "tabs are not allowed")
    _require("[RETIRED]" in lines[0] if lines else False, "name must declare [RETIRED]")
    _require("write-all" not in text, "write-all permission is forbidden")
    _require(not re.search(r"(?m)^\s*[A-Za-z0-9_-]+:\s*write\s*$", text), "write permission is forbidden")
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
    _require(not any(line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2 for line in on_block), "workflow_dispatch inputs/options are forbidden")

    permissions_block = _block(lines, permissions_index, 0)
    _require(_direct(permissions_block, 2) == ["contents: read"], "permissions must be exactly contents: read")
    _require(not any(line.strip() and not line.lstrip().startswith("#") and _indent(line) > 2 for line in permissions_block), "nested permission grants are forbidden")

    jobs_block = _block(lines, jobs_index, 0)
    _require(_direct(jobs_block, 2) == ["retired:"], "exactly one retired job is required")
    retired_index = lines.index("  retired:", jobs_index + 1)
    retired_block = _block(lines, retired_index, 2)
    _require(_direct(retired_block, 4) == ["runs-on: ubuntu-latest", "steps:"], "retired job may contain only runner and steps")

    step_markers = [line.strip() for line in retired_block if _indent(line) == 6 and line.strip().startswith("- ")]
    _require(len(step_markers) == 1 and step_markers[0].startswith("- name: "), "exactly one rejection step is required")

    step_index = next(i for i in range(retired_index + 1, len(lines)) if _indent(lines[i]) == 6 and lines[i].strip().startswith("- name: "))
    step_block = _block(lines, step_index, 6)
    _require(_direct(step_block, 8) == ["shell: bash", "run: |"], "rejection step may contain only bash shell and run block")

    run_index = next(i for i in range(step_index + 1, len(lines)) if _indent(lines[i]) == 8 and lines[i].strip() == "run: |")
    run_block = _block(lines, run_index, 8)
    commands = [line.strip() for line in run_block if line.strip() and not line.lstrip().startswith("#")]
    _require(len(commands) >= 2, "rejection run block is incomplete")
    _require(commands[0] == "set -euo pipefail", "rejection must start fail-fast")
    _require(commands[-1] == "exit 1", "rejection must terminate with exit 1")
    for command in commands[1:-1]:
        _require(command.startswith("echo '") and command.endswith("'"), "only single-quoted explanatory echo commands are allowed")
        _require("$(" not in command and "`" not in command, "shell evaluation is forbidden in retirement messages")


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: validate_retired_control_workflows.py <workflow> [...]", file=sys.stderr)
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
