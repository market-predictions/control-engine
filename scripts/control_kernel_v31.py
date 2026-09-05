#!/usr/bin/env python3
"""Historical Control Autonomy V3.1 deterministic writer support.

This module is retained only for bounded pre-V4-80 migration/rollback support
against exact frozen historical authority. It has no current Control runtime
authority and no current workflow reachability. Current semantic execution is
owned by the reviewed Control V4 Runner; this module must not be treated as a
parallel or fallback writer.

The retained implementation executes no semantic inference and never executes
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


def _run(*args: str, cwd: Path | None = None, input_text: str | None = None) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        input=input_text,
        text=True,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def _gh_json(*args: str) -> Any:
    return json.loads(_run("gh", *args))


def _gh_api_text(endpoint: str) -> str:
    return _run("gh", "api", endpoint)


def _repo_default_branch(repository: str) -> str:
    value = _gh_json("api", f"repos/{repository}")
    return value["default_branch"]


def _repo_ref_sha(repository: str, branch: str) -> str:
    value = _gh_json("api", f"repos/{repository}/git/ref/heads/{branch}")
    return value["object"]["sha"]


def _content(repository: str, path: str, ref: str) -> tuple[str, str]:
    value = _gh_json("api", f"repos/{repository}/contents/{path}?ref={urllib.parse.quote(ref, safe='')}")
    raw = base64.b64decode(value["content"])
    return raw.decode("utf-8"), value["sha"]


def _content_optional(repository: str, path: str, ref: str) -> tuple[str, str] | None:
    try:
        return _content(repository, path, ref)
    except subprocess.CalledProcessError as exc:
        if "404" in exc.stderr or "Not Found" in exc.stderr:
            return None
        raise


def _json_content(repository: str, path: str, ref: str) -> tuple[dict[str, Any], str]:
    text, sha = _content(repository, path, ref)
    return json.loads(text), sha


def _list_directory(repository: str, path: str, ref: str) -> list[dict[str, Any]]:
    value = _gh_json("api", f"repos/{repository}/contents/{path}?ref={urllib.parse.quote(ref, safe='')}")
    if not isinstance(value, list):
        raise RuntimeError(f"expected directory: {path}")
    return value


def _write_content_cas(
    repository: str,
    path: str,
    ref: str,
    expected_blob_sha: str,
    body: str,
    message: str,
) -> bool:
    endpoint = f"repos/{repository}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "sha": expected_blob_sha,
        "branch": ref,
    }
    try:
        _run(
            "gh",
            "api",
            "--method",
            "PUT",
            endpoint,
            "--input",
            "-",
            input_text=json.dumps(payload, separators=(",", ":")),
        )
        return True
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.lower()
        if "does not match" in stderr or "sha" in stderr and ("conflict" in stderr or "409" in stderr):
            return False
        raise


def _delete_content_cas(
    repository: str,
    path: str,
    ref: str,
    expected_blob_sha: str,
    message: str,
) -> bool:
    endpoint = f"repos/{repository}/contents/{path}"
    payload = {"message": message, "sha": expected_blob_sha, "branch": ref}
    try:
        _run(
            "gh",
            "api",
            "--method",
            "DELETE",
            endpoint,
            "--input",
            "-",
            input_text=json.dumps(payload, separators=(",", ":")),
        )
        return True
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.lower()
        if "does not match" in stderr or "sha" in stderr and ("conflict" in stderr or "409" in stderr):
            return False
        raise


def _post_json(repository: str, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    text = _run(
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repository}/{endpoint}",
        "--input",
        "-",
        input_text=json.dumps(payload, separators=(",", ":")),
    )
    return json.loads(text)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _load_private_authority(ref: str) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    global_auth, _ = _json_content(CONTROL_REPOSITORY, GLOBAL_AUTH_REL, ref)
    missions = []
    for entry in _list_directory(CONTROL_REPOSITORY, MISSIONS_REL, ref):
        if entry.get("type") != "file" or not entry.get("name", "").endswith(".mission.json"):
            continue
        value, _ = _json_content(CONTROL_REPOSITORY, entry["path"], ref)
        missions.append(value)
    repo_auth: dict[str, dict[str, Any]] = {}
    for entry in _list_directory(CONTROL_REPOSITORY, REPO_AUTH_REL, ref):
        if entry.get("type") != "file" or not entry.get("name", "").endswith(".json"):
            continue
        value, _ = _json_content(CONTROL_REPOSITORY, entry["path"], ref)
        repository = value.get("repository")
        if isinstance(repository, str) and repository:
            repo_auth[repository] = value
    return global_auth, missions, repo_auth


def _load_queue() -> tuple[dict[str, Any], str]:
    return _json_content(CONTROL_REPOSITORY, QUEUE_REL, RUNTIME_REF)


def _write_queue(queue: dict[str, Any], blob_sha: str, message: str) -> bool:
    body = json.dumps(queue, indent=2, sort_keys=True) + "\n"
    return _write_content_cas(CONTROL_REPOSITORY, QUEUE_REL, RUNTIME_REF, blob_sha, body, message)


def _result_path(task_id: str, run_id: str) -> str:
    safe_task = task_id.replace("/", "_")
    safe_run = run_id.replace("/", "_")
    return f"{RESULT_DIR_REL}/{safe_task}--{safe_run}.json"


def _load_result_ref(result_ref: str) -> dict[str, Any]:
    value, _ = _json_content(CONTROL_REPOSITORY, result_ref, RUNTIME_REF)
    return value


def _write_result_if_absent(path: str, result: dict[str, Any]) -> str:
    current = _content_optional(CONTROL_REPOSITORY, path, RUNTIME_REF)
    body = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if current is not None:
        existing, _ = current
        if existing != body:
            raise RuntimeError(f"result path already exists with different bytes: {path}")
        return path
    endpoint = f"repos/{CONTROL_REPOSITORY}/contents/{path}"
    payload = {
        "message": f"control: record worker result {result.get('task_id')}",
        "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
        "branch": RUNTIME_REF,
    }
    _run(
        "gh",
        "api",
        "--method",
        "PUT",
        endpoint,
        "--input",
        "-",
        input_text=json.dumps(payload, separators=(",", ":")),
    )
    return path


def _load_task_target_facts(task: dict[str, Any]) -> dict[str, Any]:
    repository = task["repository"]
    facts: dict[str, Any] = {"repository": repository}
    candidate = task.get("candidate") or {}
    pr_number = candidate.get("candidate_pr_number")
    if isinstance(pr_number, int):
        try:
            pr = _gh_json("api", f"repos/{repository}/pulls/{pr_number}")
            facts["pull_request"] = {
                "number": pr_number,
                "state": pr.get("state"),
                "merged": bool(pr.get("merged_at")),
                "head_sha": pr.get("head", {}).get("sha"),
                "base_branch": pr.get("base", {}).get("ref"),
                "base_sha": pr.get("base", {}).get("sha"),
                "merge_commit_sha": pr.get("merge_commit_sha"),
            }
        except subprocess.CalledProcessError:
            facts["pull_request"] = None
    return facts


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("TICK", "CLAIM", "RECORD", "RELEASE", "MIGRATE"))
    parser.add_argument("--run-id")
    parser.add_argument("--task-id")
    parser.add_argument("--result-ref")
    parser.add_argument("--principal-manual-relay-count", type=int, default=0)
    return parser.parse_args(argv)


def _tick(now: datetime) -> int:
    for _attempt in range(MAX_CAS_ATTEMPTS):
        global_auth, missions, repo_auth = _load_private_authority("main")
        queue, queue_blob = _load_queue()
        updated = core.tick(queue, missions=missions, repository_authority=repo_auth, global_authority=global_auth, now=now)
        if updated == queue:
            print("CONTROL_KERNEL_TICK=NOOP")
            return 0
        if _write_queue(updated, queue_blob, "control: kernel V3.1 tick"):
            print("CONTROL_KERNEL_TICK=UPDATED")
            return 0
    raise RuntimeError("queue CAS conflict budget exhausted")


def _claim(run_id: str, task_id: str, now: datetime) -> int:
    for _attempt in range(MAX_CAS_ATTEMPTS):
        global_auth, missions, repo_auth = _load_private_authority("main")
        queue, queue_blob = _load_queue()
        updated = core.claim(queue, task_id=task_id, run_id=run_id, now=now, missions=missions, repository_authority=repo_auth, global_authority=global_auth)
        if _write_queue(updated, queue_blob, f"control: kernel V3.1 claim {task_id}"):
            print(f"CONTROL_KERNEL_CLAIMED={task_id}")
            return 0
    raise RuntimeError("queue CAS conflict budget exhausted")


def _record(run_id: str, task_id: str, result_ref: str, now: datetime) -> int:
    for _attempt in range(MAX_CAS_ATTEMPTS):
        global_auth, missions, repo_auth = _load_private_authority("main")
        queue, queue_blob = _load_queue()
        result = _load_result_ref(result_ref)
        updated = core.record(queue, task_id=task_id, run_id=run_id, result=result, result_ref=result_ref, now=now, missions=missions, repository_authority=repo_auth, global_authority=global_auth)
        if _write_queue(updated, queue_blob, f"control: kernel V3.1 record {task_id}"):
            print(f"CONTROL_KERNEL_RECORDED={task_id}")
            return 0
    raise RuntimeError("queue CAS conflict budget exhausted")


def _release(run_id: str, task_id: str, now: datetime) -> int:
    for _attempt in range(MAX_CAS_ATTEMPTS):
        global_auth, missions, repo_auth = _load_private_authority("main")
        queue, queue_blob = _load_queue()
        updated = core.release(queue, task_id=task_id, run_id=run_id, now=now, missions=missions, repository_authority=repo_auth, global_authority=global_auth)
        if _write_queue(updated, queue_blob, f"control: kernel V3.1 release {task_id}"):
            print(f"CONTROL_KERNEL_RELEASED={task_id}")
            return 0
    raise RuntimeError("queue CAS conflict budget exhausted")


def _migrate(now: datetime) -> int:
    for _attempt in range(MAX_CAS_ATTEMPTS):
        global_auth, missions, repo_auth = _load_private_authority("main")
        queue, queue_blob = _load_queue()
        updated = migration.migrate(queue, missions=missions, repository_authority=repo_auth, global_authority=global_auth, now=now)
        if updated == queue:
            print("CONTROL_KERNEL_MIGRATE=NOOP")
            return 0
        if _write_queue(updated, queue_blob, "control: migrate queue to V3.1"):
            print("CONTROL_KERNEL_MIGRATE=UPDATED")
            return 0
    raise RuntimeError("queue CAS conflict budget exhausted")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    now = _utcnow()
    if args.principal_manual_relay_count != 0:
        raise RuntimeError("principal_manual_relay_count must remain 0")
    if args.command == "TICK":
        return _tick(now)
    if not args.run_id or not args.task_id:
        raise RuntimeError("CLAIM/RECORD/RELEASE require --run-id and --task-id")
    if args.command == "CLAIM":
        return _claim(args.run_id, args.task_id, now)
    if args.command == "RECORD":
        if not args.result_ref:
            raise RuntimeError("RECORD requires --result-ref")
        return _record(args.run_id, args.task_id, args.result_ref, now)
    if args.command == "RELEASE":
        return _release(args.run_id, args.task_id, now)
    if args.command == "MIGRATE":
        return _migrate(now)
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
