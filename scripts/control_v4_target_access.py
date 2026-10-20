from __future__ import annotations

"""Exact, read-only target GitHub capability for the existing V4 carrier.

The native workflow creates a short-lived GitHub App token limited to a target
repository that is selected from *current* private Mission/queue authority.
This module never issues tokens or grants Control task/merge authority.
"""

import os
from typing import Any, Callable, Mapping


class TargetAccessError(RuntimeError):
    pass


def selected_repositories() -> frozenset[str]:
    raw = os.environ.get("CONTROL_TARGET_REPOSITORIES", "")
    repositories = [value.strip() for value in raw.splitlines() if value.strip()]
    if len(repositories) != len(set(repositories)):
        raise TargetAccessError("duplicate target capability scope")
    return frozenset(repositories)


def target_headers(path: str) -> dict[str, str]:
    """Attach target credentials ONLY to an exact allowed /repos/{owner}/{repo} API path."""
    for repository in selected_repositories():
        prefix = f"repos/{repository}"
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
            token = os.environ.get("CONTROL_TARGET_READ_TOKEN", "")
            if not token:
                raise TargetAccessError("scoped target read capability unavailable")
            return {"Authorization": f"Bearer {token}"}
    return {}


def assert_supported_target(
    repository: str,
    read: Callable[[str], Any],
) -> None:
    """Validate exact repository identity and its public or private read contract."""
    observed = read(f"repos/{repository}")
    if not isinstance(observed, Mapping) or observed.get("full_name") != repository:
        raise TargetAccessError("target repository identity unavailable or mismatched")
    privacy = observed.get("private")
    if privacy is False:
        return
    if privacy is not True or repository not in selected_repositories():
        raise TargetAccessError("private target has no exact scoped read capability")
    if not os.environ.get("CONTROL_TARGET_READ_TOKEN", ""):
        raise TargetAccessError("private target read token unavailable")
