#!/usr/bin/env python3
"""Deterministic PROJECT_INTEGRATION actuator for Scheduled Worker A V2.

The public repository contains only public-safe code. Runtime state, assurance
results, handovers and live PR metadata are processed transiently on the trusted
runner and are never written to public logs/artifacts/caches.
"""

from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request


CONTROL_REPOSITORY = "market-predictions/control-plane"
CONTROL_RUNTIME_REF = "control-runtime-state"
CONTROL_CODE_REF = "control/171-intake-queue-reconciliation-v1"
CONTROL_CODE_SHA = "ca9c9759a07fd4943e31a94d81a3af7c1aaf9534"
MAX_CAS_ATTEMPTS = 7
LEASE_MINUTES = 75
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PROJECT_INTAKE_PATH_RE = re.compile(r"^control/project-intake/[A-Za-z0-9_.-]+\.json$")
STATUS_PREFIX = "SCHEDULED_WORKER_A_INTEGRATION="
HANDLED_PREFIX = "SCHEDULED_WORKER_A_INTEGRATION_HANDLED="


class IntegrationError(RuntimeError):
    pass


class IntegrationBlocked(IntegrationError):
    pass


class IntegrationUnavailable(IntegrationError):
    pass


def _status(name: str, *, handled: bool) -> None:
    print(f"{STATUS_PREFIX}{name}")
    print(f"{HANDLED_PREFIX}{str(handled).lower()}")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise IntegrationError(f"subprocess failed: {cmd[0]}")
    return result


def _private_git(token: str, cwd: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return _run(
        ["git", "-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {auth}", *args],
        cwd=cwd,
        check=check,
    )


def _api(token: str, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.github.com/{path.lstrip('/')}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "control-scheduled-worker-a-v2")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {429, 500, 502, 503, 504}:
            raise IntegrationUnavailable(f"GitHub API transient HTTP {exc.code}") from exc
        raise IntegrationBlocked(f"GitHub API HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise IntegrationUnavailable("GitHub API unavailable") from exc


def _init_repo(path: Path, remote: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], cwd=path)
    _run(["git", "remote", "add", "origin", remote], cwd=path)


def _fetch_code(token: str, code_dir: Path) -> None:
    _init_repo(code_dir, f"https://github.com/{CONTROL_REPOSITORY}.git")
    _private_git(token, code_dir, ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{CONTROL_CODE_REF}"])
    _run(["git", "checkout", "--detach", "--quiet", "FETCH_HEAD"], cwd=code_dir)
    actual = _run(["git", "rev-parse", "HEAD"], cwd=code_dir).stdout.strip()
    if actual != CONTROL_CODE_SHA:
        raise IntegrationBlocked("private Control code SHA mismatch")


def _reset_state(token: str, state_dir: Path) -> None:
    result = _private_git(
        token,
        state_dir,
        ["fetch", "--quiet", "origin", f"refs/heads/{CONTROL_RUNTIME_REF}"],
        check=False,
    )
    if result.returncode != 0:
        raise IntegrationUnavailable("private runtime fetch unavailable")
    _run(["git", "reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=state_dir)
    _run(["git", "clean", "-fdq"], cwd=state_dir)


def _identity(state_dir: Path, ref: str = "HEAD") -> tuple[str, str]:
    commit = _run(["git", "rev-parse", ref], cwd=state_dir).stdout.strip()
    blob = _run(["git", "rev-parse", f"{commit}:control/DISPATCH_QUEUE.json"], cwd=state_dir).stdout.strip()
    return commit, blob


def _remote_identity(token: str, state_dir: Path) -> tuple[str, str]:
    result = _private_git(
        token,
        state_dir,
        ["fetch", "--quiet", "origin", f"refs/heads/{CONTROL_RUNTIME_REF}"],
        check=False,
    )
    if result.returncode != 0:
        raise IntegrationUnavailable("private runtime ref fetch unavailable")
    return _identity(state_dir, "FETCH_HEAD")


def _changed_paths(state_dir: Path) -> set[str]:
    tracked = _run(["git", "diff", "--name-only"], cwd=state_dir).stdout.splitlines()
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=state_dir).stdout.splitlines()
    return {item for item in tracked + untracked if item}


def _extend_reconcile_write_scope(allowed: set[str], changed: set[str]) -> set[str]:
    result = set(allowed)
    result.update(path for path in changed if PROJECT_INTAKE_PATH_RE.fullmatch(path))
    return result


def _persist(
    token: str,
    state_dir: Path,
    *,
    message: str,
    paths: list[str],
    allowed: set[str],
) -> bool:
    changed = _changed_paths(state_dir)
    if not changed:
        return True
    if not changed.issubset(allowed):
        raise IntegrationBlocked("private runtime write scope exceeded")
    _run(["git", "add", "--", *paths], cwd=state_dir)
    _run(["git", "commit", "--quiet", "-m", message], cwd=state_dir)
    pushed = _private_git(
        token,
        state_dir,
        ["push", "--quiet", "origin", f"HEAD:refs/heads/{CONTROL_RUNTIME_REF}"],
        check=False,
    )
    return pushed.returncode == 0


def _private_modules(code_dir: Path):
    root = str(code_dir.resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    parallel = importlib.import_module("tools.control_parallel_execution_v1")
    queue_mod = importlib.import_module("tools.control_queue_v1")
    gate_mod = importlib.import_module("tools.control_integration_claim_gate_v1")
    handover_mod = importlib.import_module("tools.validate_handover_contract")
    return parallel, queue_mod, gate_mod, handover_mod


def _find_task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise IntegrationBlocked("canonical task identity is not unique")
    return matches[0]


def _select_integration(code_dir: Path, state_dir: Path) -> dict[str, Any] | None:
    parallel, queue_mod, _, _ = _private_modules(code_dir)
    queue = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
    parallel.validate_parallel_queue(queue)
    selected = parallel.select_task_for_instance(queue, queue_mod.ROLE_A, parallel.INSTANCE_A1)
    if selected is None or selected.get("operation") != "PROJECT_INTEGRATION":
        return None
    return copy.deepcopy(selected)


def _reconcile_once(token: str, code_dir: Path, state_dir: Path, private_tmp: Path) -> None:
    from control_engine.scheduled_worker_a import resume_a_unavailable

    for _ in range(MAX_CAS_ATTEMPTS):
        _reset_state(token, state_dir)
        observed = _identity(state_dir)
        allowed = {
            "control/DISPATCH_QUEUE.json",
            "control/DISPATCH_RUNS.json",
        }
        for path in (state_dir / "control" / "project-intake").glob("*.json"):
            allowed.add(path.relative_to(state_dir).as_posix())

        _run(
            [
                sys.executable,
                str(code_dir / "dispatcher" / "cli.py"),
                "reconcile",
                "--queue",
                str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                "--runs",
                str(state_dir / "control" / "DISPATCH_RUNS.json"),
            ]
        )
        resume_a_unavailable(
            str(code_dir),
            str(state_dir / "control" / "DISPATCH_QUEUE.json"),
            str(private_tmp / "resume-a.json"),
        )
        _run(
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
                str(private_tmp / "intake-report.json"),
            ]
        )
        _run(
            [
                sys.executable,
                str(code_dir / "dispatcher" / "cli.py"),
                "validate",
                "--queue",
                str(state_dir / "control" / "DISPATCH_QUEUE.json"),
            ]
        )
        allowed = _extend_reconcile_write_scope(allowed, _changed_paths(state_dir))
        current = _remote_identity(token, state_dir)
        if current != observed:
            continue
        if _persist(
            token,
            state_dir,
            message="runtime: Scheduled Worker A integration reconcile before selection",
            paths=["control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json", "control/project-intake"],
            allowed=allowed,
        ):
            return
    raise IntegrationUnavailable("runtime CAS conflict during integration reconciliation")


def _claim_selected(
    token: str,
    code_dir: Path,
    state_dir: Path,
    task_id: str,
) -> tuple[str, dict[str, Any]] | None:
    parallel, queue_mod, _, _ = _private_modules(code_dir)
    allowed = {"control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"}
    for _ in range(MAX_CAS_ATTEMPTS):
        _reset_state(token, state_dir)
        selected = _select_integration(code_dir, state_dir)
        if selected is None or selected.get("task_id") != task_id:
            return None
        observed = _identity(state_dir)
        result = _run(
            [
                sys.executable,
                str(code_dir / "dispatcher" / "cli.py"),
                "claim",
                "--queue",
                str(state_dir / "control" / "DISPATCH_QUEUE.json"),
                "--runs",
                str(state_dir / "control" / "DISPATCH_RUNS.json"),
                "--task-id",
                task_id,
                "--backend",
                "github-actions/public-control-engine-project-integration-v1",
                "--lease-minutes",
                str(LEASE_MINUTES),
            ],
            check=False,
        )
        if result.returncode != 0:
            raise IntegrationBlocked("canonical integration claim failed")
        _run(
            [
                sys.executable,
                str(code_dir / "dispatcher" / "cli.py"),
                "validate",
                "--queue",
                str(state_dir / "control" / "DISPATCH_QUEUE.json"),
            ]
        )
        if _remote_identity(token, state_dir) != observed:
            continue
        if not _persist(
            token,
            state_dir,
            message="runtime: Scheduled Worker A V2 claim PROJECT_INTEGRATION",
            paths=["control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"],
            allowed=allowed,
        ):
            continue
        _reset_state(token, state_dir)
        queue = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
        task = _find_task(queue, task_id)
        run_id = task.get("active_run_id")
        if not isinstance(run_id, str) or not run_id:
            raise IntegrationBlocked("integration START_PROVEN run id missing")
        parallel.assert_claim_current(
            queue,
            task_id=task_id,
            role=queue_mod.ROLE_A,
            worker_instance=parallel.INSTANCE_A1,
            run_id=run_id,
            now=datetime.now(timezone.utc),
        )
        if task.get("operation") != "PROJECT_INTEGRATION":
            raise IntegrationBlocked("claimed task operation drifted")
        if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
            raise IntegrationBlocked("principal manual relay invariant changed")
        return run_id, copy.deepcopy(task)
    raise IntegrationUnavailable("runtime CAS conflict while claiming integration")


def _trusted_base_sha(repository: str, handover: dict[str, Any]) -> str:
    prefix = f"https://github.com/{repository}/commit/"
    candidates: set[str] = set()
    for item in handover.get("context_refs", []):
        if not isinstance(item, dict) or item.get("kind") != "source":
            continue
        immutable = item.get("immutable_ref")
        locator = item.get("locator")
        if isinstance(immutable, str) and SHA_RE.fullmatch(immutable) and locator == prefix + immutable:
            candidates.add(immutable)
    if len(candidates) != 1:
        raise IntegrationBlocked("handover does not bind exactly one trusted base commit")
    return next(iter(candidates))


def _ci_run_ids(repository: str, candidate_sha: str, handover: dict[str, Any]) -> list[int]:
    prefix = f"https://github.com/{repository}/actions/runs/"
    run_ids: list[int] = []
    for item in handover.get("context_refs", []):
        if not isinstance(item, dict) or item.get("kind") != "raw_ci":
            continue
        locator = item.get("locator")
        if item.get("immutable_ref") != candidate_sha or not isinstance(locator, str) or not locator.startswith(prefix):
            raise IntegrationBlocked("handover raw CI binding is malformed")
        suffix = locator[len(prefix):]
        if not suffix.isdigit():
            raise IntegrationBlocked("handover raw CI run id is invalid")
        run_ids.append(int(suffix))
    if not run_ids:
        raise IntegrationBlocked("handover contains no exact-head raw CI evidence")
    return sorted(set(run_ids))


def _pr_snapshot(token: str, repository: str, pr_number: int) -> dict[str, Any]:
    raw: dict[str, Any] | None = None
    for _ in range(5):
        raw = _api(token, "GET", f"repos/{repository}/pulls/{pr_number}")
        if raw.get("mergeable") is not None or raw.get("merged") is True:
            break
        time.sleep(1)
    assert raw is not None
    return {
        "number": raw.get("number"),
        "head_sha": (raw.get("head") or {}).get("sha"),
        "base_sha": (raw.get("base") or {}).get("sha"),
        "base_ref": (raw.get("base") or {}).get("ref"),
        "state": raw.get("state"),
        "merged": bool(raw.get("merged")),
        "mergeable": raw.get("mergeable"),
        "draft": bool(raw.get("draft")),
        "merge_commit_sha": raw.get("merge_commit_sha"),
    }


def _ci_green(token: str, repository: str, candidate_sha: str, handover: dict[str, Any]) -> bool:
    for run_id in _ci_run_ids(repository, candidate_sha, handover):
        run = _api(token, "GET", f"repos/{repository}/actions/runs/{run_id}")
        if run.get("head_sha") != candidate_sha:
            return False
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            return False
    return True


def _load_integration_evidence(
    code_dir: Path,
    state_dir: Path,
    task: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    _, queue_mod, _, handover_mod = _private_modules(code_dir)
    handover_id = task.get("handover_id")
    result_ref = task.get("assurance_result_ref")
    if not isinstance(handover_id, str) or not handover_id:
        raise IntegrationBlocked("integration handover id missing")
    prefix = "control-runtime-state:control/worker-results/"
    if not isinstance(result_ref, str) or not result_ref.startswith(prefix):
        raise IntegrationBlocked("integration assurance result reference is invalid")
    result_name = result_ref[len(prefix):]
    if "/" in result_name or not result_name.endswith(".json"):
        raise IntegrationBlocked("integration assurance result path is invalid")
    result = _load(state_dir / "control" / "worker-results" / result_name)
    handover = _load(state_dir / "control" / "handovers" / f"{handover_id}.json")
    errors = handover_mod.validate(handover)
    if errors:
        raise IntegrationBlocked("authoritative integration handover is invalid")
    candidate_sha = task.get("candidate_sha")
    if handover.get("handover_type") != "ASSURANCE_REQUEST":
        raise IntegrationBlocked("integration handover type is not ASSURANCE_REQUEST")
    if handover.get("repository") != task.get("repository"):
        raise IntegrationBlocked("integration handover repository mismatch")
    if handover.get("candidate_pr") != task.get("candidate_pr"):
        raise IntegrationBlocked("integration handover PR mismatch")
    if handover.get("candidate_sha") != candidate_sha:
        raise IntegrationBlocked("integration handover candidate mismatch")
    if result.get("run_id") != handover_id or result.get("role") != queue_mod.ROLE_B:
        raise IntegrationBlocked("assurance result identity mismatch")
    if result.get("outcome") != "PASS" or result.get("candidate_sha") != candidate_sha:
        raise IntegrationBlocked("authoritative assurance result is not matching PASS")
    return handover, result


def _assert_claim_still_current(code_dir: Path, state_dir: Path, task_id: str, run_id: str) -> dict[str, Any]:
    parallel, queue_mod, _, _ = _private_modules(code_dir)
    queue = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
    task = _find_task(queue, task_id)
    parallel.assert_claim_current(
        queue,
        task_id=task_id,
        role=queue_mod.ROLE_A,
        worker_instance=parallel.INSTANCE_A1,
        run_id=run_id,
        now=datetime.now(timezone.utc),
    )
    return task


def _close_run(runs: dict[str, Any], run_id: str, outcome: str, stamp: str) -> None:
    matches = [item for item in runs.get("runs", []) if item.get("run_id") == run_id]
    if len(matches) != 1:
        raise IntegrationBlocked("integration run record identity mismatch")
    run = matches[0]
    run["outcome"] = outcome
    run["heartbeat_at"] = stamp
    run["finished_at"] = stamp


def _finalize_claim(
    token: str,
    code_dir: Path,
    state_dir: Path,
    *,
    task_id: str,
    run_id: str,
    next_state: str,
    findings: list[str],
    merge_sha: str | None = None,
) -> None:
    parallel, queue_mod, _, _ = _private_modules(code_dir)
    allowed = {"control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"}
    for _ in range(MAX_CAS_ATTEMPTS):
        _reset_state(token, state_dir)
        queue = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
        runs = _load(state_dir / "control" / "DISPATCH_RUNS.json")
        task = _find_task(queue, task_id)
        parallel.assert_claim_current(
            queue,
            task_id=task_id,
            role=queue_mod.ROLE_A,
            worker_instance=parallel.INSTANCE_A1,
            run_id=run_id,
            now=datetime.now(timezone.utc),
        )
        observed = _identity(state_dir)
        completed = parallel.complete_claim_for_instance(
            queue,
            task_id=task_id,
            role=queue_mod.ROLE_A,
            worker_instance=parallel.INSTANCE_A1,
            run_id=run_id,
            next_state=next_state,
            now=datetime.now(timezone.utc),
        )
        updated = _find_task(completed, task_id)
        updated["last_findings"] = list(findings)
        if next_state == "EXECUTION_UNAVAILABLE":
            updated["resume_state"] = "IMPLEMENTATION_QUEUED"
        if merge_sha is not None:
            if not SHA_RE.fullmatch(merge_sha):
                raise IntegrationBlocked("merge SHA is invalid")
            updated["merge_sha"] = merge_sha
        stamp = updated["updated_at"]
        _close_run(runs, run_id, "COMPLETED" if next_state == "COMPLETED_WITHOUT_ASSURANCE" else next_state, stamp)
        _write(state_dir / "control" / "DISPATCH_QUEUE.json", completed)
        _write(state_dir / "control" / "DISPATCH_RUNS.json", runs)
        if _remote_identity(token, state_dir) != observed:
            continue
        if not _persist(
            token,
            state_dir,
            message="runtime: Scheduled Worker A V2 finalize PROJECT_INTEGRATION",
            paths=["control/DISPATCH_QUEUE.json", "control/DISPATCH_RUNS.json"],
            allowed=allowed,
        ):
            continue
        _reset_state(token, state_dir)
        readback = _load(state_dir / "control" / "DISPATCH_QUEUE.json")
        final_task = _find_task(readback, task_id)
        if final_task.get("state") != next_state:
            raise IntegrationBlocked("integration finalization readback state mismatch")
        if any(
            final_task.get(key) is not None
            for key in ("active_run_id", "active_role", "active_worker_instance", "claim_started_at", "claim_expires_at")
        ):
            raise IntegrationBlocked("integration finalization left ghost ownership")
        if merge_sha is not None and final_task.get("merge_sha") != merge_sha:
            raise IntegrationBlocked("integration merge SHA readback mismatch")
        return
    raise IntegrationUnavailable("runtime CAS conflict finalizing integration")


def _perform_expected_head_merge(token: str, repository: str, pr_number: int, candidate_sha: str) -> str:
    repo = _api(token, "GET", f"repos/{repository}")
    if repo.get("allow_merge_commit") is not True:
        raise IntegrationBlocked("repository does not allow exact merge-commit integration")
    response = _api(
        token,
        "PUT",
        f"repos/{repository}/pulls/{pr_number}/merge",
        {"sha": candidate_sha, "merge_method": "merge"},
    )
    merge_sha = response.get("sha")
    if response.get("merged") is not True or not isinstance(merge_sha, str) or not SHA_RE.fullmatch(merge_sha):
        raise IntegrationBlocked("expected-head merge was not accepted")
    return merge_sha


def _validate_merged_state(
    token: str,
    repository: str,
    pr_number: int,
    candidate_sha: str,
    trusted_base_sha: str,
    target_branch: str,
    merge_sha: str,
) -> None:
    post = _pr_snapshot(token, repository, pr_number)
    if post.get("merged") is not True or post.get("head_sha") != candidate_sha:
        raise IntegrationBlocked("post-merge PR identity mismatch")
    if post.get("merge_commit_sha") != merge_sha:
        raise IntegrationBlocked("post-merge commit SHA mismatch")

    commit = _api(token, "GET", f"repos/{repository}/git/commits/{merge_sha}")
    parents = [item.get("sha") for item in commit.get("parents", []) if isinstance(item, dict)]
    if parents != [trusted_base_sha, candidate_sha]:
        raise IntegrationBlocked("merge commit parents do not bind trusted base plus assured head")

    compare = _api(token, "GET", f"repos/{repository}/compare/{merge_sha}...{target_branch}")
    if compare.get("status") not in {"identical", "ahead"}:
        raise IntegrationBlocked("target branch does not contain exact merge commit")


def _detect_completed_merge(
    token: str,
    repository: str | None,
    pr_number: int | None,
    candidate_sha: str | None,
) -> str | None:
    if not isinstance(repository, str) or not isinstance(pr_number, int) or not isinstance(candidate_sha, str):
        return None
    try:
        snapshot = _pr_snapshot(token, repository, pr_number)
    except Exception:
        return None
    merge_sha = snapshot.get("merge_commit_sha")
    if (
        snapshot.get("merged") is True
        and snapshot.get("head_sha") == candidate_sha
        and isinstance(merge_sha, str)
        and SHA_RE.fullmatch(merge_sha)
    ):
        return merge_sha
    return None


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        _status("EXECUTION_UNAVAILABLE_PRIVATE_GITHUB_CREDENTIAL", handled=False)
        return 78

    if os.environ.get("GITHUB_REPOSITORY") != "market-predictions/control-engine" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        _status("FAIL_CLOSED_PUBLIC_EXECUTION_IDENTITY", handled=False)
        return 2

    root = Path(tempfile.mkdtemp(prefix="control-project-integration-", dir=os.environ.get("RUNNER_TEMP")))
    root.chmod(0o700)
    code_dir = root / "code"
    state_dir = root / "state"
    private_tmp = root / "private"
    private_tmp.mkdir(mode=0o700)
    claimed: tuple[str, str] | None = None
    repository: str | None = None
    pr_number: int | None = None
    candidate_sha: str | None = None
    merge_sha: str | None = None

    try:
        _fetch_code(token, code_dir)
        _init_repo(state_dir, f"https://github.com/{CONTROL_REPOSITORY}.git")
        _run(["git", "config", "user.name", "control-scheduled-a-v2[bot]"], cwd=state_dir)
        _run(["git", "config", "user.email", "control-scheduled-a-v2[bot]@users.noreply.github.com"], cwd=state_dir)

        if str(Path.cwd()) not in sys.path:
            sys.path.insert(0, str(Path.cwd()))
        _reconcile_once(token, code_dir, state_dir, private_tmp)
        _reset_state(token, state_dir)
        selected = _select_integration(code_dir, state_dir)
        if selected is None:
            _status("NO_PROJECT_INTEGRATION_SELECTED", handled=False)
            return 0
        task_id = selected["task_id"]

        claim = _claim_selected(token, code_dir, state_dir, task_id)
        if claim is None:
            _status("A1_SELECTION_MOVED", handled=False)
            return 0
        run_id, task = claim
        claimed = (task_id, run_id)

        _reset_state(token, state_dir)
        current_task = _assert_claim_still_current(code_dir, state_dir, task_id, run_id)
        handover, assurance_result = _load_integration_evidence(code_dir, state_dir, current_task)
        repository = current_task.get("repository")
        pr_number = current_task.get("candidate_pr")
        candidate_sha = current_task.get("candidate_sha")
        target_branch = current_task.get("target_branch")
        if not isinstance(repository, str) or repository.count("/") != 1:
            raise IntegrationBlocked("integration repository binding invalid")
        if not isinstance(pr_number, int) or isinstance(pr_number, bool):
            raise IntegrationBlocked("integration PR binding invalid")
        if not isinstance(candidate_sha, str) or not SHA_RE.fullmatch(candidate_sha):
            raise IntegrationBlocked("integration candidate binding invalid")
        if not isinstance(target_branch, str) or not target_branch:
            raise IntegrationBlocked("integration target branch binding invalid")

        trusted_base_sha = _trusted_base_sha(repository, handover)
        snapshot = _pr_snapshot(token, repository, pr_number)
        if snapshot.get("base_ref") != target_branch or snapshot.get("base_sha") != trusted_base_sha:
            raise IntegrationBlocked("live PR base moved from trusted assurance base")
        ci_green = _ci_green(token, repository, candidate_sha, handover)
        _, _, gate_mod, _ = _private_modules(code_dir)
        decision = gate_mod.evaluate_claimed_project_integration(
            current_task,
            assurance_result,
            snapshot,
            exact_head_ci_green=ci_green,
            now=datetime.now(timezone.utc),
        )
        if not decision.allowed:
            raise IntegrationBlocked("claim-backed project integration gate rejected live state")

        # Re-read both canonical claim and live PR/CI immediately before mutation.
        _reset_state(token, state_dir)
        current_task = _assert_claim_still_current(code_dir, state_dir, task_id, run_id)
        snapshot = _pr_snapshot(token, repository, pr_number)
        if snapshot.get("base_ref") != target_branch or snapshot.get("base_sha") != trusted_base_sha:
            raise IntegrationBlocked("live PR base moved before merge")
        if not _ci_green(token, repository, candidate_sha, handover):
            raise IntegrationBlocked("exact-head CI moved from green before merge")
        decision = gate_mod.evaluate_claimed_project_integration(
            current_task,
            assurance_result,
            snapshot,
            exact_head_ci_green=True,
            now=datetime.now(timezone.utc),
        )
        if not decision.allowed:
            raise IntegrationBlocked("final claim-backed integration gate rejected live state")

        merge_sha = _perform_expected_head_merge(token, repository, pr_number, candidate_sha)
        _validate_merged_state(
            token,
            repository,
            pr_number,
            candidate_sha,
            trusted_base_sha,
            target_branch,
            merge_sha,
        )
        _finalize_claim(
            token,
            code_dir,
            state_dir,
            task_id=task_id,
            run_id=run_id,
            next_state="COMPLETED_WITHOUT_ASSURANCE",
            findings=[],
            merge_sha=merge_sha,
        )
        claimed = None
        _status("COMPLETED_ONE_PROJECT_INTEGRATION", handled=True)
        return 0

    except IntegrationUnavailable:
        # A merge API timeout can be ambiguous. Before any lifecycle mutation,
        # independently re-read the PR. If the assured head is already merged,
        # keep the exact A1 claim intact for deterministic recovery/finalization;
        # never resume into a path that could attempt a second merge.
        if merge_sha is None:
            merge_sha = _detect_completed_merge(token, repository, pr_number, candidate_sha)
        if merge_sha is not None:
            _status("EXECUTION_UNAVAILABLE_POST_MERGE_FINALIZATION", handled=True)
            return 78
        if claimed is not None:
            try:
                _finalize_claim(
                    token,
                    code_dir,
                    state_dir,
                    task_id=claimed[0],
                    run_id=claimed[1],
                    next_state="EXECUTION_UNAVAILABLE",
                    findings=["Deterministic project integration execution unavailable; no completed merge could be proven."],
                )
                claimed = None
            except Exception:
                pass
        _status("EXECUTION_UNAVAILABLE_PROJECT_INTEGRATION", handled=True)
        return 78
    except Exception:
        # Once a merge is known to have completed, never rewrite the same task as
        # pre-merge BLOCKED. Preserve claim/history for the canonical missed-
        # finalization recovery path instead of risking a second integration.
        if merge_sha is None:
            merge_sha = _detect_completed_merge(token, repository, pr_number, candidate_sha)
        if merge_sha is not None:
            _status("FAIL_CLOSED_POST_MERGE_VALIDATION_OR_FINALIZATION", handled=True)
            return 2
        if claimed is not None:
            try:
                _finalize_claim(
                    token,
                    code_dir,
                    state_dir,
                    task_id=claimed[0],
                    run_id=claimed[1],
                    next_state="BLOCKED",
                    findings=["Deterministic project integration failed closed before any completed merge could be proven."],
                )
                claimed = None
            except Exception:
                pass
        _status("BLOCKED_PROJECT_INTEGRATION", handled=True)
        return 2
    finally:
        try:
            import shutil
            shutil.rmtree(root)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
