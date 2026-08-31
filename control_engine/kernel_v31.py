from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping
import hashlib
import json
import re
import uuid

PROTOCOL_ID = "CONTROL_AUTONOMY_V3_1"
ROLE_A = "implementation_operations"
ROLE_B = "governance_release_assurance"
INSTANCE_A1 = "A1"
INSTANCE_B1 = "B1"
STATUS_QUEUED = "QUEUED"
STATUS_EXECUTING = "EXECUTING"
STATUS_TERMINAL = "TERMINAL"
STATUS_SUPERSEDED = "SUPERSEDED"
LEASE_SECONDS = 5400
TASK_SEPARATOR = "--"

OPERATION_ROLE = {
    "IMPLEMENTATION": ROLE_A,
    "REPAIR": ROLE_A,
    "ASSURANCE": ROLE_B,
}
OUTCOMES = {
    "IMPLEMENTATION": {"COMPLETED", "BLOCKED"},
    "REPAIR": {"COMPLETED", "BLOCKED"},
    "ASSURANCE": {"PASS", "FAIL", "INDETERMINATE"},
}
WORKER_ROLE = {INSTANCE_A1: ROLE_A, INSTANCE_B1: ROLE_B}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class KernelError(ValueError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise KernelError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ts(value: datetime) -> str:
    return _utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str):
        raise KernelError("timestamp must be a string")
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise KernelError("invalid timestamp") from exc


def _zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(SHA_RE.fullmatch(value))


def _task(queue: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    matches = [t for t in queue.get("tasks", []) if t.get("task_id") == task_id]
    if len(matches) != 1:
        raise KernelError(f"task identity is not unique: {task_id}")
    return matches[0]


def _candidate(candidate: object) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise KernelError("candidate envelope is required")
    required = {
        "candidate_sha",
        "candidate_pr_number",
        "candidate_head_branch",
        "expected_base_branch",
        "expected_base_sha",
    }
    if set(candidate) != required:
        raise KernelError("candidate envelope fields are not exact")
    if not _sha(candidate.get("candidate_sha")) or not _sha(candidate.get("expected_base_sha")):
        raise KernelError("candidate envelope SHA is invalid")
    if not isinstance(candidate.get("candidate_pr_number"), int) or candidate["candidate_pr_number"] < 1:
        raise KernelError("candidate PR number is invalid")
    for key in ("candidate_head_branch", "expected_base_branch"):
        if not isinstance(candidate.get(key), str) or not candidate[key]:
            raise KernelError(f"candidate {key} is invalid")
    return dict(candidate)


def result_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate(queue: Mapping[str, Any]) -> None:
    if not isinstance(queue.get("tasks"), list):
        raise KernelError("queue tasks must be a list")
    if not _zero(queue.get("principal_manual_relay_count")):
        raise KernelError("principal_manual_relay_count must remain integer zero")

    ids: set[str] = set()
    active_workers: set[str] = set()
    active_repositories: set[str] = set()
    active_runs: set[str] = set()
    for task in queue["tasks"]:
        if task.get("lifecycle_model") != PROTOCOL_ID:
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id in ids:
            raise KernelError("invalid or duplicate V3.1 task id")
        ids.add(task_id)
        if not _zero(task.get("principal_manual_relay_count")):
            raise KernelError("task principal_manual_relay_count must remain zero")
        operation = task.get("operation")
        if operation not in OPERATION_ROLE or task.get("role") != OPERATION_ROLE[operation]:
            raise KernelError("task operation/role mismatch")
        if task.get("status") not in {STATUS_QUEUED, STATUS_EXECUTING, STATUS_TERMINAL, STATUS_SUPERSEDED}:
            raise KernelError("invalid V3.1 status")
        if not isinstance(task.get("repository"), str) or not task["repository"]:
            raise KernelError("repository is required")
        if task.get("operation") in {"REPAIR", "ASSURANCE"}:
            _candidate(task.get("candidate"))

        claim = task.get("claim")
        if task["status"] == STATUS_EXECUTING:
            if not isinstance(claim, Mapping):
                raise KernelError("executing task requires claim")
            worker = claim.get("worker_instance")
            run_id = claim.get("run_id")
            if WORKER_ROLE.get(worker) != task["role"] or claim.get("role") != task["role"]:
                raise KernelError("claim role mismatch")
            if worker in active_workers or task["repository"] in active_repositories:
                raise KernelError("active capacity/repository conflict")
            if not isinstance(run_id, str) or not run_id or run_id in active_runs:
                raise KernelError("invalid active run id")
            if _parse_ts(claim.get("expires_at")) <= _parse_ts(claim.get("started_at")):
                raise KernelError("claim expiry must be after start")
            active_workers.add(worker)
            active_repositories.add(task["repository"])
            active_runs.add(run_id)
        elif claim is not None:
            raise KernelError("only executing task may retain claim")

        if task["status"] == STATUS_TERMINAL:
            if task.get("outcome") not in OUTCOMES[operation]:
                raise KernelError("terminal outcome invalid")
            if not isinstance(task.get("result_ref"), str) or not task["result_ref"]:
                raise KernelError("terminal task requires result_ref")
            if not isinstance(task.get("terminal_run_id"), str) or not task["terminal_run_id"]:
                raise KernelError("terminal task requires terminal_run_id")
        elif task.get("outcome") is not None or task.get("result_ref") is not None or task.get("terminal_run_id") is not None:
            raise KernelError("non-terminal task retains terminal state")


def _identity_component(value: object) -> str:
    if not isinstance(value, str) or not value or TASK_SEPARATOR in value:
        raise KernelError("task identity component is invalid")
    return value


def deterministic_root_id(mission_id: str, revision: str, gap_id: str) -> str:
    return TASK_SEPARATOR.join(
        ("MISSION", _identity_component(mission_id), _identity_component(revision), _identity_component(gap_id))
    )


def _successor_id(predecessor_id: str, operation: str, candidate_sha: str | None = None) -> str:
    suffix = operation
    if candidate_sha:
        suffix += f"-{candidate_sha[:12]}"
    return f"{predecessor_id}{TASK_SEPARATOR}{suffix}"


def select_task(queue: Mapping[str, Any], role: str) -> dict[str, Any] | None:
    validate(queue)
    if role not in {ROLE_A, ROLE_B}:
        raise KernelError("unsupported role")
    active_repositories = {
        t["repository"]
        for t in queue["tasks"]
        if t.get("lifecycle_model") == PROTOCOL_ID and t.get("status") == STATUS_EXECUTING
    }
    candidates = [
        t for t in queue["tasks"]
        if t.get("lifecycle_model") == PROTOCOL_ID
        and t.get("status") == STATUS_QUEUED
        and t.get("role") == role
        and t.get("repository") not in active_repositories
    ]
    if not candidates:
        return None
    return deepcopy(sorted(candidates, key=lambda t: (t.get("queued_at", t.get("created_at", "")), t["task_id"]))[0])


def claim(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    worker_instance: str,
    authenticated_role: str,
    now: datetime,
    run_id: str | None = None,
    lease_seconds: int = LEASE_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    q = deepcopy(queue)
    validate(q)
    expected_role = WORKER_ROLE.get(worker_instance)
    if expected_role is None or expected_role != authenticated_role:
        raise KernelError("authenticated caller role does not match worker")
    task = _task(q, task_id)
    if task.get("status") != STATUS_QUEUED or task.get("role") != authenticated_role:
        raise KernelError("task is not claimable by authenticated role")
    if any(
        t.get("lifecycle_model") == PROTOCOL_ID
        and t.get("status") == STATUS_EXECUTING
        and (t.get("repository") == task["repository"] or t.get("claim", {}).get("worker_instance") == worker_instance)
        for t in q["tasks"]
    ):
        raise KernelError("worker or repository capacity unavailable")
    if lease_seconds != LEASE_SECONDS:
        raise KernelError("V3.1 uses one fixed lease")
    now = _utc(now)
    run_id = run_id or f"run-{uuid.uuid4()}"
    task["status"] = STATUS_EXECUTING
    task["attempt_count"] = int(task.get("attempt_count", 0)) + 1
    task["claim"] = {
        "run_id": run_id,
        "role": authenticated_role,
        "worker_instance": worker_instance,
        "started_at": _ts(now),
        "expires_at": _ts(now + timedelta(seconds=lease_seconds)),
    }
    task["updated_at"] = _ts(now)
    validate(q)
    return q, deepcopy(task)


def assert_current_claim(
    queue: Mapping[str, Any], *, task_id: str, run_id: str, worker_instance: str, authenticated_role: str, now: datetime
) -> dict[str, Any]:
    validate(queue)
    task = _task(queue, task_id)
    claim = task.get("claim")
    if task.get("status") != STATUS_EXECUTING or not isinstance(claim, Mapping):
        raise KernelError("current claim is absent")
    if (
        task.get("role") != authenticated_role
        or WORKER_ROLE.get(worker_instance) != authenticated_role
        or claim.get("worker_instance") != worker_instance
        or claim.get("role") != authenticated_role
        or claim.get("run_id") != run_id
    ):
        raise KernelError("current claim identity mismatch")
    if _parse_ts(claim.get("expires_at")) <= _utc(now):
        raise KernelError("claim expired")
    return deepcopy(task)


def release(
    queue: Mapping[str, Any], *, task_id: str, run_id: str, worker_instance: str, authenticated_role: str, reason: str, now: datetime
) -> dict[str, Any]:
    if reason not in {"EXECUTION_UNAVAILABLE", "EXECUTION_ABORTED"}:
        raise KernelError("invalid release reason")
    q = deepcopy(queue)
    assert_current_claim(q, task_id=task_id, run_id=run_id, worker_instance=worker_instance, authenticated_role=authenticated_role, now=now)
    task = _task(q, task_id)
    task["status"] = STATUS_QUEUED
    task["claim"] = None
    task["last_execution_error"] = reason
    task["updated_at"] = _ts(now)
    task["queued_at"] = _ts(now)
    validate(q)
    return q


def _copy_authority(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(source[key])
        for key in (
            "mission_id", "mission_revision", "mission_contract_blob_sha",
            "repository_authority_blob_sha", "gap_id", "integration_policy", "acceptance"
        )
        if key in source
    }


def _new_successor(
    predecessor: Mapping[str, Any], *, operation: str, now: datetime, candidate: Mapping[str, Any], reason: str | None = None
) -> dict[str, Any]:
    candidate_dict = _candidate(candidate)
    task_id = _successor_id(predecessor["task_id"], operation, candidate_dict["candidate_sha"])
    successor: dict[str, Any] = {
        "lifecycle_model": PROTOCOL_ID,
        "task_id": task_id,
        "operation": operation,
        "role": OPERATION_ROLE[operation],
        "repository": predecessor["repository"],
        "candidate": candidate_dict,
        "status": STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "predecessor_task_id": predecessor["task_id"],
        "principal_manual_relay_count": 0,
        "created_at": _ts(now),
        "updated_at": _ts(now),
        "queued_at": _ts(now),
        **_copy_authority(predecessor),
    }
    if reason:
        successor["reason"] = reason
    return successor


def record(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    worker_instance: str,
    authenticated_role: str,
    result: Mapping[str, Any],
    result_ref: str,
    now: datetime,
) -> tuple[dict[str, Any], str | None]:
    q = deepcopy(queue)
    assert_current_claim(q, task_id=task_id, run_id=run_id, worker_instance=worker_instance, authenticated_role=authenticated_role, now=now)
    task = _task(q, task_id)
    outcome = result.get("outcome")
    if outcome not in OUTCOMES[task["operation"]]:
        raise KernelError("result outcome invalid for operation")
    if result.get("role") != authenticated_role or result.get("task_id") != task_id or result.get("run_id") != run_id:
        raise KernelError("result identity mismatch")

    successor: dict[str, Any] | None = None
    candidate: dict[str, Any] | None = None
    if task["operation"] in {"IMPLEMENTATION", "REPAIR"} and outcome == "COMPLETED":
        candidate = _candidate(result.get("candidate"))
        if task["operation"] == "REPAIR" and candidate["candidate_sha"] == task["candidate"]["candidate_sha"]:
            raise KernelError("completed repair must produce fresh candidate SHA")
        successor = _new_successor(task, operation="ASSURANCE", now=now, candidate=candidate)
    elif task["operation"] == "ASSURANCE":
        candidate = _candidate(result.get("candidate"))
        if candidate != _candidate(task.get("candidate")):
            raise KernelError("assurance result candidate envelope mismatch")
        if outcome == "FAIL":
            successor = _new_successor(task, operation="REPAIR", now=now, candidate=candidate, reason="ASSURANCE_FAIL")
        elif outcome == "PASS":
            task["integration_state"] = "HOLD" if task.get("integration_policy") == "HOLD_AFTER_PASS" else "PENDING"

    if successor and any(t.get("task_id") == successor["task_id"] for t in q["tasks"]):
        raise KernelError("deterministic successor already exists")

    task["status"] = STATUS_TERMINAL
    task["outcome"] = outcome
    task["result_ref"] = result_ref
    task["terminal_run_id"] = run_id
    task["claim"] = None
    task["updated_at"] = _ts(now)
    task["last_execution_error"] = None
    if candidate and task["operation"] in {"IMPLEMENTATION", "REPAIR"}:
        task["candidate"] = candidate
    if successor:
        q["tasks"].append(successor)
    validate(q)
    return q, successor["task_id"] if successor else None


def reconcile(
    queue: Mapping[str, Any],
    *,
    now: datetime,
    active_missions: Mapping[str, str] | None = None,
    active_gaps: set[tuple[str, str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    q = deepcopy(queue)
    validate(q)
    now = _utc(now)
    missions_authoritative = active_missions is not None
    gaps_authoritative = active_gaps is not None
    active_missions = active_missions or {}
    active_gaps = active_gaps or set()
    expired: list[str] = []
    superseded: list[str] = []
    for task in q["tasks"]:
        if task.get("lifecycle_model") != PROTOCOL_ID or task.get("status") not in {STATUS_QUEUED, STATUS_EXECUTING}:
            continue
        mission_id = task.get("mission_id")
        revision = task.get("mission_revision")
        gap_id = task.get("gap_id")
        obsolete = False
        if missions_authoritative:
            obsolete = not isinstance(mission_id, str) or active_missions.get(mission_id) != revision
        if not obsolete and gaps_authoritative:
            obsolete = (mission_id, revision, gap_id) not in active_gaps
        if obsolete:
            task["status"] = STATUS_SUPERSEDED
            task["claim"] = None
            task["updated_at"] = _ts(now)
            superseded.append(task["task_id"])
            continue
        if task.get("status") != STATUS_EXECUTING:
            continue
        claim = task["claim"]
        if _parse_ts(claim["expires_at"]) <= now:
            task["status"] = STATUS_QUEUED
            task["claim"] = None
            task["queued_at"] = _ts(now)
            task["updated_at"] = _ts(now)
            task["last_execution_error"] = "CLAIM_EXPIRED"
            expired.append(task["task_id"])
    validate(q)
    return q, {"expired_claims": expired, "superseded_claims": superseded}


def _legacy_gap_satisfied(queue: Mapping[str, Any], mission_id: str, revision: str, gap_id: str) -> bool:
    root = deterministic_root_id(mission_id, revision, gap_id)
    return any(
        (t.get("task_id", "") == root or t.get("task_id", "").startswith(root + TASK_SEPARATOR))
        and t.get("operation") == "PROJECT_INTEGRATION"
        and t.get("status") == "TERMINAL"
        and t.get("outcome") == "COMPLETED"
        for t in queue.get("tasks", [])
    )


def gap_satisfied(queue: Mapping[str, Any], mission_id: str, revision: str, gap_id: str) -> bool:
    if _legacy_gap_satisfied(queue, mission_id, revision, gap_id):
        return True
    return any(
        t.get("lifecycle_model") == PROTOCOL_ID
        and t.get("mission_id") == mission_id
        and t.get("mission_revision") == revision
        and t.get("gap_id") == gap_id
        and t.get("operation") == "ASSURANCE"
        and t.get("status") == STATUS_TERMINAL
        and t.get("outcome") == "PASS"
        and t.get("integration_state") == "MERGED"
        for t in queue.get("tasks", [])
    )


def feed(
    queue: Mapping[str, Any], *, missions: Iterable[Mapping[str, Any]], now: datetime
) -> tuple[dict[str, Any], list[str]]:
    q = deepcopy(queue)
    validate(q)
    now = _utc(now)
    created: list[str] = []
    active_repositories = {
        t["repository"] for t in q["tasks"]
        if t.get("lifecycle_model") == PROTOCOL_ID and t.get("status") == STATUS_EXECUTING
    }
    for wrapped in sorted(missions, key=lambda m: (m["mission"]["mission_id"], m["mission"]["mission_revision"])):
        mission = wrapped["mission"]
        mission_id = mission["mission_id"]
        revision = mission["mission_revision"]
        repository = mission["repository"]
        if repository in active_repositories:
            continue
        for gap in mission["gaps"]:
            if gap.get("gap_state") != "OPEN":
                continue
            gap_id = gap["gap_id"]
            root_id = deterministic_root_id(mission_id, revision, gap_id)
            if any(t.get("task_id") == root_id for t in q["tasks"]):
                continue
            if any(
                t.get("mission_id") == mission_id
                and t.get("mission_revision") == revision
                and t.get("gap_id", t.get("mission_gap_id")) == gap_id
                for t in q["tasks"]
            ):
                continue
            if not all(gap_satisfied(q, mission_id, revision, dep) for dep in gap.get("depends_on", [])):
                continue
            task = {
                "lifecycle_model": PROTOCOL_ID,
                "task_id": root_id,
                "operation": "IMPLEMENTATION",
                "role": ROLE_A,
                "repository": gap["repository"],
                "status": STATUS_QUEUED,
                "outcome": None,
                "claim": None,
                "result_ref": None,
                "terminal_run_id": None,
                "attempt_count": 0,
                "last_execution_error": None,
                "principal_manual_relay_count": 0,
                "created_at": _ts(now),
                "updated_at": _ts(now),
                "queued_at": _ts(now),
                "mission_id": mission_id,
                "mission_revision": revision,
                "mission_contract_blob_sha": wrapped["mission_contract_blob_sha"],
                "repository_authority_blob_sha": wrapped["repository_authority_blob_sha"],
                "gap_id": gap_id,
                "integration_policy": gap["integration_policy"],
                "acceptance": deepcopy(gap["acceptance"]),
            }
            q["tasks"].append(task)
            created.append(root_id)
            break
    validate(q)
    return q, created


def mark_integrated(
    queue: Mapping[str, Any], *, assurance_task_id: str, merge_sha: str, merged_at: datetime
) -> dict[str, Any]:
    if not _sha(merge_sha):
        raise KernelError("merge SHA invalid")
    q = deepcopy(queue)
    task = _task(q, assurance_task_id)
    if not (
        task.get("lifecycle_model") == PROTOCOL_ID
        and task.get("operation") == "ASSURANCE"
        and task.get("status") == STATUS_TERMINAL
        and task.get("outcome") == "PASS"
        and task.get("integration_state") == "PENDING"
    ):
        raise KernelError("assurance is not pending deterministic integration")
    task["integration_state"] = "MERGED"
    task["merge_sha"] = merge_sha
    task["merged_at"] = _ts(merged_at)
    task["updated_at"] = _ts(merged_at)
    validate(q)
    return q


def materialize_base_drift_repair(queue: Mapping[str, Any], *, assurance_task_id: str, now: datetime) -> tuple[dict[str, Any], str]:
    q = deepcopy(queue)
    task = _task(q, assurance_task_id)
    if not (
        task.get("lifecycle_model") == PROTOCOL_ID
        and task.get("operation") == "ASSURANCE"
        and task.get("status") == STATUS_TERMINAL
        and task.get("outcome") == "PASS"
        and task.get("integration_state") == "PENDING"
    ):
        raise KernelError("assurance is not pending integration")
    successor = _new_successor(task, operation="REPAIR", now=now, candidate=task["candidate"], reason="BASE_DRIFT_AFTER_PASS")
    if any(t.get("task_id") == successor["task_id"] for t in q["tasks"]):
        raise KernelError("base-drift repair already exists")
    task["integration_state"] = "BASE_DRIFT"
    task["updated_at"] = _ts(now)
    q["tasks"].append(successor)
    validate(q)
    return q, successor["task_id"]
