#!/usr/bin/env python3
"""Materialize one exact-candidate ASSURANCE root into Minimal Core V1.

This is deterministic lifecycle plumbing only. It creates no semantic verdict,
implementation, merge, release, provider route, scheduler, queue, or state plane.
The canonical private DISPATCH_QUEUE remains the sole execution authority.
"""

from __future__ import annotations

import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_engine import minimal_core as core
from scripts import private_minimal_core_apply as bridge

ALLOWED_SPEC_FIELDS = {
    "task_id",
    "repository",
    "candidate_sha",
    "priority",
    "instruction",
    "acceptance_criteria",
}
ROOT_FORBIDDEN_LINEAGE_FIELDS = {
    "predecessor_task_id",
    "mission_id",
    "mission_revision",
    "mission_gap_id",
    "mission_contract_ref",
    "depends_on",
}
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _ts_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decode_spec(value: str) -> dict:
    if not value or len(value) > 32768:
        raise RuntimeError("root spec is missing or too large")
    if any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=" for ch in value):
        raise RuntimeError("root spec must be base64url")
    padding = "=" * ((4 - len(value) % 4) % 4)
    try:
        raw = base64.urlsafe_b64decode((value + padding).encode("ascii"))
        spec = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("root spec is not valid base64url JSON") from exc
    if not isinstance(spec, dict):
        raise RuntimeError("root spec must be a JSON object")
    unknown = set(spec) - ALLOWED_SPEC_FIELDS
    if unknown:
        raise RuntimeError(f"root spec contains unsupported fields: {sorted(unknown)}")
    return spec


def _validated_strings(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RuntimeError("acceptance_criteria must be a non-empty list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RuntimeError("acceptance_criteria must contain non-empty strings")
    return list(value)


def _root_from_spec(spec: dict, now: str) -> dict:
    task_id = spec.get("task_id")
    repository = spec.get("repository")
    candidate_sha = spec.get("candidate_sha")
    priority = spec.get("priority", 100)
    instruction = spec.get("instruction")

    if not isinstance(task_id, str) or TASK_ID_RE.fullmatch(task_id) is None:
        raise RuntimeError("task_id is invalid")
    if not isinstance(repository, str) or REPOSITORY_RE.fullmatch(repository) is None:
        raise RuntimeError("repository must be owner/name")
    if not isinstance(candidate_sha, str) or SHA_RE.fullmatch(candidate_sha) is None:
        raise RuntimeError("ASSURANCE root requires exact candidate SHA")
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise RuntimeError("priority must be an integer")
    if not isinstance(instruction, str) or not instruction.strip():
        raise RuntimeError("instruction is required")
    acceptance = _validated_strings(spec.get("acceptance_criteria"))

    task = {
        "lifecycle_model": core.PROTOCOL_ID,
        "task_id": task_id,
        "operation": "ASSURANCE",
        "role": core.ROLE_B,
        "repository": repository,
        "priority": priority,
        "candidate_sha": candidate_sha,
        "status": core.STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "successor_by_outcome": {
            "PASS": {
                "task_id": f"{task_id}--INTEGRATE",
                "operation": "PROJECT_INTEGRATION",
                "role": core.ROLE_A,
                "repository": repository,
                "candidate_sha": candidate_sha,
            },
            "FAIL": {
                "task_id": f"{task_id}--REPAIR",
                "operation": "REPAIR",
                "role": core.ROLE_A,
                "repository": repository,
                "candidate_sha": candidate_sha,
            },
        },
        "principal_manual_relay_count": 0,
        "created_at": now,
        "updated_at": now,
        "instruction": instruction,
        "acceptance_criteria": acceptance,
    }
    core._assert_task_shape(task)
    return task


def _identity_projection(task: dict) -> dict:
    fields = (
        "lifecycle_model",
        "task_id",
        "operation",
        "role",
        "repository",
        "priority",
        "candidate_sha",
        "successor_by_outcome",
        "principal_manual_relay_count",
        "instruction",
        "acceptance_criteria",
    )
    return {field: deepcopy(task.get(field)) for field in fields}


def _root_identity_projection(task: dict) -> dict:
    present_lineage = sorted(field for field in ROOT_FORBIDDEN_LINEAGE_FIELDS if field in task)
    if present_lineage:
        raise RuntimeError(f"root task contains lineage metadata: {present_lineage}")
    created_at = task.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise RuntimeError("root task requires immutable created_at")
    return {**_identity_projection(task), "created_at": created_at}


def _assert_root_id_available(queue: dict, task_id: str) -> None:
    for other in queue.get("tasks", []):
        if other.get("status") == core.STATUS_TERMINAL:
            continue
        successors = other.get("successor_by_outcome")
        if not isinstance(successors, dict):
            continue
        if any(
            isinstance(successor, dict) and successor.get("task_id") == task_id
            for successor in successors.values()
        ):
            raise RuntimeError("root task_id is reserved by an existing non-terminal task")


def command_materialize(token: str, spec_b64: str) -> int:
    spec = _decode_spec(spec_b64)

    def mutate(state_dir):
        queue_path = state_dir / bridge.QUEUE_REL
        queue = bridge._load(queue_path)
        bridge._assert_legacy_b1_retired(state_dir)
        proposed = _root_from_spec(spec, _ts_now())
        identity = _identity_projection(proposed)
        matches = [task for task in queue.get("tasks", []) if task.get("task_id") == proposed["task_id"]]
        if matches:
            if len(matches) != 1 or _identity_projection(matches[0]) != identity:
                raise RuntimeError("root task identity already exists with different immutable specification")
            root_identity = _root_identity_projection(matches[0])
            core.validate(queue)
            return {"task_id": proposed["task_id"], "created": False, "root_identity": root_identity}

        _assert_root_id_available(queue, proposed["task_id"])
        core._assert_direct_successor_ids_available(queue, proposed)
        root_identity = _root_identity_projection(proposed)
        queue.setdefault("tasks", []).append(proposed)
        core.validate(queue)
        bridge._write(queue_path, queue)
        return {"task_id": proposed["task_id"], "created": True, "root_identity": root_identity}

    captured, readback_queue, attempt = bridge._with_cas(
        token,
        mutate,
        message=f"runtime: materialize Minimal Core assurance root {spec.get('task_id', 'UNKNOWN')}",
    )
    matches = [task for task in readback_queue.get("tasks", []) if task.get("task_id") == captured["task_id"]]
    if len(matches) != 1:
        raise RuntimeError("materialized root missing from authoritative readback")
    core.validate(readback_queue)
    if _root_identity_projection(matches[0]) != captured["root_identity"]:
        raise RuntimeError("materialized root immutable identity drifted in authoritative readback")
    print("CONTROL_MINIMAL_CORE_MATERIALIZE=SUCCESS")
    print(f"CONTROL_MINIMAL_CORE_TASK_ID={captured['task_id']}")
    print(f"CONTROL_MINIMAL_CORE_CREATED={'true' if captured['created'] else 'false'}")
    print(f"CONTROL_MINIMAL_CORE_CAS_ATTEMPT={attempt}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize one exact-candidate Minimal Core assurance root")
    parser.add_argument("--spec-b64", required=True)
    args = parser.parse_args()
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("CONTROL_MINIMAL_CORE=NO_TOKEN")
        return 78
    try:
        return command_materialize(token, args.spec_b64)
    except Exception as exc:
        print(f"CONTROL_MINIMAL_CORE=FAILED:{type(exc).__name__}:{str(exc)[-1200:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
