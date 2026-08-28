from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import uuid

PROTOCOL_ID = "CONTROL_MINIMAL_CORE_V1"
VERSION = "1.0"

ROLE_A = "implementation_operations"
ROLE_B = "governance_release_assurance"
INSTANCE_A1 = "A1"
INSTANCE_B1 = "B1"

STATUS_QUEUED = "QUEUED"
STATUS_EXECUTING = "EXECUTING"
STATUS_TERMINAL = "TERMINAL"

OPERATION_ROLE = {
    "IMPLEMENTATION": ROLE_A,
    "REPAIR": ROLE_A,
    "PROJECT_INTEGRATION": ROLE_A,
    "ASSURANCE": ROLE_B,
}

OUTCOMES_BY_OPERATION = {
    "IMPLEMENTATION": {"COMPLETED", "BLOCKED"},
    "REPAIR": {"COMPLETED", "BLOCKED"},
    "PROJECT_INTEGRATION": {"COMPLETED", "BLOCKED"},
    "ASSURANCE": {"PASS", "FAIL", "INDETERMINATE"},
}

WORKER_ROLE = {INSTANCE_A1: ROLE_A, INSTANCE_B1: ROLE_B}


class MinimalCoreError(ValueError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MinimalCoreError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ts(value: datetime) -> str:
    return _utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise MinimalCoreError("invalid timestamp") from exc
    return _utc(parsed)


def _valid_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _exact_integer_zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _task(queue: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    matches = [task for task in queue.get("tasks", []) if task.get("task_id") == task_id]
    if len(matches) != 1:
        raise MinimalCoreError(f"expected exactly one task {task_id!r}, found {len(matches)}")
    return matches[0]


def _assert_principal_zero(queue: Mapping[str, Any], task: Mapping[str, Any] | None = None) -> None:
    if not _exact_integer_zero(queue.get("principal_manual_relay_count")):
        raise MinimalCoreError("queue principal_manual_relay_count must remain integer zero")
    if task is not None and not _exact_integer_zero(task.get("principal_manual_relay_count")):
        raise MinimalCoreError("task principal_manual_relay_count must remain integer zero")


def _assert_task_shape(task: Mapping[str, Any]) -> None:
    if task.get("lifecycle_model") != PROTOCOL_ID:
        raise MinimalCoreError("task is not Minimal Core V1")
    if not isinstance(task.get("task_id"), str) or not task["task_id"]:
        raise MinimalCoreError("task_id is required")
    operation = task.get("operation")
    role = OPERATION_ROLE.get(operation)
    if role is None:
        raise MinimalCoreError(f"unsupported operation: {operation!r}")
    if task.get("role") != role:
        raise MinimalCoreError("task role does not match immutable operation")
    if task.get("status") not in {STATUS_QUEUED, STATUS_EXECUTING, STATUS_TERMINAL}:
        raise MinimalCoreError("invalid task status")
    if not isinstance(task.get("repository"), str) or not task["repository"]:
        raise MinimalCoreError("repository is required")
    if operation in {"ASSURANCE", "REPAIR", "PROJECT_INTEGRATION"} and not _valid_sha(task.get("candidate_sha")):
        raise MinimalCoreError(f"{operation.lower()} task requires exact candidate SHA")
    if not isinstance(task.get("priority", 0), int):
        raise MinimalCoreError("priority must be an integer")
    if not isinstance(task.get("attempt_count", 0), int) or task.get("attempt_count", 0) < 0:
        raise MinimalCoreError("attempt_count must be a non-negative integer")

    claim = task.get("claim")
    terminal_run_id = task.get("terminal_run_id")
    if task["status"] == STATUS_EXECUTING:
        if not isinstance(claim, dict):
            raise MinimalCoreError("executing task requires a claim")
        if terminal_run_id is not None:
            raise MinimalCoreError("executing task may not retain terminal_run_id")
    elif claim is not None:
        raise MinimalCoreError("only executing tasks may retain a claim")

    if task["status"] == STATUS_TERMINAL:
        if task.get("outcome") not in OUTCOMES_BY_OPERATION[operation]:
            raise MinimalCoreError("terminal task outcome is invalid for operation")
        if not isinstance(task.get("result_ref"), str) or not task["result_ref"]:
            raise MinimalCoreError("terminal task requires result_ref")
        if not isinstance(terminal_run_id, str) or not terminal_run_id:
            raise MinimalCoreError("terminal task requires terminal_run_id")
    elif task.get("outcome") is not None or task.get("result_ref") is not None or terminal_run_id is not None:
        raise MinimalCoreError("non-terminal task may not retain semantic terminal state")

    successors = task.get("successor_by_outcome", {})
    if not isinstance(successors, dict):
        raise MinimalCoreError("successor_by_outcome must be an object")
    successor_ids: set[str] = set()
    for outcome, successor in successors.items():
        if outcome not in OUTCOMES_BY_OPERATION[operation] or not isinstance(successor, dict):
            raise MinimalCoreError("invalid successor template")
        successor_id = successor.get("task_id")
        if not isinstance(successor_id, str) or not successor_id:
            raise MinimalCoreError("successor task_id is required")
        if successor_id == task["task_id"]:
            raise MinimalCoreError("task cannot succeed itself")
        if successor_id in successor_ids:
            raise MinimalCoreError("direct successor task_id may be reserved only once per task")
        successor_ids.add(successor_id)

    if operation == "PROJECT_INTEGRATION" and successors:
        raise MinimalCoreError("project integration may not create successor authority")

    if operation == "ASSURANCE":
        expected_operation = {"PASS": "PROJECT_INTEGRATION", "FAIL": "REPAIR"}
        if "INDETERMINATE" in successors:
            raise MinimalCoreError("INDETERMINATE assurance may not create a successor")
        for outcome, successor in successors.items():
            expected = expected_operation.get(outcome)
            if expected is None:
                raise MinimalCoreError("invalid assurance successor outcome")
            if successor.get("operation") != expected or successor.get("role") != ROLE_A:
                raise MinimalCoreError("assurance successor routes to invalid authority")
            if successor.get("repository") != task["repository"]:
                raise MinimalCoreError("assurance successor repository mismatch")
            if successor.get("candidate_sha") != task["candidate_sha"]:
                raise MinimalCoreError("assurance successor candidate mismatch")

    if operation in {"IMPLEMENTATION", "REPAIR"}:
        if "BLOCKED" in successors:
            raise MinimalCoreError("blocked A1 work may not create a successor")
        completed = successors.get("COMPLETED")
        if completed is not None:
            if completed.get("operation") != "ASSURANCE" or completed.get("role") != ROLE_B:
                raise MinimalCoreError("A1 completion must route through assurance")
            if completed.get("repository") != task["repository"]:
                raise MinimalCoreError("A1 assurance successor repository mismatch")
            template_candidate = completed.get("candidate_sha")
            if template_candidate is not None and not _valid_sha(template_candidate):
                raise MinimalCoreError("A1 assurance successor candidate template is invalid")


def _assert_direct_successor_ids_available(queue: Mapping[str, Any], task: Mapping[str, Any]) -> None:
    task_id = task["task_id"]
    for successor in task.get("successor_by_outcome", {}).values():
        successor_id = successor["task_id"]
        if any(item.get("task_id") == successor_id for item in queue.get("tasks", [])):
            raise MinimalCoreError(f"successor task already exists: {successor_id}")
        for other in queue.get("tasks", []):
            if other.get("task_id") == task_id or other.get("status") == STATUS_TERMINAL:
                continue
            other_successors = other.get("successor_by_outcome")
            if not isinstance(other_successors, Mapping):
                continue
            if any(
                isinstance(other_successor, Mapping) and other_successor.get("task_id") == successor_id
                for other_successor in other_successors.values()
            ):
                raise MinimalCoreError(f"successor task_id is reserved by another task: {successor_id}")


def _derived_task_id(task_id: str, suffix: str) -> str:
    return f"{task_id}--{suffix}"


def _default_successors(task: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Create only the immediate next transition; never prebuild a lifecycle tree."""
    operation = task["operation"]
    task_id = task["task_id"]
    repository = task["repository"]
    if operation in {"IMPLEMENTATION", "REPAIR"}:
        return {
            "COMPLETED": {
                "task_id": _derived_task_id(task_id, "ASSURE"),
                "operation": "ASSURANCE",
                "role": ROLE_B,
                "repository": repository,
                "candidate_sha": None,
            }
        }
    if operation == "ASSURANCE":
        candidate_sha = task["candidate_sha"]
        return {
            "PASS": {
                "task_id": _derived_task_id(task_id, "INTEGRATE"),
                "operation": "PROJECT_INTEGRATION",
                "role": ROLE_A,
                "repository": repository,
                "candidate_sha": candidate_sha,
            },
            "FAIL": {
                "task_id": _derived_task_id(task_id, "REPAIR"),
                "operation": "REPAIR",
                "role": ROLE_A,
                "repository": repository,
                "candidate_sha": candidate_sha,
            },
        }
    return {}


def validate(queue: Mapping[str, Any]) -> None:
    if queue.get("version") != VERSION or not isinstance(queue.get("tasks"), list):
        raise MinimalCoreError("queue must contain version=1.0 and tasks array")
    _assert_principal_zero(queue)
    ids: set[str] = set()
    active_roles: set[str] = set()
    active_repositories: set[str] = set()
    active_run_ids: set[str] = set()
    terminal_run_ids: set[str] = set()
    for task in queue["tasks"]:
        if task.get("lifecycle_model") != PROTOCOL_ID:
            continue
        _assert_principal_zero(queue, task)
        _assert_task_shape(task)
        task_id = task["task_id"]
        if task_id in ids:
            raise MinimalCoreError(f"duplicate Minimal Core task id: {task_id}")
        ids.add(task_id)

        if task["status"] == STATUS_TERMINAL:
            run_id = task["terminal_run_id"]
            if run_id in terminal_run_ids or run_id in active_run_ids:
                raise MinimalCoreError("duplicate Minimal Core run identity")
            terminal_run_ids.add(run_id)
            continue
        if task["status"] != STATUS_EXECUTING:
            continue

        role = task["role"]
        repository = task["repository"]
        claim = task["claim"]
        run_id = claim.get("run_id")
        if role in active_roles:
            raise MinimalCoreError(f"role capacity exceeded: {role}")
        if repository in active_repositories:
            raise MinimalCoreError(f"repository exclusivity exceeded: {repository}")
        if not isinstance(run_id, str) or not run_id or run_id in active_run_ids or run_id in terminal_run_ids:
            raise MinimalCoreError("invalid or duplicate active run id")
        if claim.get("role") != role or WORKER_ROLE.get(claim.get("worker_instance")) != role:
            raise MinimalCoreError("claim role/worker mismatch")
        started = _parse_ts(claim.get("started_at"))
        if _parse_ts(claim.get("expires_at")) <= started:
            raise MinimalCoreError("claim expiry must be after start")
        active_roles.add(role)
        active_repositories.add(repository)
        active_run_ids.add(run_id)


def _eligible(task: Mapping[str, Any], role: str) -> bool:
    return (
        task.get("lifecycle_model") == PROTOCOL_ID
        and task.get("status") == STATUS_QUEUED
        and task.get("role") == role
        and task.get("claim") is None
    )


def select_task(queue: Mapping[str, Any], role: str) -> dict[str, Any] | None:
    validate(queue)
    if role not in {ROLE_A, ROLE_B}:
        raise MinimalCoreError("unsupported role")
    candidates = [task for task in queue["tasks"] if _eligible(task, role)]
    if not candidates:
        return None
    candidates.sort(key=lambda task: (task.get("priority", 0), task.get("created_at", ""), task["task_id"]))
    return deepcopy(candidates[0])


def claim(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    worker_instance: str,
    backend: str,
    now: datetime,
    lease_seconds: int = 5400,
    run_id: str | None = None,
    require_preferred: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if lease_seconds <= 0:
        raise MinimalCoreError("lease_seconds must be positive")
    current_queue = deepcopy(queue)
    validate(current_queue)
    role = WORKER_ROLE.get(worker_instance)
    if role is None:
        raise MinimalCoreError("unsupported worker instance")
    task = _task(current_queue, task_id)
    _assert_principal_zero(current_queue, task)
    if not _eligible(task, role):
        raise MinimalCoreError("task is not eligible for worker role")
    _assert_direct_successor_ids_available(current_queue, task)
    if require_preferred:
        preferred = select_task(current_queue, role)
        if preferred is None or preferred["task_id"] != task_id:
            raise MinimalCoreError("task is not the preferred eligible task")

    started = _utc(now)
    expires = started + timedelta(seconds=lease_seconds)
    actual_run_id = run_id or f"run-{uuid.uuid4()}"
    used_run_ids = {
        value
        for item in current_queue["tasks"]
        if item.get("lifecycle_model") == PROTOCOL_ID
        for value in (
            (item.get("claim") or {}).get("run_id"),
            item.get("terminal_run_id"),
        )
        if isinstance(value, str)
    }
    if actual_run_id in used_run_ids:
        raise MinimalCoreError("run id already exists")

    task["status"] = STATUS_EXECUTING
    task["attempt_count"] = task.get("attempt_count", 0) + 1
    task["last_execution_error"] = None
    task["claim"] = {
        "run_id": actual_run_id,
        "role": role,
        "worker_instance": worker_instance,
        "backend": backend,
        "started_at": _ts(started),
        "expires_at": _ts(expires),
    }
    task["updated_at"] = _ts(started)
    validate(current_queue)
    return current_queue, deepcopy(task)


def assert_current_claim(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    worker_instance: str,
    run_id: str,
    now: datetime,
) -> dict[str, Any]:
    validate(queue)
    task = _task(queue, task_id)
    role = WORKER_ROLE.get(worker_instance)
    claim_data = task.get("claim")
    if task.get("status") != STATUS_EXECUTING or task.get("role") != role or not isinstance(claim_data, dict):
        raise MinimalCoreError("task is not executing for worker role")
    if claim_data.get("run_id") != run_id or claim_data.get("worker_instance") != worker_instance:
        raise MinimalCoreError("claim identity mismatch")
    if _parse_ts(claim_data["expires_at"]) <= _utc(now):
        raise MinimalCoreError("claim has expired")
    return deepcopy(task)


def _materialize_successor(
    queue: dict[str, Any],
    task: Mapping[str, Any],
    *,
    outcome: str,
    now: datetime,
    result_candidate_sha: str | None = None,
) -> str | None:
    template = task.get("successor_by_outcome", {}).get(outcome)
    if template is None:
        return None
    successor = deepcopy(template)
    successor_id = successor.get("task_id")
    if not isinstance(successor_id, str) or not successor_id:
        raise MinimalCoreError("successor task_id is required")
    if any(item.get("task_id") == successor_id for item in queue["tasks"]):
        raise MinimalCoreError(f"successor task already exists: {successor_id}")
    if task["operation"] in {"IMPLEMENTATION", "REPAIR"} and outcome == "COMPLETED":
        if not _valid_sha(result_candidate_sha):
            raise MinimalCoreError("A1 completed result requires exact resulting candidate SHA")
        successor["candidate_sha"] = result_candidate_sha
    successor.update({
        "lifecycle_model": PROTOCOL_ID,
        "status": STATUS_QUEUED,
        "outcome": None,
        "claim": None,
        "result_ref": None,
        "terminal_run_id": None,
        "attempt_count": 0,
        "last_execution_error": None,
        "predecessor_task_id": task["task_id"],
        "principal_manual_relay_count": 0,
        "updated_at": _ts(now),
    })
    successor.setdefault("priority", task.get("priority", 0))
    successor.setdefault("created_at", _ts(now))
    successor["successor_by_outcome"] = _default_successors(successor)
    _assert_task_shape(successor)
    queue["tasks"].append(successor)
    return successor_id


def finalize_result(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    result: Mapping[str, Any],
    result_ref: str,
    now: datetime,
) -> tuple[dict[str, Any], str | None]:
    current_queue = deepcopy(queue)
    validate(current_queue)
    task = _task(current_queue, task_id)
    _assert_principal_zero(current_queue, task)

    if not isinstance(result_ref, str) or not result_ref:
        raise MinimalCoreError("result_ref is required")
    if result.get("version") != VERSION or result.get("task_id") != task_id:
        raise MinimalCoreError("result task identity mismatch")
    result_run_id = result.get("run_id")
    if not isinstance(result_run_id, str) or not result_run_id:
        raise MinimalCoreError("result run identity is invalid")
    if result.get("role") != task["role"]:
        raise MinimalCoreError("result role mismatch")
    outcome = result.get("outcome")
    if not isinstance(outcome, str) or outcome not in OUTCOMES_BY_OPERATION[task["operation"]]:
        raise MinimalCoreError("result outcome is invalid for operation")
    result_candidate_sha = result.get("candidate_sha")
    a1_result_binds_successor = (
        task["operation"] in {"IMPLEMENTATION", "REPAIR"}
        and outcome == "COMPLETED"
        and task.get("successor_by_outcome", {}).get("COMPLETED") is not None
    )
    if task["role"] == ROLE_B:
        if not _valid_sha(result_candidate_sha) or result_candidate_sha != task["candidate_sha"]:
            raise MinimalCoreError("B1 result candidate mismatch")
    elif a1_result_binds_successor:
        if not _valid_sha(result_candidate_sha):
            raise MinimalCoreError("A1 completed result requires exact resulting candidate SHA")
    elif task.get("candidate_sha") is not None and result_candidate_sha not in {None, task.get("candidate_sha")}:
        raise MinimalCoreError("A1 result candidate mismatch")

    if task.get("status") == STATUS_TERMINAL:
        if (
            task.get("outcome") != outcome
            or task.get("result_ref") != result_ref
            or task.get("terminal_run_id") != result_run_id
        ):
            raise MinimalCoreError("terminal result replay mismatch")
        template = task.get("successor_by_outcome", {}).get(outcome)
        if template is None:
            successor_id = None
        else:
            successor_id = template.get("task_id")
            if not isinstance(successor_id, str) or not successor_id:
                raise MinimalCoreError("terminal successor replay identity invalid")
            successor = _task(current_queue, successor_id)
            if successor.get("predecessor_task_id") != task_id:
                raise MinimalCoreError("terminal successor replay mismatch")
            if (a1_result_binds_successor or task["role"] == ROLE_B) and successor.get("candidate_sha") != result_candidate_sha:
                raise MinimalCoreError("terminal successor candidate replay mismatch")
        return current_queue, successor_id

    if task.get("status") != STATUS_EXECUTING:
        raise MinimalCoreError("result target is not executing")
    claim_data = task["claim"]
    run_id = claim_data["run_id"]
    if result_run_id != run_id:
        raise MinimalCoreError("result task/run identity mismatch")
    if _parse_ts(claim_data["expires_at"]) <= _utc(now):
        raise MinimalCoreError("claim expired before result finalization")

    task.update({
        "status": STATUS_TERMINAL,
        "outcome": outcome,
        "result_ref": result_ref,
        "terminal_run_id": run_id,
        "claim": None,
        "last_execution_error": None,
        "updated_at": _ts(now),
    })
    successor_id = _materialize_successor(
        current_queue,
        task,
        outcome=outcome,
        now=now,
        result_candidate_sha=result_candidate_sha if isinstance(result_candidate_sha, str) else None,
    )
    validate(current_queue)
    return current_queue, successor_id


def release_execution_failure(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    code: str,
    now: datetime,
) -> dict[str, Any]:
    if not isinstance(code, str) or not code or code in {"PASS", "FAIL", "INDETERMINATE"}:
        raise MinimalCoreError("execution error code is invalid")
    current_queue = deepcopy(queue)
    validate(current_queue)
    task = _task(current_queue, task_id)
    if task.get("status") != STATUS_EXECUTING or task.get("claim", {}).get("run_id") != run_id:
        raise MinimalCoreError("execution failure does not own current claim")
    task.update({
        "status": STATUS_QUEUED,
        "outcome": None,
        "result_ref": None,
        "terminal_run_id": None,
        "claim": None,
        "last_execution_error": code,
        "updated_at": _ts(now),
    })
    validate(current_queue)
    return current_queue


def reconcile(
    queue: Mapping[str, Any],
    *,
    persisted_results: Mapping[tuple[str, str], tuple[Mapping[str, Any] | None, str]] | None = None,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Expire lost authority first; only current claims may finalize persisted results."""
    current_queue = deepcopy(queue)
    validate(current_queue)
    report = {"finalized_results": [], "expired_claims": []}
    persisted_results = persisted_results or {}

    for task in list(current_queue["tasks"]):
        if task.get("lifecycle_model") != PROTOCOL_ID or task.get("status") != STATUS_EXECUTING:
            continue
        run_id = task["claim"]["run_id"]
        if _parse_ts(task["claim"]["expires_at"]) <= _utc(now):
            current_queue = release_execution_failure(
                current_queue,
                task_id=task["task_id"],
                run_id=run_id,
                code="LEASE_EXPIRED",
                now=now,
            )
            report["expired_claims"].append(task["task_id"])
            continue

        entry = persisted_results.get((task["task_id"], run_id))
        if entry is None:
            continue
        result, result_ref = entry
        try:
            if not isinstance(result, Mapping):
                raise MinimalCoreError("persisted result must be an object")
            current_queue, _ = finalize_result(
                current_queue,
                task_id=task["task_id"],
                result=result,
                result_ref=result_ref,
                now=now,
            )
        except MinimalCoreError:
            current_queue = release_execution_failure(
                current_queue,
                task_id=task["task_id"],
                run_id=run_id,
                code="INVALID_PERSISTED_RESULT",
                now=now,
            )
            continue
        report["finalized_results"].append(task["task_id"])

    validate(current_queue)
    return current_queue, report


def explain_task(queue: Mapping[str, Any], task_id: str) -> dict[str, Any]:
    validate(queue)
    task = _task(queue, task_id)
    if task.get("lifecycle_model") != PROTOCOL_ID:
        raise MinimalCoreError("task is not Minimal Core V1")
    claim_data = task.get("claim") or {}
    return {
        "task_id": task["task_id"],
        "operation": task["operation"],
        "role": task["role"],
        "status": task["status"],
        "outcome": task.get("outcome"),
        "repository": task["repository"],
        "candidate_sha": task.get("candidate_sha"),
        "run_id": claim_data.get("run_id") or task.get("terminal_run_id"),
        "lease_expires_at": claim_data.get("expires_at"),
        "result_ref": task.get("result_ref"),
        "last_execution_error": task.get("last_execution_error"),
    }
