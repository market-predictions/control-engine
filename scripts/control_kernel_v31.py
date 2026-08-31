#!/usr/bin/env python3
"""Control Autonomy V3.1 deterministic runtime writer.

This process is the only public implementation allowed to mutate canonical
Control runtime state. It executes no semantic inference and never executes
private Control code.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_engine import kernel_v31 as core
from control_engine import migration_v31 as migration

CONTROL_REPOSITORY = "market-predictions/control-plane"
RUNTIME_REF = "control-runtime-state"
QUEUE_REL = "control/DISPATCH_QUEUE.json"
RESULT_DIR_REL = "control/worker-results"
GLOBAL_AUTH_REL = "control/CONTROL_RUNTIME_AUTHORITY_V3_1.json"
MISSIONS_REL = "control/missions"
REPO_AUTH_REL = "control/repository-authority"
MAX_CAS_ATTEMPTS = 7
TASK_SEPARATOR = "--"


class BridgeError(RuntimeError):
    pass


class TransientError(BridgeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        raise BridgeError(f"command failed: {cmd[0]}")
    return result


def _auth_header(token: str) -> str:
    raw = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"AUTHORIZATION: basic {raw}"


def _git(token: str, cwd: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", "-c", f"http.https://github.com/.extraheader={_auth_header(token)}", *args], cwd=cwd, check=check)


def _init_repo(path: Path, repository: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], cwd=path)
    _run(["git", "remote", "add", "origin", f"https://github.com/{repository}.git"], cwd=path)


def _fetch_ref(token: str, repo: Path, ref: str) -> None:
    result = _git(token, repo, ["fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{ref}"], check=False)
    if result.returncode != 0:
        raise TransientError(f"cannot fetch {ref}")
    _run(["git", "reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=repo)
    _run(["git", "clean", "-fdq"], cwd=repo)


def _identity(repo: Path, ref: str = "HEAD") -> tuple[str, str]:
    commit = _run(["git", "rev-parse", ref], cwd=repo).stdout.strip()
    blob = _run(["git", "rev-parse", f"{commit}:{QUEUE_REL}"], cwd=repo).stdout.strip()
    return commit, blob


def _remote_identity(token: str, repo: Path) -> tuple[str, str]:
    result = _git(token, repo, ["fetch", "--quiet", "origin", f"refs/heads/{RUNTIME_REF}"], check=False)
    if result.returncode != 0:
        raise TransientError("runtime ref unavailable")
    return _identity(repo, "FETCH_HEAD")


def _changed(repo: Path) -> set[str]:
    tracked = _run(["git", "diff", "--name-only"], cwd=repo).stdout.splitlines()
    untracked = _run(["git", "ls-files", "--others", "--exclude-standard"], cwd=repo).stdout.splitlines()
    return {p for p in tracked + untracked if p}


def _persist_runtime(token: str, repo: Path, observed: tuple[str, str], *, message: str, allowed: set[str]) -> bool:
    if _remote_identity(token, repo) != observed:
        return False
    changed = _changed(repo)
    if not changed:
        return True
    if not changed.issubset(allowed):
        raise BridgeError(f"runtime write scope exceeded: {sorted(changed - allowed)}")
    _run(["git", "config", "user.name", "control-kernel[bot]"], cwd=repo)
    _run(["git", "config", "user.email", "control-kernel[bot]@users.noreply.github.com"], cwd=repo)
    _run(["git", "add", "--", *sorted(changed)], cwd=repo)
    _run(["git", "commit", "--quiet", "-m", message], cwd=repo)
    pushed = _git(token, repo, ["push", "--quiet", "origin", f"HEAD:refs/heads/{RUNTIME_REF}"], check=False)
    return pushed.returncode == 0


def _blob_sha(repo: Path, path: str) -> str:
    return _run(["git", "rev-parse", f"HEAD:{path}"], cwd=repo).stdout.strip()


def _task_identity_component(value: object, *, label: str) -> str:
    try:
        return core._identity_component(value)
    except core.KernelError as exc:
        raise BridgeError(f"{label} is invalid or contains reserved task separator/boundary ambiguity") from exc


def _authority(main: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    global_auth = _load(main / GLOBAL_AUTH_REL)
    if global_auth.get("protocol_id") != "CONTROL_RUNTIME_AUTHORITY_V3_1" or not core._zero(global_auth.get("principal_manual_relay_count")):
        raise BridgeError("global V3.1 authority invalid")
    if global_auth.get("semantic_claim_lease_seconds") != core.LEASE_SECONDS:
        raise BridgeError("lease authority mismatch")
    if not isinstance(global_auth.get("control_runtime_enabled"), bool) or not isinstance(global_auth.get("integration_enabled"), bool):
        raise BridgeError("global V3.1 authority switches must be booleans")

    repo_auth: dict[str, dict[str, Any]] = {}
    for path in sorted((main / REPO_AUTH_REL).glob("*.json")):
        doc = _load(path)
        if doc.get("protocol_id") != "CONTROL_REPOSITORY_AUTHORITY_V3_1" or not core._zero(doc.get("principal_manual_relay_count")):
            raise BridgeError(f"repository authority invalid: {path.name}")
        doc = dict(doc)
        doc["_blob_sha"] = _blob_sha(main, path.relative_to(main).as_posix())
        repo_auth[doc["repository"]] = doc

    missions: list[dict[str, Any]] = []
    roots: set[str] = set()
    for path in sorted((main / MISSIONS_REL).glob("*.mission.json")):
        mission = _load(path)
        if mission.get("protocol_id") != "MISSION_CONTRACT_V3_1" or not core._zero(mission.get("principal_manual_relay_count")):
            raise BridgeError(f"Mission is not V3.1: {path.name}")
        mission_id = _task_identity_component(mission.get("mission_id"), label="Mission identity")
        revision = _task_identity_component(mission.get("mission_revision"), label="Mission revision")
        gaps = mission.get("gaps")
        if not isinstance(gaps, list):
            raise BridgeError(f"Mission gaps are invalid: {path.name}")
        for gap in gaps:
            if not isinstance(gap, dict):
                raise BridgeError(f"Mission gap is invalid: {path.name}")
            gap_id = _task_identity_component(gap.get("gap_id"), label="Mission gap identity")
            root_id = core.deterministic_root_id(mission_id, revision, gap_id)
            if root_id in roots:
                raise BridgeError("duplicate deterministic V3.1 Mission gap identity")
            roots.add(root_id)
            dependencies = gap.get("depends_on", [])
            if not isinstance(dependencies, list):
                raise BridgeError(f"Mission gap dependencies are invalid: {path.name}")
            for dependency in dependencies:
                _task_identity_component(dependency, label="Mission gap dependency")
        repository = mission.get("repository")
        if repository not in repo_auth:
            raise BridgeError(f"Mission repository has no authority record: {repository}")
        missions.append({
            "mission": mission,
            "mission_contract_blob_sha": _blob_sha(main, path.relative_to(main).as_posix()),
            "repository_authority_blob_sha": repo_auth[repository]["_blob_sha"],
        })
    return global_auth, missions, repo_auth


def _active_revisions(missions: list[dict[str, Any]]) -> dict[str, str]:
    return {wrapped["mission"]["mission_id"]: wrapped["mission"]["mission_revision"] for wrapped in missions}


def _active_gap_identities(missions: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {
        (mission["mission_id"], mission["mission_revision"], gap["gap_id"])
        for wrapped in missions
        for mission in [wrapped["mission"]]
        for gap in mission.get("gaps", [])
        if isinstance(gap, dict) and gap.get("gap_state") == "OPEN"
    }


def _active_mission_blobs(missions: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {
        (wrapped["mission"]["mission_id"], wrapped["mission"]["mission_revision"]): wrapped["mission_contract_blob_sha"]
        for wrapped in missions
    }


def _mission_for_task(missions: list[dict[str, Any]], task: dict[str, Any]) -> dict[str, Any] | None:
    for wrapped in missions:
        m = wrapped["mission"]
        if m.get("mission_id") == task.get("mission_id") and m.get("mission_revision") == task.get("mission_revision"):
            return wrapped
    return None


def _assert_live_task_authority(task: dict[str, Any], missions: list[dict[str, Any]], repo_auth: dict[str, dict[str, Any]]) -> None:
    wrapped = _mission_for_task(missions, task)
    if wrapped is None:
        raise BridgeError("task Mission revision is not current")
    mission = wrapped["mission"]
    gap_id = task.get("gap_id")
    gaps = [g for g in mission.get("gaps", []) if g.get("gap_id") == gap_id]
    if len(gaps) != 1 or gaps[0].get("gap_state") != "OPEN":
        raise BridgeError("task gap is retired or missing")
    repository = task.get("repository")
    if repository not in repo_auth:
        raise BridgeError("task repository authority missing")
    if task.get("mission_contract_blob_sha") != wrapped["mission_contract_blob_sha"]:
        raise BridgeError("task frozen Mission authority digest no longer matches active revision")
    if not core._sha(task.get("repository_authority_blob_sha")):
        raise BridgeError("task frozen repository authority digest is invalid")


def _has_live_task_authority(task: dict[str, Any], missions: list[dict[str, Any]], repo_auth: dict[str, dict[str, Any]]) -> bool:
    try:
        _assert_live_task_authority(task, missions, repo_auth)
        return True
    except BridgeError:
        return False


def _require_v31_queue(queue: dict[str, Any]) -> None:
    if queue.get("version") != "3.1":
        raise BridgeError("canonical runtime queue requires one-time V3.1 TICK migration")
    core.validate(queue)
    migration.validate_migration_facts(queue)


def _with_runtime(token: str, mutate, *, message: str):
    with tempfile.TemporaryDirectory(prefix="control-kernel-v31-") as temp:
        root = Path(temp)
        main = root / "main"
        runtime = root / "runtime"
        _init_repo(main, CONTROL_REPOSITORY)
        _init_repo(runtime, CONTROL_REPOSITORY)
        _fetch_ref(token, main, "main")
        global_auth, missions, repo_auth = _authority(main)
        for attempt in range(1, MAX_CAS_ATTEMPTS + 1):
            _fetch_ref(token, runtime, RUNTIME_REF)
            observed = _identity(runtime)
            value, allowed = mutate(runtime, global_auth, missions, repo_auth)
            if _persist_runtime(token, runtime, observed, message=message, allowed=allowed):
                _fetch_ref(token, runtime, RUNTIME_REF)
                return value, _load(runtime / QUEUE_REL), attempt
        raise TransientError("CONTROL_KERNEL_CAS_CONFLICT")


def _api(token: str, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = "https://api.github.com/" + path.lstrip("/")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "control-kernel-v3-1")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code in {429, 500, 502, 503, 504}:
            raise TransientError(f"GitHub transient HTTP {exc.code}") from exc
        raise BridgeError(f"GitHub API HTTP {exc.code} for {path}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TransientError("GitHub API unavailable") from exc


def _branch_sha(token: str, repository: str, branch: str) -> str:
    data = _api(token, "GET", f"repos/{repository}/branches/{urllib.parse.quote(branch, safe='')}")
    sha = data.get("commit", {}).get("sha")
    if not core._sha(sha):
        raise BridgeError("target base branch identity is invalid")
    return sha


def _fast_forward_branch_ref(
    token: str,
    repository: str,
    branch: str,
    *,
    merge_sha: str,
    expected_base_sha: str,
) -> bool:
    """Atomically move a base ref only while the frozen base is still current.

    GitHub rejects a non-fast-forward update if the base moved after planning.
    A rejection while the frozen base is still current is a real authority or
    branch-protection blocker, not a synthetic base-drift signal.
    """
    path = f"repos/{repository}/git/refs/heads/{urllib.parse.quote(branch, safe='')}"
    url = "https://api.github.com/" + path
    body = json.dumps({"sha": merge_sha, "force": False}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "control-kernel-v3-1")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {409, 422}:
            if _branch_sha(token, repository, branch) != expected_base_sha:
                return False
            raise BridgeError("atomic base ref update rejected while frozen base remained current") from exc
        if exc.code in {429, 500, 502, 503, 504}:
            raise TransientError(f"GitHub transient HTTP {exc.code}") from exc
        raise BridgeError("atomic base ref update failed") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TransientError("GitHub API unavailable") from exc
    if payload.get("object", {}).get("sha") != merge_sha:
        raise BridgeError("atomic base ref update returned unexpected identity")
    return True


def _frozen_repository_authority(control_token: str, task: dict[str, Any]) -> dict[str, Any]:
    sha = task.get("repository_authority_blob_sha")
    if not core._sha(sha):
        raise BridgeError("frozen repository authority digest is invalid")
    blob = _api(control_token, "GET", f"repos/{CONTROL_REPOSITORY}/git/blobs/{sha}")
    if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
        raise BridgeError("frozen repository authority blob is unreadable")
    try:
        raw = base64.b64decode(blob["content"].replace("\n", ""), validate=True).decode("utf-8")
        doc = json.loads(raw)
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise BridgeError("frozen repository authority blob is invalid") from exc
    if (
        not isinstance(doc, dict)
        or doc.get("protocol_id") != "CONTROL_REPOSITORY_AUTHORITY_V3_1"
        or doc.get("repository") != task.get("repository")
        or not core._zero(doc.get("principal_manual_relay_count"))
    ):
        raise BridgeError("frozen repository authority identity mismatch")
    return doc


def _frozen_integration_authorized(task: dict[str, Any], frozen_repo: dict[str, Any]) -> bool:
    return (
        task.get("integration_policy") == "AUTO_AFTER_PASS"
        and frozen_repo.get("integration_policy") == "AUTO_AFTER_PASS"
        and frozen_repo.get("integration_enabled") is True
        and frozen_repo.get("control_auto_profile") == "CONTROL_AUTO_V1"
    )


def _integration_authorized(task: dict[str, Any], frozen_repo: dict[str, Any], live_repo: dict[str, Any]) -> bool:
    return (
        _frozen_integration_authorized(task, frozen_repo)
        and live_repo.get("integration_policy") == "AUTO_AFTER_PASS"
        and live_repo.get("integration_enabled") is True
        and live_repo.get("control_auto_profile") == "CONTROL_AUTO_V1"
    )


def _global_integration_enabled(global_auth: dict[str, Any]) -> bool:
    return global_auth.get("control_runtime_enabled") is True and global_auth.get("integration_enabled") is True


def _effective_required_checks(frozen_repo: dict[str, Any], live_repo: dict[str, Any]) -> list[str]:
    frozen = frozen_repo.get("required_check_runs", [])
    live = live_repo.get("required_check_runs", [])
    if not isinstance(frozen, list) or not isinstance(live, list):
        raise BridgeError("repository required checks are invalid")
    if any(not isinstance(item, str) or not item for item in frozen + live):
        raise BridgeError("repository required check identity is invalid")
    return sorted(set(frozen) | set(live))


def _required_checks_green(token: str, repository: str, sha: str, required: list[str]) -> bool:
    if not required:
        return True
    data = _api(token, "GET", f"repos/{repository}/commits/{sha}/check-runs?per_page=100")
    by_name = {item.get("name"): item for item in data.get("check_runs", [])}
    for name in required:
        item = by_name.get(name)
        if not item or item.get("status") != "completed" or item.get("conclusion") not in {"success", "neutral", "skipped"}:
            return False
    return True


def _publish_assurance_status(token: str, repository: str, sha: str) -> None:
    _api(token, "POST", f"repos/{repository}/statuses/{sha}", {
        "state": "success",
        "context": "control/assurance",
        "description": "CONTROL_V3_1_EXACT_CANDIDATE_PASS",
    })


def _integration_candidates(queue: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [
            t for t in queue.get("tasks", [])
            if t.get("lifecycle_model") == core.PROTOCOL_ID
            and t.get("operation") == "ASSURANCE"
            and t.get("status") == core.STATUS_TERMINAL
            and t.get("outcome") == "PASS"
            and t.get("integration_state") == "PENDING"
        ],
        key=lambda t: (t.get("updated_at", ""), t["task_id"]),
    )


def _merged_commit_proves_expected_candidate(
    token: str, repository: str, merge_sha: str, *, expected_base_sha: str, candidate_sha: str
) -> bool:
    if not core._sha(merge_sha) or not core._sha(expected_base_sha) or not core._sha(candidate_sha):
        return False
    commit = _api(token, "GET", f"repos/{repository}/commits/{merge_sha}")
    if commit.get("sha") != merge_sha:
        return False
    parents = commit.get("parents")
    if not isinstance(parents, list) or len(parents) != 2:
        return False
    parent_shas = [parent.get("sha") if isinstance(parent, dict) else None for parent in parents]
    return parent_shas == [expected_base_sha, candidate_sha]


def _plan_integration_target(
    queue: dict[str, Any],
    global_auth: dict[str, Any],
    missions: list[dict[str, Any]],
    repo_auth: dict[str, dict[str, Any]],
    control_token: str,
) -> tuple[str, str]:
    """Return one exact pending task and repository, preferring new authorized work.

    A frozen-AUTO task whose live authority is now HOLD/revoked remains eligible
    only as a recovery fallback, because the external merge may already have
    happened while the runtime write was lost. New merges require both live
    Mission authority and live repository authority.
    """
    if not _global_integration_enabled(global_auth):
        return "", ""
    _require_v31_queue(queue)
    recovery: tuple[str, str] = ("", "")
    for task in _integration_candidates(queue):
        frozen = _frozen_repository_authority(control_token, task)
        if not _frozen_integration_authorized(task, frozen):
            continue
        repository = task["repository"]
        live = repo_auth.get(repository, {})
        if _has_live_task_authority(task, missions, repo_auth) and _integration_authorized(task, frozen, live):
            return task["task_id"], repository
        if not recovery[0]:
            recovery = (task["task_id"], repository)
    return recovery


def _integrate_one(
    queue: dict[str, Any],
    missions: list[dict[str, Any]],
    repo_auth: dict[str, dict[str, Any]],
    control_token: str,
    target_token: str,
    target_task_id: str,
    target_repository: str,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    pending = [t for t in _integration_candidates(queue) if t.get("task_id") == target_task_id]
    if not pending:
        return queue, {"integration": "NONE"}
    if len(pending) != 1:
        raise BridgeError("planned integration task identity is not unique")
    task = pending[0]
    if task.get("repository") != target_repository:
        raise BridgeError("planned integration task repository mismatch")
    live = repo_auth.get(target_repository, {})
    frozen = _frozen_repository_authority(control_token, task)
    candidate = task["candidate"]
    sha = candidate["candidate_sha"]
    pr_number = candidate["candidate_pr_number"]
    pr = _api(target_token, "GET", f"repos/{target_repository}/pulls/{pr_number}")

    if pr.get("head", {}).get("sha") != sha:
        raise BridgeError("live PR no longer matches exact PASS candidate")
    if pr.get("base", {}).get("ref") != candidate["expected_base_branch"]:
        raise BridgeError("live PR base branch mismatch")

    if pr.get("merged") is True:
        if not _frozen_integration_authorized(task, frozen):
            raise BridgeError("already-merged candidate lacks frozen AUTO authority")
        merge_sha = pr.get("merge_commit_sha")
        if not core._sha(merge_sha):
            raise BridgeError("already-merged exact candidate has invalid merge SHA")
        if not _merged_commit_proves_expected_candidate(
            target_token,
            target_repository,
            merge_sha,
            expected_base_sha=candidate["expected_base_sha"],
            candidate_sha=sha,
        ):
            raise BridgeError("already-merged candidate does not prove frozen base and candidate parents")
        q = core.mark_integrated(queue, assurance_task_id=task["task_id"], merge_sha=merge_sha, merged_at=now)
        return q, {"integration": "RECONCILED_MERGED", "task_id": task["task_id"], "merge_sha": merge_sha}

    if pr.get("state") != "open":
        raise BridgeError("live PR is neither open nor merged")

    current_base = _branch_sha(target_token, target_repository, candidate["expected_base_branch"])
    if current_base != candidate["expected_base_sha"] and _merged_commit_proves_expected_candidate(
        target_token,
        target_repository,
        current_base,
        expected_base_sha=candidate["expected_base_sha"],
        candidate_sha=sha,
    ):
        q = core.mark_integrated(queue, assurance_task_id=task["task_id"], merge_sha=current_base, merged_at=now)
        return q, {"integration": "RECONCILED_BASE_REF", "task_id": task["task_id"], "merge_sha": current_base}

    if not _has_live_task_authority(task, missions, repo_auth):
        q = core.mark_integration_hold(queue, assurance_task_id=task["task_id"], held_at=now)
        return q, {"integration": "HOLD_MISSION_AUTHORITY", "task_id": task["task_id"]}
    if not _integration_authorized(task, frozen, live):
        q = core.mark_integration_hold(queue, assurance_task_id=task["task_id"], held_at=now)
        return q, {"integration": "HOLD", "task_id": task["task_id"]}

    if current_base != candidate["expected_base_sha"]:
        q, repair_id = core.materialize_base_drift_repair(queue, assurance_task_id=task["task_id"], now=now)
        return q, {"integration": "BASE_DRIFT", "task_id": task["task_id"], "repair_task_id": repair_id}

    required_checks = _effective_required_checks(frozen, live)
    if not _required_checks_green(target_token, target_repository, sha, required_checks):
        return queue, {"integration": "WAIT_CHECKS", "task_id": task["task_id"]}
    _publish_assurance_status(target_token, target_repository, sha)

    merge_ref = _api(target_token, "GET", f"repos/{target_repository}/git/ref/pull/{pr_number}/merge")
    merge_sha = merge_ref.get("object", {}).get("sha")
    if not core._sha(merge_sha):
        raise BridgeError("synthetic PR merge ref is unavailable")
    if not _merged_commit_proves_expected_candidate(
        target_token,
        target_repository,
        merge_sha,
        expected_base_sha=candidate["expected_base_sha"],
        candidate_sha=sha,
    ):
        raise BridgeError("synthetic merge commit does not prove frozen base and exact candidate")

    if not _fast_forward_branch_ref(
        target_token,
        target_repository,
        candidate["expected_base_branch"],
        merge_sha=merge_sha,
        expected_base_sha=candidate["expected_base_sha"],
    ):
        q, repair_id = core.materialize_base_drift_repair(queue, assurance_task_id=task["task_id"], now=now)
        return q, {"integration": "BASE_DRIFT", "task_id": task["task_id"], "repair_task_id": repair_id}

    if _branch_sha(target_token, target_repository, candidate["expected_base_branch"]) != merge_sha:
        raise BridgeError("atomic integration readback does not prove exact merge commit")

    q = core.mark_integrated(queue, assurance_task_id=task["task_id"], merge_sha=merge_sha, merged_at=now)
    return q, {"integration": "MERGED", "task_id": task["task_id"], "merge_sha": merge_sha}


def command_claim(token: str, *, role: str, worker: str, task_id: str) -> int:
    def mutate(runtime, global_auth, missions, repo_auth):
        if global_auth.get("control_runtime_enabled") is not True:
            raise BridgeError("Control runtime is disabled")
        queue_path = runtime / QUEUE_REL
        q = _load(queue_path)
        _require_v31_queue(q)
        q, _ = core.reconcile(
            q,
            now=_now(),
            active_missions=_active_revisions(missions),
            active_gaps=_active_gap_identities(missions),
            active_mission_blobs=_active_mission_blobs(missions),
        )
        chosen = task_id
        if chosen == "AUTO":
            selected = core.select_task(q, role)
            if selected is None:
                _write(queue_path, q)
                return {"idle": True}, {QUEUE_REL}
            chosen = selected["task_id"]
        task = next((t for t in q.get("tasks", []) if t.get("task_id") == chosen), None)
        if not isinstance(task, dict):
            raise BridgeError("claim target missing")
        _assert_live_task_authority(task, missions, repo_auth)
        q, claimed = core.claim(q, task_id=chosen, worker_instance=worker, authenticated_role=role, now=_now())
        _write(queue_path, q)
        return {"idle": False, "task_id": chosen, "run_id": claimed["claim"]["run_id"]}, {QUEUE_REL}

    captured, readback, attempt = _with_runtime(token, mutate, message=f"runtime: Control V3.1 claim {worker}")
    if captured["idle"]:
        print("CONTROL_KERNEL_CLAIM=NO_ELIGIBLE_WORK")
        return 0
    core.assert_current_claim(readback, task_id=captured["task_id"], run_id=captured["run_id"], worker_instance=worker, authenticated_role=role, now=_now())
    print("CONTROL_KERNEL_CLAIM=START_PROVEN")
    print(f"CONTROL_KERNEL_TASK_ID={captured['task_id']}")
    print(f"CONTROL_KERNEL_RUN_ID={captured['run_id']}")
    print(f"CONTROL_KERNEL_CAS_ATTEMPT={attempt}")
    return 0


def command_release(token: str, *, role: str, worker: str, task_id: str, run_id: str, reason: str) -> int:
    def mutate(runtime, global_auth, missions, repo_auth):
        q = _load(runtime / QUEUE_REL)
        _require_v31_queue(q)
        task = next((t for t in q.get("tasks", []) if t.get("task_id") == task_id), None)
        if not isinstance(task, dict):
            raise BridgeError("release target missing")
        _assert_live_task_authority(task, missions, repo_auth)
        q = core.release(q, task_id=task_id, run_id=run_id, worker_instance=worker, authenticated_role=role, reason=reason, now=_now())
        _write(runtime / QUEUE_REL, q)
        return {"released": task_id}, {QUEUE_REL}

    _, _, attempt = _with_runtime(token, mutate, message=f"runtime: Control V3.1 release {task_id}")
    print("CONTROL_KERNEL_RELEASE=QUEUED")
    print(f"CONTROL_KERNEL_TASK_ID={task_id}")
    print(f"CONTROL_KERNEL_CAS_ATTEMPT={attempt}")
    return 0


def command_record(token: str, *, role: str, worker: str, task_id: str, run_id: str, payload: dict[str, Any]) -> int:
    def mutate(runtime, global_auth, missions, repo_auth):
        if global_auth.get("control_runtime_enabled") is not True:
            raise BridgeError("Control runtime is disabled")
        q = _load(runtime / QUEUE_REL)
        _require_v31_queue(q)
        task = next((t for t in q.get("tasks", []) if t.get("task_id") == task_id), None)
        if not isinstance(task, dict):
            raise BridgeError("record target missing")
        _assert_live_task_authority(task, missions, repo_auth)
        ref = f"{RESULT_DIR_REL}/{task_id}--{run_id}.json"
        result_path = runtime / ref
        if result_path.exists():
            existing = _load(result_path)
            if core.result_fingerprint(existing.get("semantic_result", {})) == core.result_fingerprint(payload):
                return {"idempotent": True, "result_ref": ref}, set()
            raise BridgeError("conflicting canonical result already exists")
        q, successor = core.record(q, task_id=task_id, run_id=run_id, worker_instance=worker, authenticated_role=role, result=payload, result_ref=ref, now=_now())
        canonical = {
            "protocol_id": "CONTROL_WORKER_RESULT_V3_1",
            "task_id": task_id,
            "run_id": run_id,
            "role": role,
            "worker_instance": worker,
            "semantic_result": payload,
            "semantic_result_sha256": core.result_fingerprint(payload),
            "recorded_at": _now().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "principal_manual_relay_count": 0,
        }
        _write(result_path, canonical)
        _write(runtime / QUEUE_REL, q)
        return {"idempotent": False, "result_ref": ref, "successor": successor}, {QUEUE_REL, ref}

    captured, readback, attempt = _with_runtime(token, mutate, message=f"runtime: atomic Control V3.1 RECORD {task_id}")
    terminal = next((t for t in readback.get("tasks", []) if t.get("task_id") == task_id), None)
    if not captured.get("idempotent") and (not terminal or terminal.get("status") != core.STATUS_TERMINAL):
        raise BridgeError("atomic RECORD readback not terminal")
    print("CONTROL_KERNEL_RECORD=IDEMPOTENT" if captured.get("idempotent") else "CONTROL_KERNEL_RECORD=TERMINAL")
    print(f"CONTROL_KERNEL_RESULT_REF={captured['result_ref']}")
    print(f"CONTROL_KERNEL_SUCCESSOR={captured.get('successor') or ''}")
    print(f"CONTROL_KERNEL_CAS_ATTEMPT={attempt}")
    return 0


def command_plan_tick(token: str) -> int:
    with tempfile.TemporaryDirectory(prefix="control-kernel-plan-") as temp:
        root = Path(temp)
        main = root / "main"
        runtime = root / "runtime"
        _init_repo(main, CONTROL_REPOSITORY)
        _init_repo(runtime, CONTROL_REPOSITORY)
        _fetch_ref(token, main, "main")
        global_auth, missions, repo_auth = _authority(main)
        _fetch_ref(token, runtime, RUNTIME_REF)
        q = _load(runtime / QUEUE_REL)
        target_task_id, target_repository = ("", "")
        if q.get("version") == "3.1":
            target_task_id, target_repository = _plan_integration_target(q, global_auth, missions, repo_auth, token)
        print(f"CONTROL_KERNEL_TARGET_TASK_ID={target_task_id}")
        print(f"CONTROL_KERNEL_TARGET_REPOSITORY={target_repository}")
    return 0


def command_tick(token: str, *, target_token: str, target_task_id: str, target_repository: str) -> int:
    def mutate(runtime, global_auth, missions, repo_auth):
        queue_path = runtime / QUEUE_REL
        q = _load(queue_path)
        now = _now()
        source_version = q.get("version")
        q, imported_facts = migration.migrate(q, missions=missions, now=now)
        migration_report = {
            "performed": source_version != "3.1",
            "from_version": source_version,
            "to_version": "3.1",
            "imported_fact_count": len(imported_facts),
        }
        q, reconcile_report = core.reconcile(
            q,
            now=now,
            active_missions=_active_revisions(missions),
            active_gaps=_active_gap_identities(missions),
            active_mission_blobs=_active_mission_blobs(missions),
        )
        integration_report: dict[str, Any] = {"integration": "DISABLED"}
        if _global_integration_enabled(global_auth) and target_repository:
            if not target_token or not target_task_id:
                raise BridgeError("exact target capability required for enabled integration")
            q, integration_report = _integrate_one(
                q,
                missions,
                repo_auth,
                token,
                target_token,
                target_task_id,
                target_repository,
                now,
            )
        created: list[str] = []
        if global_auth.get("control_runtime_enabled") is True:
            q, created = migration.feed(q, missions=missions, now=now)
        _write(queue_path, q)
        return {
            "migration": migration_report,
            "reconcile": reconcile_report,
            "integration": integration_report,
            "feed": created,
        }, {QUEUE_REL}

    captured, _, attempt = _with_runtime(token, mutate, message="runtime: Control V3.1 TICK")
    print("CONTROL_KERNEL_TICK=SUCCESS")
    print(f"CONTROL_KERNEL_MIGRATION={json.dumps(captured['migration'], separators=(',', ':'))}")
    print(f"CONTROL_KERNEL_RECONCILE={json.dumps(captured['reconcile'], separators=(',', ':'))}")
    print(f"CONTROL_KERNEL_INTEGRATION={json.dumps(captured['integration'], separators=(',', ':'))}")
    print(f"CONTROL_KERNEL_FEED={json.dumps(captured['feed'], separators=(',', ':'))}")
    print(f"CONTROL_KERNEL_CAS_ATTEMPT={attempt}")
    return 0


def _payload_from_env() -> dict[str, Any]:
    raw = os.environ.get("CONTROL_RESULT_PAYLOAD", "")
    if not raw:
        raise BridgeError("CONTROL_RESULT_PAYLOAD is required")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError("CONTROL_RESULT_PAYLOAD is invalid JSON") from exc
    if not isinstance(value, dict):
        raise BridgeError("CONTROL_RESULT_PAYLOAD must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Autonomy V3.1 deterministic runtime writer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tick")
    sub.add_parser("plan-tick")
    claim = sub.add_parser("claim")
    claim.add_argument("--role", choices=[core.ROLE_A, core.ROLE_B], required=True)
    claim.add_argument("--worker", choices=[core.INSTANCE_A1, core.INSTANCE_B1], required=True)
    claim.add_argument("--task-id", default="AUTO")
    record = sub.add_parser("record")
    record.add_argument("--role", choices=[core.ROLE_A, core.ROLE_B], required=True)
    record.add_argument("--worker", choices=[core.INSTANCE_A1, core.INSTANCE_B1], required=True)
    record.add_argument("--task-id", required=True)
    record.add_argument("--run-id", required=True)
    release = sub.add_parser("release")
    release.add_argument("--role", choices=[core.ROLE_A, core.ROLE_B], required=True)
    release.add_argument("--worker", choices=[core.INSTANCE_A1, core.INSTANCE_B1], required=True)
    release.add_argument("--task-id", required=True)
    release.add_argument("--run-id", required=True)
    release.add_argument("--reason", choices=["EXECUTION_UNAVAILABLE", "EXECUTION_ABORTED"], required=True)
    return parser


def main() -> int:
    token = os.environ.get("CONTROL_RUNTIME_TOKEN", "")
    if not token:
        print("CONTROL_KERNEL=NO_RUNTIME_TOKEN")
        return 78
    args = build_parser().parse_args()
    try:
        if args.command == "plan-tick":
            return command_plan_tick(token)
        if args.command == "tick":
            return command_tick(
                token,
                target_token=os.environ.get("CONTROL_TARGET_TOKEN", ""),
                target_task_id=os.environ.get("CONTROL_TARGET_TASK_ID", ""),
                target_repository=os.environ.get("CONTROL_TARGET_REPOSITORY", ""),
            )
        if args.command == "claim":
            return command_claim(token, role=args.role, worker=args.worker, task_id=args.task_id)
        if args.command == "record":
            return command_record(token, role=args.role, worker=args.worker, task_id=args.task_id, run_id=args.run_id, payload=_payload_from_env())
        if args.command == "release":
            return command_release(token, role=args.role, worker=args.worker, task_id=args.task_id, run_id=args.run_id, reason=args.reason)
        raise BridgeError("unsupported command")
    except Exception as exc:
        print(f"CONTROL_KERNEL=FAILED:{type(exc).__name__}:{str(exc)[-800:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
