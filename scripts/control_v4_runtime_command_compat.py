from __future__ import annotations

"""Narrow public transport compatibility for the observed V4 Runner event envelope.

The canonical carrier protocol remains authoritative. This helper only rewrites the
exact observed REVIEW_UNAVAILABLE envelope emitted by the Scheduled Runner into the
existing flat holder-identity EVENT shape. Everything else is passed through so the
carrier parser can accept or reject it normally.
"""

import json
import os
import re


EVENT_PREFIX = "CONTROL_V4_RUNTIME_EVENT "
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
NESTED_KEYS = {"run_id", "task_token", "event", "repository", "candidate"}
CANDIDATE_KEYS = {
    "candidate_sha",
    "candidate_pr_number",
    "candidate_head_branch",
    "expected_base_branch",
    "expected_base_sha",
}


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError(key)
        value[key] = item
    return value


def _strict_object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, _DuplicateKeyError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def normalize_runner_command(command: str) -> str:
    if not isinstance(command, str) or not command.startswith(EVENT_PREFIX):
        return command

    payload = _strict_object(command[len(EVENT_PREFIX):])
    if payload is None or payload.get("event") != "REVIEW_UNAVAILABLE":
        return command
    if set(payload) != NESTED_KEYS:
        return command

    repository = payload.get("repository")
    candidate = payload.get("candidate")
    if (
        not isinstance(repository, str)
        or "/" not in repository
        or not isinstance(candidate, dict)
        or set(candidate) != CANDIDATE_KEYS
    ):
        return command

    candidate_sha = candidate.get("candidate_sha")
    expected_base_sha = candidate.get("expected_base_sha")
    expected_base_branch = candidate.get("expected_base_branch")
    candidate_head_branch = candidate.get("candidate_head_branch")
    candidate_pr_number = candidate.get("candidate_pr_number")
    if (
        not isinstance(candidate_sha, str)
        or SHA1_RE.fullmatch(candidate_sha) is None
        or not isinstance(expected_base_sha, str)
        or SHA1_RE.fullmatch(expected_base_sha) is None
        or not isinstance(expected_base_branch, str)
        or not expected_base_branch
        or not isinstance(candidate_head_branch, str)
        or not candidate_head_branch
        or not isinstance(candidate_pr_number, int)
        or isinstance(candidate_pr_number, bool)
        or candidate_pr_number < 1
    ):
        return command

    normalized = {
        "run_id": payload.get("run_id"),
        "task_token": payload.get("task_token"),
        "event": "REVIEW_UNAVAILABLE",
        "holder_candidate_sha": candidate_sha,
        "holder_expected_base_branch": expected_base_branch,
        "holder_expected_base_sha": expected_base_sha,
    }
    return EVENT_PREFIX + json.dumps(normalized, separators=(",", ":"), sort_keys=True)


def main() -> int:
    print(normalize_runner_command(os.environ.get("CONTROL_V4_PUBLIC_COMMAND", "")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
