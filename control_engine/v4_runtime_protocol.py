from __future__ import annotations

"""Pure protocol helpers for the bounded Control V4 runtime carrier.

The Scheduled Runner is the semantic actor. This module accepts only narrow typed
commands/events and computes validated queue transitions. It owns no network,
credential, scheduler, target-repository or private-state I/O capability.
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from control_engine.v4_contracts import (
    finish_passed_review_v4,
    validate_queue_v4,
)


RESULT_PROTOCOL_ID = "CONTROL_V4_RUNTIME_RESULT_V1"
TICK_PREFIX = "CONTROL_V4_RUNTIME_TICK "
EVENT_PREFIX = "CONTROL_V4_RUNTIME_EVENT "
TICK_NEWLINE_PREFIX = "CONTROL_V4_RUNTIME_TICK\n"
EVENT_NEWLINE_PREFIX = "CONTROL_V4_RUNTIME_EVENT\n"
PENDING_DRIFT_BLOCKER = "MISSION_REVISION_DISCIPLINE_VIOLATION_PENDING"
CANONICAL_RUNNER_PROMPT_BLOB_SHA = "6cd83f6c687ae2b8cf437add85c798bfb95f28f3"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ACTION_RE = re.compile(r"^[A-Z0-9_]{1,96}$")
EVENTS = {
    "YIELD",
    "CANDIDATE_READY",
    "INTERNAL_PASS",
    "INTERNAL_REPAIR",
    "EXTERNAL_REQUESTED",
    "EXTERNAL_FINDING",
    "EXTERNAL_PASS",
    "REVIEW_UNAVAILABLE",
}
FORBIDDEN_PUBLIC_KEYS = {
    "task_id",
    "gap_id",
    "mission_id",
    "mission_revision",
    "acceptance",
    "mission_contract_blob_sha",
    "repository_authority_blob_sha",
    "last_review",
    "external_review",
    "blocker",
    "migration_facts",
    "execution_lock",
    "lock_expires_at",
    "queue",
    "missions",
    "authorities",
}


class RuntimeProtocolError(ValueError):
    pass


class StaleEventError(RuntimeProtocolError):
    pass


class _DuplicateKeyError(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError(key)
        value[key] = item
    return value


def strict_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, _DuplicateKeyError, TypeError, ValueError) as exc:
        raise RuntimeProtocolError("JSON invalid or ambiguous") from exc
    if not isinstance(value, dict):
        raise RuntimeProtocolError("JSON root must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], allowed: set[str], required: set[str]) -> None:
    keys = set(value)
    if not required.issubset(keys) or not keys.issubset(allowed):
        raise RuntimeProtocolError("command fields invalid")


def _run_id(value: object) -> str:
    if not isinstance(value, str) or RUN_ID_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("run_id invalid")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or SHA1_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("SHA identity invalid")
    return value


def _token(value: object) -> str:
    if not isinstance(value, str) or TOKEN_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("task token invalid")
    return value


def _repo(value: object) -> str:
    if not isinstance(value, str) or REPOSITORY_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("repository invalid")
    return value


def _branch(value: object) -> str:
    if not isinstance(value, str) or BRANCH_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("branch invalid")
    return value


def _action(value: object) -> str:
    if not isinstance(value, str) or ACTION_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("action invalid")
    return value


def _candidate(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeProtocolError("candidate invalid")
    _exact_keys(
        value,
        {"candidate_sha", "candidate_pr_number", "candidate_head_branch", "expected_base_branch", "expected_base_sha"},
        {"candidate_sha", "candidate_pr_number", "candidate_head_branch", "expected_base_branch", "expected_base_sha"},
    )
    pr_number = value["candidate_pr_number"]
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise RuntimeProtocolError("candidate PR invalid")
    return {
        "candidate_sha": _sha(value["candidate_sha"]),
        "candidate_pr_number": pr_number,
        "candidate_head_branch": _branch(value["candidate_head_branch"]),
        "expected_base_branch": _branch(value["expected_base_branch"]),
        "expected_base_sha": _sha(value["expected_base_sha"]),
    }


def parse_public_command(text: str) -> dict[str, Any]:
    prefix = None
    for candidate_prefix in (TICK_PREFIX, TICK_NEWLINE_PREFIX, EVENT_PREFIX, EVENT_NEWLINE_PREFIX):
        if text.startswith(candidate_prefix):
            prefix = candidate_prefix
            break
    if prefix is None:
        raise RuntimeProtocolError("command prefix invalid")
    payload = strict_json_object(text[len(prefix):])
    if prefix in (TICK_PREFIX, TICK_NEWLINE_PREFIX):
        _exact_keys(payload, {"run_id", "yielded_task_tokens"}, {"run_id", "yielded_task_tokens"})
        tokens = payload["yielded_task_tokens"]
        if not isinstance(tokens, list) or len(tokens) != len(set(tokens)):
            raise RuntimeProtocolError("yielded tokens invalid")
        return {
            "kind": "TICK",
            "run_id": _run_id(payload["run_id"]),
            "yielded_task_tokens": [_token(token) for token in tokens],
        }

    allowed = {
        "run_id", "task_token", "event", "repository", "action", "candidate",
        "new_candidate_sha", "candidate_pr_number", "candidate_head_branch",
        "new_expected_base_branch", "new_expected_base_sha", "request_ref", "evidence_ref",
    }
    required = {"run_id", "task_token", "event", "repository", "action"}
    _exact_keys(payload, allowed, required)
    event = payload["event"]
    if event not in EVENTS:
        raise RuntimeProtocolError("event invalid")
    result: dict[str, Any] = {
        "kind": "EVENT",
        "run_id": _run_id(payload["run_id"]),
        "task_token": _token(payload["task_token"]),
        "event": event,
        "repository": _repo(payload["repository"]),
        "action": _action(payload["action"]),
    }
    if "candidate" in payload:
        result["candidate"] = _candidate(payload["candidate"])

    event_fields = {
        "YIELD": set(),
        "INTERNAL_PASS": set(),
        "INTERNAL_REPAIR": set(),
        "REVIEW_UNAVAILABLE": set(),
        "CANDIDATE_READY": {"new_candidate_sha", "candidate_pr_number", "candidate_head_branch", "new_expected_base_branch", "new_expected_base_sha"},
        "EXTERNAL_REQUESTED": {"request_ref"},
        "EXTERNAL_FINDING": {"evidence_ref"},
        "EXTERNAL_PASS": {"evidence_ref"},
    }
    extras = set(payload) - required - ({"candidate"} if "candidate" in payload else set())
    if extras != event_fields[event]:
        raise RuntimeProtocolError("event fields invalid")
    if event == "CANDIDATE_READY":
        pr_number = payload["candidate_pr_number"]
        if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
            raise RuntimeProtocolError("candidate PR invalid")
        result.update(
            new_candidate_sha=_sha(payload["new_candidate_sha"]),
            candidate_pr_number=pr_number,
            candidate_head_branch=_branch(payload["candidate_head_branch"]),
            new_expected_base_branch=_branch(payload["new_expected_base_branch"]),
            new_expected_base_sha=_sha(payload["new_expected_base_sha"]),
        )
    elif event == "EXTERNAL_REQUESTED":
        if not isinstance(payload["request_ref"], str) or not payload["request_ref"]:
            raise RuntimeProtocolError("request ref invalid")
        result["request_ref"] = payload["request_ref"]
    elif event in {"EXTERNAL_FINDING", "EXTERNAL_PASS"}:
        if not isinstance(payload["evidence_ref"], str) or not payload["evidence_ref"]:
            raise RuntimeProtocolError("evidence ref invalid")
        result["evidence_ref"] = payload["evidence_ref"]
    return result


def task_token(task: Mapping[str, Any], run_id: str) -> str:
    payload = f"{run_id}\n{task['task_id']}\n{task['mission_contract_blob_sha']}\n{task['repository_authority_blob_sha']}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_by_token(queue: Mapping[str, Any], run_id: str, token: str) -> Mapping[str, Any]:
    matches = [task for task in queue.get("tasks", []) if task_token(task, run_id) == token]
    if len(matches) != 1:
        raise StaleEventError("task token not current")
    return matches[0]


def _public_candidate(task: Mapping[str, Any]) -> dict[str, Any] | None:
    value = task.get("candidate")
    if not isinstance(value, Mapping):
        return None
    return {
        "candidate_sha": value["candidate_sha"],
        "candidate_pr_number": value["candidate_pr_number"],
        "candidate_head_branch": value["candidate_head_branch"],
        "expected_base_branch": value["expected_base_branch"],
        "expected_base_sha": value["expected_base_sha"],
    }


def _action_for_task(task: Mapping[str, Any]) -> str:
    phase = task.get("phase")
    if phase == "BUILD":
        return "BUILD"
    if phase == "REPAIR":
        return "REPAIR"
    if phase == "REVIEW":
        review_policy = task.get("review_policy")
        last_review = task.get("last_review")
        external_review = task.get("external_review")
        if review_policy == "INTERNAL":
            return "REVIEW_INTERNAL"
        if not isinstance(last_review, Mapping) or last_review.get("verdict") != "PASS":
            return "REVIEW_INTERNAL"
        if isinstance(external_review, Mapping) and external_review.get("status") == "PENDING":
            return "AWAIT_EXTERNAL_REVIEW"
        return "REQUEST_EXTERNAL_REVIEW"
    if phase == "INTEGRATE":
        return "INTEGRATE"
    if phase == "CONVERGE":
        return "CONVERGE"
    raise RuntimeProtocolError("task phase unsupported")


def safe_work_capsule(
    queue: Mapping[str, Any], *, task_id: str, run_id: str, live_candidate: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    task = next((item for item in queue.get("tasks", []) if item.get("task_id") == task_id), None)
    if not isinstance(task, Mapping):
        raise RuntimeProtocolError("task missing")
    capsule: dict[str, Any] = {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "WORK",
        "run_id": run_id,
        "task_token": task_token(task, run_id),
        "action": _action_for_task(task),
        "repository": task["repository"],
    }
    candidate = _public_candidate(task)
    if candidate is not None:
        capsule["candidate"] = candidate
    if live_candidate is not None:
        capsule["live_candidate"] = _candidate(live_candidate)
    return capsule


def bind_public_event_to_holder(queue: Mapping[str, Any], event: Mapping[str, Any]) -> dict[str, Any]:
    if event.get("kind") != "EVENT":
        raise RuntimeProtocolError("event kind invalid")
    task = _task_by_token(queue, event["run_id"], event["task_token"])
    if event["repository"] != task["repository"]:
        raise StaleEventError("event repository stale")
    if event["action"] != _action_for_task(task):
        raise StaleEventError("event action stale")
    task_candidate = _public_candidate(task)
    event_candidate = event.get("candidate")
    if task_candidate is None:
        if event_candidate is not None:
            raise StaleEventError("event candidate stale")
    elif event_candidate != task_candidate:
        raise StaleEventError("event candidate stale")
    return {**event, "task_id": task["task_id"]}


def assert_event_identity(queue: Mapping[str, Any], event: Mapping[str, Any], *, now: datetime) -> None:
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping):
        raise StaleEventError("event has no current holder")
    if lock.get("run_id") != event.get("run_id") or lock.get("task_id") != event.get("task_id"):
        raise StaleEventError("event holder stale")
    expires_at = datetime.fromisoformat(lock["expires_at"].replace("Z", "+00:00"))
    if expires_at <= now.astimezone(timezone.utc):
        raise StaleEventError("event lease expired")


def _same_candidate(task: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    current = task.get("candidate")
    return isinstance(current, Mapping) and all(current.get(key) == candidate.get(key) for key in (
        "candidate_sha", "candidate_pr_number", "candidate_head_branch", "expected_base_branch", "expected_base_sha"
    ))


def reconcile_review_candidate_drift_v4(
    queue: Mapping[str, Any], *, task_id: str, run_id: str, live_candidate: Mapping[str, Any], now: datetime
) -> tuple[dict[str, Any], bool]:
    task = next((item for item in queue.get("tasks", []) if item.get("task_id") == task_id), None)
    if not isinstance(task, Mapping):
        raise RuntimeProtocolError("task missing")
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW":
        return deepcopy(queue), False
    normalized = _candidate(live_candidate)
    if _same_candidate(task, normalized):
        return deepcopy(queue), False
    next_queue = deepcopy(queue)
    next_task = next(item for item in next_queue["tasks"] if item["task_id"] == task_id)
    next_task["phase"] = "REPAIR"
    next_task["candidate"] = normalized
    next_task["last_review"] = None
    next_task["external_review"] = None
    next_task["blocker"] = None
    next_task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    validate_queue_v4(next_queue)
    return next_queue, True


def block_holder_v4(queue: Mapping[str, Any], *, task_id: str, run_id: str, blocker: str, now: datetime) -> dict[str, Any]:
    next_queue = deepcopy(queue)
    assert_event_identity(next_queue, {"run_id": run_id, "task_id": task_id}, now=now)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == task_id)
    task["status"] = "BLOCKED"
    task["blocker"] = blocker
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    next_queue["execution_lock"] = None
    validate_queue_v4(next_queue)
    return next_queue


def yield_holder_v4(queue: Mapping[str, Any], event: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    next_queue = deepcopy(queue)
    next_queue["execution_lock"] = None
    validate_queue_v4(next_queue)
    return next_queue


def candidate_ready_v4(
    queue: Mapping[str, Any], event: Mapping[str, Any], *, verified_candidate: Mapping[str, Any], now: datetime
) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    normalized = _candidate(verified_candidate)
    expected = {
        "candidate_sha": event["new_candidate_sha"],
        "candidate_pr_number": event["candidate_pr_number"],
        "candidate_head_branch": event["candidate_head_branch"],
        "expected_base_branch": event["new_expected_base_branch"],
        "expected_base_sha": event["new_expected_base_sha"],
    }
    if normalized != expected:
        raise StaleEventError("candidate ready verification mismatch")
    next_queue = deepcopy(queue)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == event["task_id"])
    task["candidate"] = normalized
    task["phase"] = "REVIEW"
    task["last_review"] = None
    task["external_review"] = None
    task["blocker"] = None
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    validate_queue_v4(next_queue)
    return next_queue


def _review_identity(task: Mapping[str, Any], verdict: str, now: datetime) -> dict[str, Any]:
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("review task has no candidate")
    return {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "verdict": verdict,
        "reviewed_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def internal_review_v4(
    queue: Mapping[str, Any], event: Mapping[str, Any], *, verdict: str, now: datetime,
    control_runtime_enabled: bool, integration_enabled: bool,
) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    if verdict not in {"PASS", "REPAIR_REQUIRED"}:
        raise RuntimeProtocolError("review verdict invalid")
    next_queue = deepcopy(queue)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == event["task_id"])
    task["last_review"] = _review_identity(task, verdict, now)
    task["external_review"] = None
    task["blocker"] = None
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if verdict == "REPAIR_REQUIRED":
        task["phase"] = "REPAIR"
    elif task["review_policy"] == "INTERNAL":
        task = finish_passed_review_v4(
            task, now=now, control_runtime_enabled=control_runtime_enabled, integration_enabled=integration_enabled
        )
        next_queue["tasks"] = [task if item["task_id"] == task["task_id"] else item for item in next_queue["tasks"]]
    validate_queue_v4(next_queue)
    return next_queue


def _external_request_key(task: Mapping[str, Any]) -> str:
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("external review task has no candidate")
    return f"{task['gap_id']}--{candidate['candidate_sha']}--{candidate['expected_base_branch']}--{candidate['expected_base_sha']}"


def external_requested_v4(queue: Mapping[str, Any], event: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    next_queue = deepcopy(queue)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == event["task_id"])
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("external review task has no candidate")
    task["external_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "request_key": _external_request_key(task),
        "status": "PENDING",
        "request_ref": event["request_ref"],
        "evidence_ref": None,
    }
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    validate_queue_v4(next_queue)
    return next_queue


def external_finding_v4(queue: Mapping[str, Any], event: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    next_queue = deepcopy(queue)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == event["task_id"])
    external = task.get("external_review")
    if not isinstance(external, Mapping) or external.get("status") != "PENDING" or external.get("request_key") != _external_request_key(task):
        raise StaleEventError("external review request stale")
    task["external_review"] = {**external, "status": "FINDING", "evidence_ref": event["evidence_ref"]}
    task["phase"] = "REPAIR"
    task["blocker"] = None
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    validate_queue_v4(next_queue)
    return next_queue


def external_pass_v4(
    queue: Mapping[str, Any], event: Mapping[str, Any], *, now: datetime,
    control_runtime_enabled: bool, integration_enabled: bool,
) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    next_queue = deepcopy(queue)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == event["task_id"])
    external = task.get("external_review")
    if not isinstance(external, Mapping) or external.get("status") != "PENDING" or external.get("request_key") != _external_request_key(task):
        raise StaleEventError("external review request stale")
    task["external_review"] = {**external, "status": "PASS", "evidence_ref": event["evidence_ref"]}
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    task = finish_passed_review_v4(
        task, now=now, control_runtime_enabled=control_runtime_enabled, integration_enabled=integration_enabled
    )
    next_queue["tasks"] = [task if item["task_id"] == task["task_id"] else item for item in next_queue["tasks"]]
    validate_queue_v4(next_queue)
    return next_queue


def external_unavailable_v4(queue: Mapping[str, Any], event: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    assert_event_identity(queue, event, now=now)
    next_queue = deepcopy(queue)
    task = next(item for item in next_queue["tasks"] if item["task_id"] == event["task_id"])
    external = task.get("external_review")
    if not isinstance(external, Mapping) or external.get("request_key") != _external_request_key(task):
        raise StaleEventError("external review request stale")
    task["external_review"] = {**external, "status": "INDETERMINATE", "evidence_ref": None}
    task["updated_at"] = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    validate_queue_v4(next_queue)
    return next_queue


def recover_expired_lock_v4(queue: Mapping[str, Any], *, now: datetime) -> tuple[dict[str, Any], bool]:
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping):
        return deepcopy(queue), False
    expires_at = datetime.fromisoformat(lock["expires_at"].replace("Z", "+00:00"))
    if expires_at > now.astimezone(timezone.utc):
        return deepcopy(queue), False
    next_queue = deepcopy(queue)
    next_queue["execution_lock"] = None
    validate_queue_v4(next_queue)
    return next_queue, True


def select_task_id_v4(
    queue: Mapping[str, Any], *, run_id: str, yielded_task_tokens: Sequence[str], integration_enabled: bool
) -> str | None:
    yielded = set(yielded_task_tokens)
    tasks = list(queue.get("tasks", []))

    def available(task: Mapping[str, Any]) -> bool:
        if task_token(task, run_id) in yielded:
            return False
        status = task.get("status")
        phase = task.get("phase")
        if status == "READY":
            return integration_enabled and task.get("integration_policy") == "AUTO"
        if status != "ACTIVE":
            return False
        if phase in {"INTEGRATE", "CONVERGE"}:
            return integration_enabled
        return phase in {"BUILD", "REPAIR", "REVIEW"}

    eligible = [task for task in tasks if available(task)]
    if not eligible:
        return None

    def priority(task: Mapping[str, Any]) -> tuple[int, int]:
        external = task.get("external_review")
        is_retryable_external_wait = (
            task.get("phase") == "REVIEW"
            and isinstance(external, Mapping)
            and external.get("status") == "INDETERMINATE"
        )
        if is_retryable_external_wait:
            return (4, tasks.index(task))
        if task.get("status") == "ACTIVE":
            return (0, tasks.index(task))
        if task.get("status") == "READY":
            return (1, tasks.index(task))
        return (3, tasks.index(task))

    return min(eligible, key=priority)["task_id"]


def compact_public_result(result: Mapping[str, Any]) -> str:
    if not isinstance(result, Mapping):
        raise RuntimeProtocolError("result invalid")
    if any(key in result for key in FORBIDDEN_PUBLIC_KEYS):
        raise RuntimeProtocolError("private field leak")
    return json.dumps(dict(result), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
