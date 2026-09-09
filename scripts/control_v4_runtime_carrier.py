from __future__ import annotations

"""Trusted GitHub I/O carrier for Control V4 Scheduled runtime commands.

The public issue comment is transport only. Private control-plane remains the sole
Mission/authority/runtime-state plane. This executable accepts only the bounded
protocol implemented by ``control_engine.v4_runtime_protocol`` and mutates only
``control-runtime-state:control/DISPATCH_QUEUE.json`` by exact old-ref CAS.
"""

import base64
from datetime import datetime, timezone
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from control_engine.v4_authority_io import V4AuthorityBundle, assert_v4_queue_bound_to_authority
from control_engine.v4_contracts import V4ValidationError, acquire_task_v4, validate_authority_set, validate_queue_v4
from control_engine.v4_runtime_protocol import (
    RESULT_PROTOCOL_ID,
    RuntimeProtocolError,
    StaleEventError,
    assert_event_identity,
    bind_public_event_to_holder,
    block_holder_v4,
    candidate_ready_v4,
    compact_public_result,
    external_finding_v4,
    external_pass_v4,
    external_requested_v4,
    external_unavailable_v4,
    internal_review_v4,
    parse_public_command,
    reconcile_review_candidate_drift_v4,
    recover_expired_lock_v4,
    safe_work_capsule,
    select_task_id_v4,
    strict_json_object,
    task_token,
    validate_runtime_binding,
    yield_holder_v4,
)


PRIVATE_REPOSITORY = "market-predictions/control-plane"
PUBLIC_COMMAND_REPOSITORY = "market-predictions/control-engine"
PUBLIC_COMMAND_ISSUE = 106
PUBLIC_COMMAND_ACTOR = "market-predictions"
TICK_MAX_AGE_SECONDS = 120
RUNTIME_BRANCH = "control-runtime-state"
QUEUE_PATH = "control/DISPATCH_QUEUE.json"
AUTHORITY_PATH = "control/CONTROL_RUNTIME_AUTHORITY_V4.json"
RUNNER_CONFIG_PATH = "control/CONTROL_RUNNER_V4.json"
PROMPT_PATH = "control/CONTROL_RUNNER_V4_PROMPT.md"
MISSION_DIR = "control/missions"
REPOSITORY_AUTHORITY_DIR = "control/repository-authority"
API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"


class CarrierError(RuntimeError):
    pass


class StaleWriteError(CarrierError):
    pass


def _private_headers() -> dict[str, str]:
    token = os.environ.get("CONTROL_PLANE_TOKEN", "")
    if not token:
        raise CarrierError("private capability unavailable")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "control-v4-runtime-carrier",
    }


def _public_command_headers() -> dict[str, str]:
    token = os.environ.get("CONTROL_ENGINE_TOKEN", "")
    if not token:
        raise CarrierError("public command read capability unavailable")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "control-v4-runtime-command-correlation",
    }


def _request_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    allow_404: bool = False,
) -> Any:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={**(headers or {}), **({"Content-Type": "application/json"} if data is not None else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        raise CarrierError(f"GitHub transport failed with HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CarrierError("GitHub transport/read failed") from exc


def _private_get(path: str, *, allow_404: bool = False) -> Any:
    return _request_json(f"{API}/{path}", headers=_private_headers(), allow_404=allow_404)


def _private_post(path: str, payload: Mapping[str, Any]) -> Any:
    return _request_json(f"{API}/{path}", headers=_private_headers(), method="POST", payload=payload)


def _public_get(path: str, *, allow_404: bool = False) -> Any:
    return _request_json(
        f"{API}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "control-v4-runtime-carrier-public-read",
        },
        allow_404=allow_404,
    )


def _decode_content(document: Mapping[str, Any]) -> tuple[str, str]:
    if document.get("type") != "file" or document.get("encoding") != "base64":
        raise CarrierError("private content response invalid")
    sha = document.get("sha")
    content = document.get("content")
    if not isinstance(sha, str) or len(sha) != 40 or not isinstance(content, str):
        raise CarrierError("private content identity invalid")
    try:
        text = base64.b64decode(content, validate=False).decode("utf-8", "strict")
    except (ValueError, UnicodeDecodeError) as exc:
        raise CarrierError("private content encoding invalid") from exc
    return text, sha


def _contents(path: str, ref: str) -> Mapping[str, Any]:
    quoted = urllib.parse.quote(path, safe="/")
    result = _private_get(
        f"repos/{PRIVATE_REPOSITORY}/contents/{quoted}?ref={urllib.parse.quote(ref, safe='')}"
    )
    if not isinstance(result, Mapping):
        raise CarrierError("private content response invalid")
    return result


def _json_file(path: str, ref: str) -> tuple[dict[str, Any], str]:
    text, sha = _decode_content(_contents(path, ref))
    return strict_json_object(text), sha


def _text_file(path: str, ref: str) -> tuple[str, str]:
    return _decode_content(_contents(path, ref))


def _branch_head(branch: str) -> str:
    result = _private_get(f"repos/{PRIVATE_REPOSITORY}/branches/{urllib.parse.quote(branch, safe='')}")
    if not isinstance(result, Mapping):
        raise CarrierError("private branch response invalid")
    sha = ((result.get("commit") or {}).get("sha"))
    if not isinstance(sha, str) or len(sha) != 40:
        raise CarrierError("private branch identity invalid")
    return sha


def _load_authority_bundle(main_sha: str) -> V4AuthorityBundle:
    mission_entries = _private_get(
        f"repos/{PRIVATE_REPOSITORY}/contents/{MISSION_DIR}?ref={urllib.parse.quote(main_sha, safe='')}"
    )
    authority_entries = _private_get(
        f"repos/{PRIVATE_REPOSITORY}/contents/{REPOSITORY_AUTHORITY_DIR}?ref={urllib.parse.quote(main_sha, safe='')}"
    )
    if not isinstance(mission_entries, list) or not isinstance(authority_entries, list):
        raise CarrierError("private authority registry unavailable")

    mission_paths = sorted(
        entry["path"]
        for entry in mission_entries
        if isinstance(entry, Mapping)
        and entry.get("type") == "file"
        and isinstance(entry.get("path"), str)
        and entry["path"].startswith(f"{MISSION_DIR}/")
        and entry["path"].endswith(".mission.json")
        and "/" not in entry["path"][len(MISSION_DIR) + 1:]
    )
    authority_paths = sorted(
        entry["path"]
        for entry in authority_entries
        if isinstance(entry, Mapping)
        and entry.get("type") == "file"
        and isinstance(entry.get("path"), str)
        and entry["path"].startswith(f"{REPOSITORY_AUTHORITY_DIR}/")
        and entry["path"].endswith(".json")
        and "/" not in entry["path"][len(REPOSITORY_AUTHORITY_DIR) + 1:]
    )
    if not mission_paths or not authority_paths:
        raise CarrierError("private authority registry incomplete")

    missions: list[dict[str, Any]] = []
    authorities: list[dict[str, Any]] = []
    mission_shas: dict[str, str] = {}
    authority_shas: dict[str, str] = {}
    for path in mission_paths:
        mission, blob_sha = _json_file(path, main_sha)
        mission_id = mission.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id or mission_id in mission_shas:
            raise CarrierError("private Mission identity invalid")
        mission_shas[mission_id] = blob_sha
        missions.append(mission)
    for path in authority_paths:
        authority, blob_sha = _json_file(path, main_sha)
        repository = authority.get("repository")
        if not isinstance(repository, str) or not repository:
            raise CarrierError("private repository authority identity invalid")
        key = repository.lower()
        if key in authority_shas:
            raise CarrierError("private repository authority duplicated")
        authority_shas[key] = blob_sha
        authorities.append(authority)
    validate_authority_set(missions, authorities)
    return V4AuthorityBundle(
        missions=tuple(missions),
        authorities=tuple(authorities),
        mission_blob_shas=mission_shas,
        authority_blob_shas=authority_shas,
    )


def _load_current() -> dict[str, Any]:
    repository = _private_get(f"repos/{PRIVATE_REPOSITORY}")
    node_id = repository.get("node_id") if isinstance(repository, Mapping) else None
    if (
        not isinstance(repository, Mapping)
        or repository.get("full_name") != PRIVATE_REPOSITORY
        or repository.get("private") is not True
        or not isinstance(node_id, str)
        or not node_id
    ):
        raise CarrierError("private repository identity invalid")

    main_sha = _branch_head("main")
    runtime_sha = _branch_head(RUNTIME_BRANCH)
    authority, _authority_blob = _json_file(AUTHORITY_PATH, main_sha)
    runner_config, runner_blob = _json_file(RUNNER_CONFIG_PATH, main_sha)
    prompt_text, prompt_blob = _text_file(PROMPT_PATH, main_sha)
    runtime_enabled, integration_enabled = validate_runtime_binding(
        authority,
        runner_config,
        prompt_text,
        runner_config_blob_sha=runner_blob,
        prompt_blob_sha=prompt_blob,
    )
    bundle = _load_authority_bundle(main_sha)
    queue, queue_blob = _json_file(QUEUE_PATH, runtime_sha)
    validate_queue_v4(queue)
    assert_v4_queue_bound_to_authority(queue, bundle)
    return {
        "repository_node_id": node_id,
        "main_sha": main_sha,
        "runtime_sha": runtime_sha,
        "queue_blob": queue_blob,
        "queue": queue,
        "runtime_enabled": runtime_enabled,
        "integration_enabled": integration_enabled,
    }


def _tick_command_identity() -> tuple[int, datetime]:
    try:
        command_id = int(os.environ["CONTROL_V4_PUBLIC_COMMAND_ID"])
        created_at = datetime.fromisoformat(
            os.environ["CONTROL_V4_PUBLIC_COMMAND_CREATED_AT"].replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CarrierError("TICK command correlation identity invalid") from exc
    if created_at.tzinfo is None:
        raise CarrierError("TICK command correlation timestamp invalid")
    return command_id, created_at.astimezone(timezone.utc)


def _assert_tick_fresh(*, now: datetime) -> None:
    _command_id, created_at = _tick_command_identity()
    current = now.astimezone(timezone.utc)
    age_seconds = (current - created_at).total_seconds()
    if not 0 <= age_seconds <= TICK_MAX_AGE_SECONDS:
        raise StaleEventError("TICK command stale at transition")


def _assert_tick_not_superseded(command: Mapping[str, Any]) -> None:
    if command.get("kind") != "TICK":
        return
    command_id, created_at = _tick_command_identity()

    since = urllib.parse.quote(
        created_at.isoformat().replace("+00:00", "Z"),
        safe="",
    )
    comments = _request_json(
        f"{API}/repos/{PUBLIC_COMMAND_REPOSITORY}/issues/{PUBLIC_COMMAND_ISSUE}/comments"
        f"?since={since}&per_page=100&sort=created&direction=asc",
        headers=_public_command_headers(),
    )
    if not isinstance(comments, list):
        raise CarrierError("TICK command supersession read invalid")
    if len(comments) >= 100:
        raise CarrierError("TICK command supersession window exceeds bounded read")

    for item in comments:
        if not isinstance(item, Mapping) or item.get("id") == command_id:
            continue
        user = item.get("user") or {}
        if not isinstance(user, Mapping) or user.get("login") != PUBLIC_COMMAND_ACTOR:
            continue
        other_body = item.get("body")
        other_created_raw = item.get("created_at")
        other_id = item.get("id")
        if not isinstance(other_body, str) or not isinstance(other_created_raw, str) or not isinstance(other_id, int):
            continue
        try:
            other_created = datetime.fromisoformat(other_created_raw.replace("Z", "+00:00"))
            other = parse_public_command(other_body)
        except (ValueError, RuntimeProtocolError):
            continue
        if other.get("run_id") != command.get("run_id"):
            continue
        if other_created > created_at or (other_created == created_at and other_id > command_id):
            raise StaleEventError("TICK command superseded by later same-run command")


def _assert_current_command_fresh_at_ref_cas(source_queue: Mapping[str, Any]) -> None:
    raw_command = os.environ.get("CONTROL_V4_PUBLIC_COMMAND", "")
    try:
        command = parse_public_command(raw_command)
    except RuntimeProtocolError as exc:
        raise CarrierError("current public command unavailable at private ref CAS") from exc
    if command.get("kind") == "TICK":
        _assert_tick_fresh(now=datetime.now(timezone.utc))
        return
    if command.get("kind") == "EVENT":
        bound_event = bind_public_event_to_holder(source_queue, command)
        assert_event_identity(source_queue, bound_event, now=datetime.now(timezone.utc))


def _update_refs_exact(
    *,
    repository_node_id: str,
    main_oid: str,
    runtime_before_oid: str,
    runtime_after_oid: str,
    client_id: str,
    source_queue: Mapping[str, Any],
) -> None:
    mutation = """
    mutation UpdateRefs($input: UpdateRefsInput!) {
      updateRefs(input: $input) { clientMutationId }
    }
    """
    _assert_current_command_fresh_at_ref_cas(source_queue)
    result = _request_json(
        GRAPHQL,
        headers=_private_headers(),
        method="POST",
        payload={
            "query": mutation,
            "variables": {
                "input": {
                    "repositoryId": repository_node_id,
                    "clientMutationId": client_id,
                    "refUpdates": [
                        {
                            "name": "refs/heads/main",
                            "beforeOid": main_oid,
                            "afterOid": main_oid,
                            "force": False,
                        },
                        {
                            "name": f"refs/heads/{RUNTIME_BRANCH}",
                            "beforeOid": runtime_before_oid,
                            "afterOid": runtime_after_oid,
                            "force": False,
                        },
                    ],
                }
            },
        },
    )
    if not isinstance(result, Mapping):
        raise CarrierError("private ref update response invalid")
    if result.get("errors"):
        raise StaleWriteError("exact private authority/runtime ref update rejected")
    if not isinstance(((result.get("data") or {}).get("updateRefs")), Mapping):
        raise CarrierError("private ref update returned no success payload")


def _serialize_queue(queue: Mapping[str, Any]) -> str:
    validate_queue_v4(queue)
    return json.dumps(queue, separators=(",", ":"), ensure_ascii=False)


def _write_queue_exact(state: Mapping[str, Any], queue: Mapping[str, Any], *, reason: str) -> dict[str, Any]:
    validate_queue_v4(queue)
    if _branch_head("main") != state["main_sha"]:
        raise StaleWriteError("private authority moved before runtime write")
    if _branch_head(RUNTIME_BRANCH) != state["runtime_sha"]:
        raise StaleWriteError("private runtime ref moved before runtime write")
    _current_text, current_blob = _decode_content(_contents(QUEUE_PATH, state["runtime_sha"]))
    if current_blob != state["queue_blob"]:
        raise StaleWriteError("private queue blob moved before runtime write")

    new_text = _serialize_queue(queue)
    blob = _private_post(
        f"repos/{PRIVATE_REPOSITORY}/git/blobs",
        {"content": base64.b64encode(new_text.encode("utf-8")).decode("ascii"), "encoding": "base64"},
    )
    new_blob = blob.get("sha") if isinstance(blob, Mapping) else None
    if not isinstance(new_blob, str) or len(new_blob) != 40:
        raise CarrierError("private queue blob creation failed")

    parent = _private_get(f"repos/{PRIVATE_REPOSITORY}/git/commits/{state['runtime_sha']}")
    parent_tree = ((parent.get("tree") or {}).get("sha")) if isinstance(parent, Mapping) else None
    if not isinstance(parent_tree, str) or len(parent_tree) != 40:
        raise CarrierError("private runtime parent tree unavailable")
    tree = _private_post(
        f"repos/{PRIVATE_REPOSITORY}/git/trees",
        {
            "base_tree": parent_tree,
            "tree": [{"path": QUEUE_PATH, "mode": "100644", "type": "blob", "sha": new_blob}],
        },
    )
    new_tree = tree.get("sha") if isinstance(tree, Mapping) else None
    if not isinstance(new_tree, str) or len(new_tree) != 40:
        raise CarrierError("private runtime tree creation failed")
    commit = _private_post(
        f"repos/{PRIVATE_REPOSITORY}/git/commits",
        {
            "message": f"runtime: V4 carrier {reason}",
            "tree": new_tree,
            "parents": [state["runtime_sha"]],
        },
    )
    new_commit = commit.get("sha") if isinstance(commit, Mapping) else None
    if not isinstance(new_commit, str) or len(new_commit) != 40:
        raise CarrierError("private runtime commit creation failed")

    _update_refs_exact(
        repository_node_id=state["repository_node_id"],
        main_oid=state["main_sha"],
        runtime_before_oid=state["runtime_sha"],
        runtime_after_oid=new_commit,
        client_id=f"control-v4-runtime-{os.environ.get('GITHUB_RUN_ID', 'unknown')}-{reason}",
        source_queue=state["queue"],
    )
    if _branch_head(RUNTIME_BRANCH) != new_commit:
        raise CarrierError("mandatory private runtime ref readback failed")
    if _branch_head("main") != state["main_sha"]:
        raise CarrierError("private authority moved during runtime write")
    readback, readback_blob = _json_file(QUEUE_PATH, new_commit)
    if readback_blob != new_blob or readback != queue:
        raise CarrierError("mandatory private queue readback failed")
    validate_queue_v4(readback)
    return {**state, "runtime_sha": new_commit, "queue_blob": new_blob, "queue": readback}


def _assert_public_target_repository(repository: str) -> None:
    repo = _public_get(f"repos/{repository}", allow_404=True)
    if not isinstance(repo, Mapping) or repo.get("full_name") != repository or repo.get("private") is not False:
        raise RuntimeProtocolError("target repository is not publicly readable by carrier V1")


def _target_pr_candidate(repository: str, pr_number: int) -> dict[str, Any]:
    _assert_public_target_repository(repository)
    pr = _public_get(f"repos/{repository}/pulls/{pr_number}", allow_404=True)
    if (
        not isinstance(pr, Mapping)
        or pr.get("number") != pr_number
        or pr.get("state") != "open"
        or pr.get("merged_at") is not None
    ):
        raise RuntimeProtocolError("target pull request is not an open public candidate")
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    values = (head.get("sha"), head.get("ref"), base.get("ref"), base.get("sha"))
    if not all(isinstance(value, str) and value for value in values):
        raise RuntimeProtocolError("target pull request identity incomplete")
    return {
        "candidate_sha": values[0],
        "candidate_pr_number": pr_number,
        "candidate_head_branch": values[1],
        "expected_base_branch": values[2],
        "expected_base_sha": values[3],
    }


def _tick(command: Mapping[str, Any], state: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    if state["runtime_enabled"] is not True:
        return state, {"protocol": RESULT_PROTOCOL_ID, "result": "NO_WORK", "run_id": command["run_id"]}
    if state["integration_enabled"] is True:
        return state, {
            "protocol": RESULT_PROTOCOL_ID,
            "result": "UNSUPPORTED",
            "code": "INTEGRATION_ENABLED_REQUIRES_SEPARATE_REVIEWED_CARRIER_EXTENSION",
            "run_id": command["run_id"],
        }

    queue = state["queue"]
    lock = queue.get("execution_lock")
    if isinstance(lock, Mapping) and datetime.fromisoformat(lock["expires_at"].replace("Z", "+00:00")) <= now:
        recovered, changed = recover_expired_lock_v4(queue, now=now)
        if changed:
            state = _write_queue_exact(state, recovered, reason="expired-lock-recovery")
            queue = state["queue"]
            lock = None

    if isinstance(lock, Mapping):
        if lock.get("run_id") != command["run_id"]:
            return state, {"protocol": RESULT_PROTOCOL_ID, "result": "BUSY", "run_id": command["run_id"]}
        task_id = lock.get("task_id")
        if not isinstance(task_id, str):
            raise CarrierError("current private lock task invalid")
    else:
        task_id = select_task_id_v4(
            queue,
            run_id=command["run_id"],
            yielded_task_tokens=command.get("yielded_task_tokens", []),
            integration_enabled=False,
        )
        if task_id is None:
            return state, {"protocol": RESULT_PROTOCOL_ID, "result": "NO_WORK", "run_id": command["run_id"]}
        acquired = acquire_task_v4(
            queue,
            task_id=task_id,
            run_id=command["run_id"],
            now=now,
            control_runtime_enabled=True,
            integration_enabled=False,
        )
        state = _write_queue_exact(state, acquired, reason="acquire")
        queue = state["queue"]

    task = next(item for item in queue["tasks"] if item["task_id"] == task_id)
    candidate = task.get("candidate")
    live_candidate = None
    try:
        if isinstance(candidate, Mapping):
            live_candidate = _target_pr_candidate(task["repository"], candidate["candidate_pr_number"])
        else:
            _assert_public_target_repository(task["repository"])
    except RuntimeProtocolError:
        blocked = block_holder_v4(
            queue,
            task_id=task_id,
            run_id=command["run_id"],
            blocker="TARGET_REPOSITORY_NOT_PUBLICLY_READABLE_BY_CARRIER_V1",
            now=now,
        )
        state = _write_queue_exact(state, blocked, reason="unsupported-target-block")
        return state, {
            "protocol": RESULT_PROTOCOL_ID,
            "result": "BLOCKED",
            "code": "TARGET_NOT_PUBLICLY_READABLE",
            "run_id": command["run_id"],
        }

    if task.get("phase") == "REVIEW" and isinstance(candidate, Mapping) and live_candidate is not None:
        reconciled, drifted = reconcile_review_candidate_drift_v4(
            queue,
            task_id=task_id,
            run_id=command["run_id"],
            live_candidate=live_candidate,
            now=now,
        )
        if drifted:
            state = _write_queue_exact(state, reconciled, reason="candidate-drift-to-repair")
            return state, safe_work_capsule(
                state["queue"],
                task_id=task_id,
                run_id=command["run_id"],
                live_candidate=live_candidate,
            )

    return state, safe_work_capsule(
        state["queue"],
        task_id=task_id,
        run_id=command["run_id"],
        live_candidate=live_candidate if task.get("phase") == "REPAIR" else None,
    )


def _validate_public_ref_for_task(task: Mapping[str, Any], value: str) -> None:
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("public evidence reference requires candidate")
    prefix = f"https://github.com/{task['repository']}/pull/{candidate['candidate_pr_number']}"
    if not (value.startswith(prefix + "#") or value.startswith(prefix + "/")):
        raise RuntimeProtocolError("public evidence reference is outside exact target PR")


def _release_event_holder_boundary(queue: Mapping[str, Any], command: Mapping[str, Any]) -> dict[str, Any]:
    """Return one queue image in which an accepted EVENT cannot retain its holder."""
    lock = queue.get("execution_lock")
    if lock is None:
        return dict(queue)
    if not isinstance(lock, Mapping):
        raise RuntimeProtocolError("EVENT holder identity invalid")
    if lock.get("run_id") != command["run_id"] or lock.get("task_id") != command["task_id"]:
        raise RuntimeProtocolError("EVENT transition produced a different holder")
    released = dict(queue)
    released["execution_lock"] = None
    validate_queue_v4(released)
    return released


def _event_result(state: Mapping[str, Any], command: Mapping[str, Any]) -> dict[str, Any]:
    current = next(item for item in state["queue"]["tasks"] if item["task_id"] == command["task_id"])
    if state["queue"].get("execution_lock") is not None:
        raise RuntimeProtocolError("accepted EVENT retained execution lock")
    return {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "READY" if current.get("status") == "READY" else "YIELDED",
        "run_id": command["run_id"],
        "task_token": task_token(current, command["run_id"]),
    }


def _event(command: Mapping[str, Any], state: dict[str, Any], *, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    if state["runtime_enabled"] is not True:
        raise StaleEventError("runtime disabled")
    if state["integration_enabled"] is True:
        raise RuntimeProtocolError("carrier V1 requires integration disabled")
    queue = state["queue"]
    command = bind_public_event_to_holder(queue, command)
    task = next(item for item in queue["tasks"] if item["task_id"] == command["task_id"])
    event = command["event"]

    review_events_requiring_live_candidate = {
        "INTERNAL_PASS",
        "INTERNAL_REPAIR",
        "EXTERNAL_REQUESTED",
        "EXTERNAL_FINDING",
        "EXTERNAL_PASS",
        "REVIEW_UNAVAILABLE",
    }
    if (
        event in review_events_requiring_live_candidate
        and task.get("status") == "ACTIVE"
        and task.get("phase") == "REVIEW"
        and isinstance(task.get("candidate"), Mapping)
    ):
        live_candidate = _target_pr_candidate(task["repository"], task["candidate"]["candidate_pr_number"])
        reconciled, drifted = reconcile_review_candidate_drift_v4(
            queue,
            task_id=command["task_id"],
            run_id=command["run_id"],
            live_candidate=live_candidate,
            now=now,
        )
        if drifted:
            next_queue = _release_event_holder_boundary(reconciled, command)
            state = _write_queue_exact(state, next_queue, reason="candidate-drift-to-repair")
            return state, _event_result(state, command)

    if event == "YIELD":
        next_queue = yield_holder_v4(queue, command, now=now)
    elif event == "CANDIDATE_READY":
        verified = _target_pr_candidate(task["repository"], command["candidate_pr_number"])
        next_queue = candidate_ready_v4(queue, command, verified_candidate=verified, now=now)
    elif event == "INTERNAL_PASS":
        next_queue = internal_review_v4(
            queue, command, verdict="PASS", now=now,
            control_runtime_enabled=True, integration_enabled=False,
        )
    elif event == "INTERNAL_REPAIR":
        next_queue = internal_review_v4(
            queue, command, verdict="REPAIR_REQUIRED", now=now,
            control_runtime_enabled=True, integration_enabled=False,
        )
    elif event == "EXTERNAL_REQUESTED":
        _validate_public_ref_for_task(task, command["request_ref"])
        next_queue = external_requested_v4(queue, command, now=now)
    elif event == "EXTERNAL_FINDING":
        _validate_public_ref_for_task(task, command["evidence_ref"])
        next_queue = external_finding_v4(queue, command, now=now)
    elif event == "EXTERNAL_PASS":
        _validate_public_ref_for_task(task, command["evidence_ref"])
        next_queue = external_pass_v4(
            queue, command, now=now,
            control_runtime_enabled=True, integration_enabled=False,
        )
    elif event == "REVIEW_UNAVAILABLE":
        next_queue = external_unavailable_v4(queue, command, now=now)
    else:  # pragma: no cover
        raise RuntimeProtocolError("unsupported event")

    next_queue = _release_event_holder_boundary(next_queue, command)
    if next_queue != queue:
        state = _write_queue_exact(state, next_queue, reason=event.lower().replace("_", "-"))
    return state, _event_result(state, command)


def _set_outputs(result: Mapping[str, Any], *, ok: bool) -> None:
    text = compact_public_result(result)
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        print(text)
        return
    with open(output_path, "a", encoding="utf-8") as output:
        output.write(f"result_json={text}\n")
        output.write(f"ok={'true' if ok else 'false'}\n")


def main() -> int:
    comment = os.environ.get("CONTROL_V4_PUBLIC_COMMAND", "")
    try:
        command = parse_public_command(comment)
    except RuntimeProtocolError:
        _set_outputs({"protocol": RESULT_PROTOCOL_ID, "result": "REJECTED", "code": "INVALID_COMMAND"}, ok=True)
        return 0

    try:
        state = _load_current()
        if command["kind"] == "TICK":
            _assert_tick_not_superseded(command)
            now = datetime.now(timezone.utc)
            _assert_tick_fresh(now=now)
            _state, result = _tick(command, state, now=now)
        else:
            now = datetime.now(timezone.utc)
            _state, result = _event(command, state, now=now)
        _set_outputs(result, ok=True)
    except StaleWriteError:
        _set_outputs({"protocol": RESULT_PROTOCOL_ID, "result": "RETRY", "code": "STALE_PRIVATE_STATE", "run_id": command.get("run_id")}, ok=True)
    except StaleEventError:
        _set_outputs({"protocol": RESULT_PROTOCOL_ID, "result": "REJECTED", "code": "STALE_EVENT", "run_id": command.get("run_id")}, ok=True)
    except (RuntimeProtocolError, V4ValidationError, CarrierError):
        _set_outputs({"protocol": RESULT_PROTOCOL_ID, "result": "ERROR", "code": "FAIL_CLOSED", "run_id": command.get("run_id")}, ok=False)
    except Exception:  # never expose private data through logs or public transport
        _set_outputs({"protocol": RESULT_PROTOCOL_ID, "result": "ERROR", "code": "UNEXPECTED_FAIL_CLOSED", "run_id": command.get("run_id")}, ok=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())