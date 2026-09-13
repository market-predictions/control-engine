from __future__ import annotations

"""Bounded owner-approved Control V4 runtime administration.

This is an outside-Runner governance path for two concrete actions only:

- finalize one exact READY/PASS task after its exact target PR was owner-approved
  and is already merged into the target base branch;
- activate one exact existing public candidate for the single unmaterialized,
  dependency-free OPEN Mission gap of its repository.

It never grants standing integration authority, never changes private main, and
never creates a second queue/state plane. Every queue mutation uses the same
private-main no-op + runtime-ref atomic GraphQL ``updateRefs`` CAS fence as the
normal V4 carrier.
"""

import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from control_engine.v4_authority_io import V4AuthorityBundle, assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import (
    V4ValidationError,
    v4_root_task_id,
    validate_authority_set,
    validate_queue_v4,
)
from control_engine.v4_runtime_protocol import strict_json_object


PREFIX = "CONTROL_V4_OWNER_ADMIN "
PRIVATE_REPOSITORY = "market-predictions/control-plane"
RUNTIME_BRANCH = "control-runtime-state"
QUEUE_PATH = "control/DISPATCH_QUEUE.json"
MISSION_DIR = "control/missions"
AUTHORITY_DIR = "control/repository-authority"
API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
OPERATIONS = {"FINALIZE_INTEGRATED", "ACTIVATE_ROOT_CANDIDATE"}
COMMAND_KEYS = {
    "operation",
    "repository",
    "candidate_pr_number",
    "candidate_sha",
    "candidate_head_branch",
    "expected_base_branch",
    "expected_base_sha",
}


class OwnerAdminError(RuntimeError):
    pass


class StaleWriteError(OwnerAdminError):
    pass


def _sha(value: object) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise OwnerAdminError("SHA identity invalid")
    return value


def _repository(value: object) -> str:
    if not isinstance(value, str) or REPOSITORY_RE.fullmatch(value) is None:
        raise OwnerAdminError("repository identity invalid")
    return value


def _branch(value: object) -> str:
    if not isinstance(value, str) or BRANCH_RE.fullmatch(value) is None or ".." in value:
        raise OwnerAdminError("branch identity invalid")
    return value


def parse_owner_admin_command(raw: str) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.startswith(PREFIX):
        raise OwnerAdminError("owner-admin command prefix invalid")
    try:
        payload = strict_json_object(raw[len(PREFIX):])
    except Exception as exc:
        raise OwnerAdminError("owner-admin JSON invalid") from exc
    if set(payload) != COMMAND_KEYS:
        raise OwnerAdminError("owner-admin command fields invalid")
    if payload.get("operation") not in OPERATIONS:
        raise OwnerAdminError("owner-admin operation unsupported")
    payload["repository"] = _repository(payload["repository"])
    number = payload["candidate_pr_number"]
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise OwnerAdminError("candidate PR number invalid")
    payload["candidate_sha"] = _sha(payload["candidate_sha"])
    payload["candidate_head_branch"] = _branch(payload["candidate_head_branch"])
    payload["expected_base_branch"] = _branch(payload["expected_base_branch"])
    payload["expected_base_sha"] = _sha(payload["expected_base_sha"])
    return payload


def candidate_identity(command: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_sha": command["candidate_sha"],
        "candidate_pr_number": command["candidate_pr_number"],
        "candidate_head_branch": command["candidate_head_branch"],
        "expected_base_branch": command["expected_base_branch"],
        "expected_base_sha": command["expected_base_sha"],
    }


def _ts(now: datetime) -> str:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise OwnerAdminError("current time must be timezone-aware")
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_public_target(command: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    exact = candidate_identity(command)
    if target.get("repository") != command["repository"]:
        raise OwnerAdminError("target repository drifted")
    if target.get("head_sha") != exact["candidate_sha"] or target.get("head_branch") != exact["candidate_head_branch"]:
        raise OwnerAdminError("target candidate head drifted")
    if target.get("base_branch") != exact["expected_base_branch"]:
        raise OwnerAdminError("target candidate base branch drifted")

    operation = command["operation"]
    if operation == "ACTIVATE_ROOT_CANDIDATE":
        if target.get("base_sha") != exact["expected_base_sha"]:
            raise OwnerAdminError("target candidate base drifted")
        if target.get("state") != "open" or target.get("merged") is not False:
            raise OwnerAdminError("activation candidate is not open/unmerged")
        if target.get("mergeable") is not True:
            raise OwnerAdminError("activation candidate is not currently mergeable")
        if target.get("current_base_sha") != exact["expected_base_sha"]:
            raise OwnerAdminError("activation base branch moved")
        return

    if operation == "FINALIZE_INTEGRATED":
        if target.get("state") != "closed" or target.get("merged") is not True:
            raise OwnerAdminError("finalization target is not merged")
        if target.get("candidate_in_current_base") is not True:
            raise OwnerAdminError("merged candidate is not contained in current base")
        if target.get("current_base_sha") == exact["expected_base_sha"]:
            raise OwnerAdminError("target base did not advance after integration")
        return

    raise OwnerAdminError("owner-admin operation unsupported")


def _task_candidate_matches(task: Mapping[str, Any], command: Mapping[str, Any]) -> bool:
    return task.get("repository") == command["repository"] and task.get("candidate") == candidate_identity(command)


def _task_public_pr_matches(task: Mapping[str, Any], command: Mapping[str, Any]) -> bool:
    candidate = task.get("candidate")
    return (
        task.get("repository") == command["repository"]
        and isinstance(candidate, Mapping)
        and candidate.get("candidate_pr_number") == command["candidate_pr_number"]
    )


def finalize_integrated_v4(
    queue: Mapping[str, Any],
    bundle: V4AuthorityBundle,
    command: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, bundle)
    if queue.get("execution_lock") is not None:
        raise OwnerAdminError("owner-admin mutation requires no execution lock")

    matches = [task for task in queue["tasks"] if _task_candidate_matches(task, command)]
    if len(matches) != 1:
        raise OwnerAdminError("READY task does not resolve exactly")
    source = matches[0]
    if source.get("status") != "READY" or source.get("phase") is not None:
        raise OwnerAdminError("finalization requires exact READY task")

    result = deepcopy(queue)
    task = next(item for item in result["tasks"] if item["task_id"] == source["task_id"])
    task["status"] = "DONE"
    task["phase"] = None
    task["blocker"] = None
    task["updated_at"] = _ts(now)
    validate_queue_v4(result)
    assert_v4_queue_bound_to_authority(result, bundle)
    return result


def _dependency_free_unmaterialized_gap(
    queue: Mapping[str, Any],
    bundle: V4AuthorityBundle,
    repository: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    missions = [mission for mission in bundle.missions if mission.get("repository") == repository]
    if len(missions) != 1:
        raise OwnerAdminError("repository does not resolve to exactly one current Mission")
    mission = missions[0]
    existing = {
        (task["mission_id"], task["mission_revision"], task["gap_id"])
        for task in queue["tasks"]
    }
    candidates = []
    for gap in mission["gaps"]:
        logical = (mission["mission_id"], mission["mission_revision"], gap["gap_id"])
        if (
            gap.get("gap_state") == "OPEN"
            and gap.get("depends_on") == []
            and logical not in existing
        ):
            candidates.append(gap)
    if len(candidates) != 1:
        raise OwnerAdminError("owner activation requires exactly one dependency-free unmaterialized OPEN gap")
    return mission, candidates[0]


def activate_root_candidate_v4(
    queue: Mapping[str, Any],
    bundle: V4AuthorityBundle,
    command: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, bundle)
    if queue.get("execution_lock") is not None:
        raise OwnerAdminError("owner-admin mutation requires no execution lock")
    if any(_task_public_pr_matches(task, command) for task in queue["tasks"]):
        raise OwnerAdminError("candidate PR is already materialized")

    mission, gap = _dependency_free_unmaterialized_gap(queue, bundle, command["repository"])
    repo_key = command["repository"].lower()
    created = _ts(now)
    task = {
        "task_id": v4_root_task_id(mission["mission_id"], mission["mission_revision"], gap["gap_id"]),
        "mission_id": mission["mission_id"],
        "mission_revision": mission["mission_revision"],
        "mission_contract_blob_sha": bundle.mission_blob_shas[mission["mission_id"]],
        "repository_authority_blob_sha": bundle.authority_blob_shas[repo_key],
        "gap_id": gap["gap_id"],
        "repository": gap["repository"],
        "acceptance": list(gap["acceptance"]),
        "integration_policy": gap["integration_policy"],
        "review_policy": gap["review_policy"],
        "convergence_required": bool(gap.get("convergence_required", False)),
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": candidate_identity(command),
        "last_review": None,
        "external_review": None,
        "blocker": None,
        "created_at": created,
        "updated_at": created,
    }
    result = deepcopy(queue)
    result["tasks"].append(task)
    validate_queue_v4(result)
    assert_v4_queue_bound_to_authority(result, bundle)
    return result


def plan_owner_admin_transition(
    queue: Mapping[str, Any],
    bundle: V4AuthorityBundle,
    command: Mapping[str, Any],
    target: Mapping[str, Any],
    *,
    now: datetime,
) -> dict[str, Any]:
    validate_public_target(command, target)
    if command["operation"] == "FINALIZE_INTEGRATED":
        return finalize_integrated_v4(queue, bundle, command, now=now)
    if command["operation"] == "ACTIVATE_ROOT_CANDIDATE":
        return activate_root_candidate_v4(queue, bundle, command, now=now)
    raise OwnerAdminError("owner-admin operation unsupported")


def _request_json(
    url: str,
    *,
    headers: Mapping[str, str],
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={**headers, **({"Content-Type": "application/json"} if data is not None else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OwnerAdminError("GitHub transport failed") from exc


def _private_headers() -> dict[str, str]:
    token = os.environ.get("CONTROL_PLANE_TOKEN", "")
    if not token:
        raise OwnerAdminError("private capability unavailable")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "control-v4-owner-admin",
    }


def _public_headers() -> dict[str, str]:
    token = os.environ.get("CONTROL_ENGINE_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "control-v4-owner-admin-public-read",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _private_get(path: str) -> Any:
    return _request_json(f"{API}/{path}", headers=_private_headers())


def _private_post(path: str, payload: Mapping[str, Any]) -> Any:
    return _request_json(f"{API}/{path}", headers=_private_headers(), method="POST", payload=payload)


def _public_get(path: str) -> Any:
    return _request_json(f"{API}/{path}", headers=_public_headers())


def _branch_head(repository: str, branch: str, *, private: bool) -> str:
    encoded = urllib.parse.quote(branch, safe="")
    value = _private_get(f"repos/{repository}/branches/{encoded}") if private else _public_get(f"repos/{repository}/branches/{encoded}")
    sha = ((value.get("commit") or {}).get("sha")) if isinstance(value, Mapping) else None
    return _sha(sha)


def _decode_content(document: Mapping[str, Any]) -> tuple[str, str]:
    if document.get("type") != "file" or document.get("encoding") != "base64":
        raise OwnerAdminError("private content response invalid")
    sha = _sha(document.get("sha"))
    content = document.get("content")
    if not isinstance(content, str):
        raise OwnerAdminError("private content unavailable")
    try:
        text = base64.b64decode(content, validate=False).decode("utf-8", "strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise OwnerAdminError("private content encoding invalid") from exc
    return text, sha


def _private_file(path: str, ref: str) -> tuple[str, str]:
    quoted_path = urllib.parse.quote(path, safe="/")
    quoted_ref = urllib.parse.quote(ref, safe="")
    value = _private_get(f"repos/{PRIVATE_REPOSITORY}/contents/{quoted_path}?ref={quoted_ref}")
    if not isinstance(value, Mapping):
        raise OwnerAdminError("private content response invalid")
    return _decode_content(value)


def _private_json(path: str, ref: str) -> tuple[dict[str, Any], str]:
    text, sha = _private_file(path, ref)
    try:
        return strict_json_object(text), sha
    except Exception as exc:
        raise OwnerAdminError("private JSON invalid") from exc


def _load_bundle(main_sha: str) -> V4AuthorityBundle:
    missions_listing = _private_get(f"repos/{PRIVATE_REPOSITORY}/contents/{MISSION_DIR}?ref={main_sha}")
    authorities_listing = _private_get(f"repos/{PRIVATE_REPOSITORY}/contents/{AUTHORITY_DIR}?ref={main_sha}")
    if not isinstance(missions_listing, list) or not isinstance(authorities_listing, list):
        raise OwnerAdminError("private authority registry unavailable")

    mission_paths = sorted(
        item["path"] for item in missions_listing
        if isinstance(item, Mapping) and item.get("type") == "file" and isinstance(item.get("path"), str)
        and item["path"].startswith(f"{MISSION_DIR}/") and item["path"].endswith(".mission.json")
        and "/" not in item["path"][len(MISSION_DIR) + 1:]
    )
    authority_paths = sorted(
        item["path"] for item in authorities_listing
        if isinstance(item, Mapping) and item.get("type") == "file" and isinstance(item.get("path"), str)
        and item["path"].startswith(f"{AUTHORITY_DIR}/") and item["path"].endswith(".json")
        and "/" not in item["path"][len(AUTHORITY_DIR) + 1:]
    )
    missions: list[dict[str, Any]] = []
    authorities: list[dict[str, Any]] = []
    mission_shas: dict[str, str] = {}
    authority_shas: dict[str, str] = {}
    for path in mission_paths:
        mission, blob = _private_json(path, main_sha)
        mission_id = mission.get("mission_id")
        if not isinstance(mission_id, str) or mission_id in mission_shas:
            raise OwnerAdminError("private Mission identity invalid")
        mission_shas[mission_id] = blob
        missions.append(mission)
    for path in authority_paths:
        authority, blob = _private_json(path, main_sha)
        repository = authority.get("repository")
        if not isinstance(repository, str) or repository.lower() in authority_shas:
            raise OwnerAdminError("private repository authority invalid")
        authority_shas[repository.lower()] = blob
        authorities.append(authority)
    validate_authority_set(missions, authorities)
    return V4AuthorityBundle(tuple(missions), tuple(authorities), mission_shas, authority_shas)


def _load_private_state() -> dict[str, Any]:
    repository = _private_get(f"repos/{PRIVATE_REPOSITORY}")
    node_id = repository.get("node_id") if isinstance(repository, Mapping) else None
    if not isinstance(repository, Mapping) or repository.get("full_name") != PRIVATE_REPOSITORY or repository.get("private") is not True or not isinstance(node_id, str) or not node_id:
        raise OwnerAdminError("private repository identity invalid")
    main_sha = _branch_head(PRIVATE_REPOSITORY, "main", private=True)
    runtime_sha = _branch_head(PRIVATE_REPOSITORY, RUNTIME_BRANCH, private=True)
    bundle = _load_bundle(main_sha)
    queue, queue_blob = _private_json(QUEUE_PATH, runtime_sha)
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, bundle)
    return {
        "repository_node_id": node_id,
        "main_sha": main_sha,
        "runtime_sha": runtime_sha,
        "queue_blob": queue_blob,
        "queue": queue,
        "bundle": bundle,
    }


def _public_target(command: Mapping[str, Any]) -> dict[str, Any]:
    repository = command["repository"]
    repo = _public_get(f"repos/{repository}")
    if not isinstance(repo, Mapping) or repo.get("full_name") != repository or repo.get("private") is not False:
        raise OwnerAdminError("target repository must be public and exact")
    pr = _public_get(f"repos/{repository}/pulls/{command['candidate_pr_number']}")
    if not isinstance(pr, Mapping):
        raise OwnerAdminError("target PR unavailable")
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    current_base_sha = _branch_head(repository, command["expected_base_branch"], private=False)
    merged = pr.get("merged_at") is not None
    candidate_in_current_base = False
    if command["operation"] == "FINALIZE_INTEGRATED":
        comparison = _public_get(
            f"repos/{repository}/compare/{command['candidate_sha']}...{current_base_sha}"
        )
        merge_base = ((comparison.get("merge_base_commit") or {}).get("sha")) if isinstance(comparison, Mapping) else None
        candidate_in_current_base = (
            merge_base == command["candidate_sha"]
            and comparison.get("status") in {"ahead", "identical"}
            and comparison.get("behind_by") == 0
        )
    return {
        "repository": repository,
        "state": pr.get("state"),
        "merged": merged,
        "mergeable": pr.get("mergeable"),
        "head_sha": head.get("sha"),
        "head_branch": head.get("ref"),
        "base_branch": base.get("ref"),
        "base_sha": base.get("sha"),
        "current_base_sha": current_base_sha,
        "candidate_in_current_base": candidate_in_current_base,
    }


def _write_queue_exact(
    state: Mapping[str, Any],
    queue: Mapping[str, Any],
    command: Mapping[str, Any],
) -> str:
    operation = command["operation"]
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, state["bundle"])
    if _branch_head(PRIVATE_REPOSITORY, "main", private=True) != state["main_sha"]:
        raise StaleWriteError("private main moved before owner-admin write")
    if _branch_head(PRIVATE_REPOSITORY, RUNTIME_BRANCH, private=True) != state["runtime_sha"]:
        raise StaleWriteError("private runtime ref moved before owner-admin write")

    text = json.dumps(queue, separators=(",", ":"), ensure_ascii=False)
    blob = _private_post(
        f"repos/{PRIVATE_REPOSITORY}/git/blobs",
        {"content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "encoding": "base64"},
    )
    new_blob = _sha(blob.get("sha") if isinstance(blob, Mapping) else None)
    parent = _private_get(f"repos/{PRIVATE_REPOSITORY}/git/commits/{state['runtime_sha']}")
    parent_tree = ((parent.get("tree") or {}).get("sha")) if isinstance(parent, Mapping) else None
    parent_tree = _sha(parent_tree)
    tree = _private_post(
        f"repos/{PRIVATE_REPOSITORY}/git/trees",
        {"base_tree": parent_tree, "tree": [{"path": QUEUE_PATH, "mode": "100644", "type": "blob", "sha": new_blob}]},
    )
    new_tree = _sha(tree.get("sha") if isinstance(tree, Mapping) else None)
    commit = _private_post(
        f"repos/{PRIVATE_REPOSITORY}/git/commits",
        {
            "message": f"Control V4 owner admin: {operation}",
            "tree": new_tree,
            "parents": [state["runtime_sha"]],
        },
    )
    new_commit = _sha(commit.get("sha") if isinstance(commit, Mapping) else None)

    # Public target facts cannot participate in the private-repository CAS. Re-read
    # them after commit preparation and validate them as close as possible to the
    # atomic private authority/runtime ref update.
    validate_public_target(command, _public_target(command))

    mutation = """
    mutation UpdateRefs($input: UpdateRefsInput!) {
      updateRefs(input: $input) { clientMutationId }
    }
    """
    payload = {
        "query": mutation,
        "variables": {
            "input": {
                "repositoryId": state["repository_node_id"],
                "clientMutationId": f"control-v4-owner-admin-{os.environ.get('GITHUB_RUN_ID', 'unknown')}-{operation.lower()}",
                "refUpdates": [
                    {"name": "refs/heads/main", "beforeOid": state["main_sha"], "afterOid": state["main_sha"], "force": False},
                    {"name": f"refs/heads/{RUNTIME_BRANCH}", "beforeOid": state["runtime_sha"], "afterOid": new_commit, "force": False},
                ],
            }
        },
    }
    result = _request_json(GRAPHQL, headers={**_private_headers(), "Content-Type": "application/json"}, method="POST", payload=payload)
    if not isinstance(result, Mapping) or result.get("errors") or not isinstance((result.get("data") or {}).get("updateRefs"), Mapping):
        raise StaleWriteError("owner-admin atomic updateRefs rejected")
    return new_commit


def main() -> int:
    try:
        command = parse_owner_admin_command(os.environ.get("CONTROL_V4_OWNER_COMMAND", ""))
        state = _load_private_state()
        target = _public_target(command)
        next_queue = plan_owner_admin_transition(
            state["queue"],
            state["bundle"],
            command,
            target,
            now=datetime.now(timezone.utc),
        )
        runtime_commit = _write_queue_exact(state, next_queue, command)
        print(f"CONTROL_V4_OWNER_ADMIN={command['operation']}:PASS")
        print(f"TARGET={command['repository']}#{command['candidate_pr_number']}@{command['candidate_sha']}")
        print(f"RUNTIME_COMMIT={runtime_commit}")
        return 0
    except (OwnerAdminError, V4ValidationError) as exc:
        print(f"CONTROL_V4_OWNER_ADMIN=REJECTED:{type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
