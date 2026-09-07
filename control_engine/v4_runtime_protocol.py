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
PENDING_DRIFT_BLOCKER = "MISSION_REVISION_DISCIPLINE_VIOLATION_PENDING"
CANONICAL_RUNNER_PROMPT_BLOB_SHA = "f354539a6493bce9269d77fe085300ac4a0c9fa6"
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


def _branch(value: object) -> str:
    if not isinstance(value, str) or BRANCH_RE.fullmatch(value) is None or ".." in value:
        raise RuntimeProtocolError("branch identity invalid")
    return value


def _repository(value: object) -> str:
    if not isinstance(value, str) or REPOSITORY_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("repository identity invalid")
    return value


def _action(value: object) -> str:
    if not isinstance(value, str) or ACTION_RE.fullmatch(value) is None:
        raise RuntimeProtocolError("action identity invalid")
    return value


def _candidate(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeProtocolError("candidate identity invalid")
    candidate = dict(value)
    required = {
        "candidate_sha",
        "candidate_pr_number",
        "candidate_head_branch",
        "expected_base_branch",
        "expected_base_sha",
    }
    _exact_keys(candidate, required, required)
    candidate["candidate_sha"] = _sha(candidate["candidate_sha"])
    number = candidate["candidate_pr_number"]
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise RuntimeProtocolError("candidate PR number invalid")
    candidate["candidate_head_branch"] = _branch(candidate["candidate_head_branch"])
    candidate["expected_base_branch"] = _branch(candidate["expected_base_branch"])
    candidate["expected_base_sha"] = _sha(candidate["expected_base_sha"])
    return candidate


def _public_ref(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("https://github.com/") or len(value) > 500:
        raise RuntimeProtocolError("public evidence reference invalid")
    if any(c in value for c in "\r\n\t"):
        raise RuntimeProtocolError("public evidence reference invalid")
    return value


def parse_public_command(comment_body: str) -> dict[str, Any]:
    if not isinstance(comment_body, str):
        raise RuntimeProtocolError("comment body invalid")
    if comment_body.startswith(TICK_PREFIX):
        payload = strict_json_object(comment_body[len(TICK_PREFIX):])
        _exact_keys(payload, {"run_id", "yielded_task_tokens"}, {"run_id"})
        run_id = _run_id(payload["run_id"])
        yielded = payload.get("yielded_task_tokens", [])
        if not isinstance(yielded, list) or len(yielded) > 100:
            raise RuntimeProtocolError("yielded task tokens invalid")
        clean: list[str] = []
        for item in yielded:
            token = _token(item)
            if token in clean:
                raise RuntimeProtocolError("yielded task token duplicated")
            clean.append(token)
        return {"kind": "TICK", "run_id": run_id, "yielded_task_tokens": clean}

    if comment_body.startswith(EVENT_PREFIX):
        payload = strict_json_object(comment_body[len(EVENT_PREFIX):])
        common = {"run_id", "task_token", "event", "repository", "action", "candidate"}
        event = payload.get("event")
        if event not in EVENTS:
            raise RuntimeProtocolError("event invalid")
        event_fields: dict[str, set[str]] = {
            "YIELD": set(),
            "INTERNAL_PASS": set(),
            "INTERNAL_REPAIR": set(),
            "REVIEW_UNAVAILABLE": set(),
            "CANDIDATE_READY": {
                "new_candidate_sha",
                "candidate_pr_number",
                "candidate_head_branch",
                "new_expected_base_branch",
                "new_expected_base_sha",
            },
            "EXTERNAL_REQUESTED": {"request_ref"},
            "EXTERNAL_FINDING": {"evidence_ref"},
            "EXTERNAL_PASS": {"evidence_ref"},
        }
        required = {"run_id", "task_token", "event", "repository", "action"} | event_fields[event]
        allowed = common | event_fields[event]
        _exact_keys(payload, allowed, required)
        payload["run_id"] = _run_id(payload["run_id"])
        payload["task_token"] = _token(payload["task_token"])
        payload["repository"] = _repository(payload["repository"])
        payload["action"] = _action(payload["action"])
        if "candidate" in payload:
            payload["candidate"] = _candidate(payload["candidate"])

        if event == "CANDIDATE_READY":
            payload["new_candidate_sha"] = _sha(payload["new_candidate_sha"])
            number = payload["candidate_pr_number"]
            if not isinstance(number, int) or isinstance(number, bool) or number < 1:
                raise RuntimeProtocolError("candidate PR number invalid")
            payload["candidate_head_branch"] = _branch(payload["candidate_head_branch"])
            payload["new_expected_base_branch"] = _branch(payload["new_expected_base_branch"])
            payload["new_expected_base_sha"] = _sha(payload["new_expected_base_sha"])
        elif event == "EXTERNAL_REQUESTED":
            payload["request_ref"] = _public_ref(payload["request_ref"])
        elif event in {"EXTERNAL_FINDING", "EXTERNAL_PASS"}:
            payload["evidence_ref"] = _public_ref(payload["evidence_ref"])
        return {"kind": "EVENT", **payload}

    raise RuntimeProtocolError("unsupported public command")


def validate_runtime_binding(
    authority: Mapping[str, Any],
    runner_config: Mapping[str, Any],
    prompt_text: str,
    *,
    runner_config_blob_sha: str,
    prompt_blob_sha: str,
) -> tuple[bool, bool]:
    if authority.get("protocol_id") != "CONTROL_RUNTIME_AUTHORITY_V4":
        raise RuntimeProtocolError("runtime authority identity invalid")
    if authority.get("principal_manual_relay_count") != 0:
        raise RuntimeProtocolError("runtime authority relay invalid")
    runtime_enabled = authority.get("control_runtime_enabled")
    integration_enabled = authority.get("integration_enabled")
    if not isinstance(runtime_enabled, bool) or not isinstance(integration_enabled, bool):
        raise RuntimeProtocolError("runtime switches invalid")
    if authority.get("runner_config_path") != "control/CONTROL_RUNNER_V4.json":
        raise RuntimeProtocolError("runner config path invalid")
    if authority.get("runner_config_blob_sha") != _sha(runner_config_blob_sha):
        raise RuntimeProtocolError("runner config blob binding invalid")
    if runner_config.get("protocol_id") != "CONTROL_RUNNER_V4" or runner_config.get("runner_id") != "CONTROL_V4_RUNNER":
        raise RuntimeProtocolError("runner config identity invalid")
    if runner_config.get("execution_surface") != "CHATGPT_SCHEDULED":
        raise RuntimeProtocolError("runner execution surface invalid")
    if runner_config.get("automation_object_binding_status") != "BOUND":
        raise RuntimeProtocolError("runner automation binding invalid")
    if runner_config.get("principal_manual_relay_count") != 0:
        raise RuntimeProtocolError("runner relay invalid")
    if runner_config.get("prompt_path") != "control/CONTROL_RUNNER_V4_PROMPT.md":
        raise RuntimeProtocolError("runner prompt path invalid")
    bound_prompt_blob_sha = _sha(prompt_blob_sha)
    if runner_config.get("prompt_blob_sha") != bound_prompt_blob_sha:
        raise RuntimeProtocolError("runner prompt blob binding invalid")
    if bound_prompt_blob_sha != CANONICAL_RUNNER_PROMPT_BLOB_SHA:
        raise RuntimeProtocolError("runner prompt wire contract is not current")
    required_markers = (
        "document_id=CONTROL_RUNNER_V4_PROMPT",
        "status=ACTIVE_BOUND",
        "architecture=CONTROL_AUTONOMY_ARCHITECTURE_V4",
        "source_of_truth=GITHUB",
        "principal_manual_relay_target=0",
    )
    if not isinstance(prompt_text, str) or any(marker not in prompt_text for marker in required_markers):
        raise RuntimeProtocolError("runner prompt identity invalid")
    return runtime_enabled, integration_enabled


def _utc(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise RuntimeProtocolError("current time invalid")
    return now.astimezone(timezone.utc)


def _ts(now: datetime) -> str:
    return _utc(now).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str):
        raise RuntimeProtocolError("timestamp invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeProtocolError("timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise RuntimeProtocolError("timestamp invalid")
    return parsed.astimezone(timezone.utc)


def _task(queue: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    matches = [item for item in queue["tasks"] if item["task_id"] == task_id]
    if len(matches) != 1:
        raise RuntimeProtocolError("task identity does not resolve exactly")
    return matches[0]


def task_token(task: Mapping[str, Any], run_id: str) -> str:
    material = "\0".join((
        _run_id(run_id),
        str(task["task_id"]),
        str(task["mission_contract_blob_sha"]),
        str(task["repository_authority_blob_sha"]),
    )).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _work_action(task: Mapping[str, Any]) -> str:
    phase = task.get("phase")
    action = phase
    if phase == "REVIEW":
        if task.get("review_policy") == "INTERNAL" or not _review_passed(task):
            action = "REVIEW_INTERNAL"
        else:
            external = task.get("external_review")
            action = "REQUEST_EXTERNAL_REVIEW" if not isinstance(external, Mapping) or external.get("request_ref") is None else "RECONCILE_EXTERNAL_REVIEW"
    elif phase == "INTEGRATE":
        action = "INTEGRATION_UNSUPPORTED_BY_CARRIER_V1"
    elif phase == "CONVERGE":
        action = "CONVERGENCE_UNSUPPORTED_BY_CARRIER_V1"
    if not isinstance(action, str):
        raise RuntimeProtocolError("task action invalid")
    return action


def bind_public_event_to_holder(queue: Mapping[str, Any], command: Mapping[str, Any]) -> dict[str, Any]:
    validate_queue_v4(queue)
    matches = [task for task in queue["tasks"] if task_token(task, command["run_id"]) == command["task_token"]]
    if len(matches) != 1:
        raise StaleEventError("task token is stale or ambiguous")
    task = matches[0]
    if command.get("repository") != task.get("repository") or command.get("action") != _work_action(task):
        raise StaleEventError("event WORK identity is stale")
    candidate = task.get("candidate")
    expected_candidate = _candidate_identity(candidate) if isinstance(candidate, Mapping) else None
    observed_candidate = command.get("candidate")
    if expected_candidate is None:
        if observed_candidate is not None:
            raise StaleEventError("candidate-less WORK received candidate identity")
    elif observed_candidate != expected_candidate:
        raise StaleEventError("event candidate/base identity is stale")

    bound = {key: value for key, value in command.items() if key not in {"repository", "action", "candidate"}}
    bound["task_id"] = task["task_id"]
    if expected_candidate is not None:
        bound.update({
            "holder_candidate_sha": expected_candidate["candidate_sha"],
            "holder_expected_base_branch": expected_candidate["expected_base_branch"],
            "holder_expected_base_sha": expected_candidate["expected_base_sha"],
        })
    return bound


def assert_event_identity(queue: Mapping[str, Any], command: Mapping[str, Any], *, now: datetime) -> Mapping[str, Any]:
    validate_queue_v4(queue)
    task_id = command.get("task_id")
    run_id = command.get("run_id")
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping):
        raise StaleEventError("event has no current holder")
    if lock.get("task_id") != task_id or lock.get("run_id") != run_id:
        raise StaleEventError("event holder is stale")
    if _parse_ts(lock.get("expires_at")) <= _utc(now):
        raise StaleEventError("event lease expired")
    task = _task(queue, str(task_id))
    candidate = task.get("candidate")
    holder = (
        command.get("holder_candidate_sha"),
        command.get("holder_expected_base_branch"),
        command.get("holder_expected_base_sha"),
    )
    if isinstance(candidate, Mapping):
        expected = (
            candidate.get("candidate_sha"),
            candidate.get("expected_base_branch"),
            candidate.get("expected_base_sha"),
        )
        if holder != expected:
            raise StaleEventError("event candidate/base identity is stale")
    elif any(value is not None for value in holder):
        raise StaleEventError("candidate-less task received candidate identity")
    return task


def recover_expired_lock_v4(queue: Mapping[str, Any], *, now: datetime) -> tuple[dict[str, Any], bool]:
    validate_queue_v4(queue)
    q = deepcopy(queue)
    lock = q.get("execution_lock")
    if lock is None or _parse_ts(lock["expires_at"]) > _utc(now):
        return q, False
    q["execution_lock"] = None
    validate_queue_v4(q)
    return q, True


def _retryable_external_wait(task: Mapping[str, Any]) -> bool:
    external = task.get("external_review")
    return bool(
        task.get("status") == "ACTIVE"
        and task.get("phase") == "REVIEW"
        and task.get("review_policy") == "EXTERNAL"
        and isinstance(external, Mapping)
        and external.get("status") == "INDETERMINATE"
    )


def select_task_id_v4(
    queue: Mapping[str, Any],
    *,
    run_id: str,
    yielded_task_tokens: Sequence[str] = (),
    integration_enabled: bool,
) -> str | None:
    validate_queue_v4(queue)
    if queue.get("execution_lock") is not None:
        raise RuntimeProtocolError("selection requires no execution lock")
    yielded = set(yielded_task_tokens)

    def available(task: Mapping[str, Any]) -> bool:
        return task_token(task, run_id) not in yielded

    for task in queue["tasks"]:
        if available(task) and task["status"] == "ACTIVE" and not _retryable_external_wait(task):
            if task.get("phase") == "INTEGRATE" and integration_enabled is not True:
                continue
            return task["task_id"]
    if integration_enabled is True:
        for task in queue["tasks"]:
            if available(task) and task["status"] == "READY" and task["integration_policy"] == "AUTO_AFTER_PASS":
                return task["task_id"]
    for task in queue["tasks"]:
        if available(task) and task["status"] == "QUEUED":
            return task["task_id"]
    for task in queue["tasks"]:
        if available(task) and _retryable_external_wait(task):
            return task["task_id"]
    return None


def _holder_command(queue: Mapping[str, Any], *, task_id: str, run_id: str) -> dict[str, Any]:
    task = _task(queue, task_id)
    command: dict[str, Any] = {"task_id": task_id, "run_id": run_id}
    candidate = task.get("candidate")
    if isinstance(candidate, Mapping):
        command.update({
            "holder_candidate_sha": candidate["candidate_sha"],
            "holder_expected_base_branch": candidate["expected_base_branch"],
            "holder_expected_base_sha": candidate["expected_base_sha"],
        })
    return command


def reconcile_review_candidate_drift_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    live_candidate: Mapping[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], bool]:
    command = _holder_command(queue, task_id=task_id, run_id=run_id)
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW":
        return deepcopy(queue), False
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("REVIEW task lacks candidate")
    exact = all((
        live_candidate.get("candidate_sha") == candidate.get("candidate_sha"),
        live_candidate.get("candidate_head_branch") == candidate.get("candidate_head_branch"),
        live_candidate.get("expected_base_branch") == candidate.get("expected_base_branch"),
        live_candidate.get("expected_base_sha") == candidate.get("expected_base_sha"),
    ))
    if exact:
        return deepcopy(queue), False
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == task_id)
    changed["phase"] = "REPAIR"
    changed["blocker"] = None
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q, True


def candidate_ready_v4(
    queue: Mapping[str, Any],
    command: Mapping[str, Any],
    *,
    verified_candidate: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") not in {"BUILD", "REPAIR"}:
        raise RuntimeProtocolError("candidate-ready requires ACTIVE BUILD/REPAIR")
    expected = {
        "candidate_sha": command["new_candidate_sha"],
        "candidate_pr_number": command["candidate_pr_number"],
        "candidate_head_branch": command["candidate_head_branch"],
        "expected_base_branch": command["new_expected_base_branch"],
        "expected_base_sha": command["new_expected_base_sha"],
    }
    if dict(verified_candidate) != expected:
        raise StaleEventError("candidate-ready live identity mismatch")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == command["task_id"])
    changed["candidate"] = expected
    changed["last_review"] = None
    changed["external_review"] = None
    changed["blocker"] = None
    changed["status"] = "ACTIVE"
    changed["phase"] = "REVIEW"
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q


def _review_passed(task: Mapping[str, Any]) -> bool:
    candidate = task.get("candidate")
    review = task.get("last_review")
    return bool(
        isinstance(candidate, Mapping)
        and isinstance(review, Mapping)
        and review.get("verdict") == "PASS"
        and review.get("candidate_sha") == candidate.get("candidate_sha")
        and review.get("expected_base_branch") == candidate.get("expected_base_branch")
        and review.get("expected_base_sha") == candidate.get("expected_base_sha")
    )


def internal_review_v4(
    queue: Mapping[str, Any],
    command: Mapping[str, Any],
    *,
    verdict: str,
    now: datetime,
    control_runtime_enabled: bool,
    integration_enabled: bool,
) -> dict[str, Any]:
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW":
        raise RuntimeProtocolError("internal review requires ACTIVE/REVIEW")
    if task.get("blocker") == PENDING_DRIFT_BLOCKER:
        raise RuntimeProtocolError("ordinary review forbidden during Mission drift reconciliation")
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("internal review requires candidate")
    if verdict == "PASS" and task.get("review_policy") == "INTERNAL":
        return finish_passed_review_v4(
            queue,
            task_id=command["task_id"],
            run_id=command["run_id"],
            now=now,
            control_runtime_enabled=control_runtime_enabled,
            integration_enabled=integration_enabled,
        )
    if verdict not in {"PASS", "REPAIR_REQUIRED"}:
        raise RuntimeProtocolError("internal verdict invalid")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == command["task_id"])
    changed["last_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "verdict": verdict,
        "reviewed_at": _ts(now),
    }
    if verdict == "REPAIR_REQUIRED":
        changed["phase"] = "REPAIR"
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q


def _request_key(task: Mapping[str, Any]) -> str:
    candidate = task["candidate"]
    return "--".join((task["gap_id"], candidate["candidate_sha"], candidate["expected_base_branch"], candidate["expected_base_sha"]))


def external_requested_v4(queue: Mapping[str, Any], command: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW" or task.get("review_policy") != "EXTERNAL":
        raise RuntimeProtocolError("external-request requires EXTERNAL ACTIVE/REVIEW")
    if not _review_passed(task):
        raise RuntimeProtocolError("external request requires internal PASS")
    candidate = task["candidate"]
    existing = task.get("external_review")
    if isinstance(existing, Mapping) and existing.get("request_ref") not in {None, command["request_ref"]}:
        raise StaleEventError("external request already differs")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == command["task_id"])
    changed["external_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "request_key": _request_key(task),
        "status": "PENDING",
        "request_ref": command["request_ref"],
        "evidence_ref": None,
    }
    changed["updated_at"] = _ts(now)
    q["execution_lock"] = None
    validate_queue_v4(q)
    return q


def external_unavailable_v4(queue: Mapping[str, Any], command: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW" or task.get("review_policy") != "EXTERNAL":
        raise RuntimeProtocolError("review-unavailable requires EXTERNAL ACTIVE/REVIEW")
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("review-unavailable requires candidate")
    existing = task.get("external_review")
    if isinstance(existing, Mapping) and existing.get("status") in {"PASS", "FAIL"}:
        raise StaleEventError("terminal external evidence cannot be downgraded")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == command["task_id"])
    changed["external_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "request_key": existing.get("request_key") if isinstance(existing, Mapping) else _request_key(task),
        "status": "INDETERMINATE",
        "request_ref": existing.get("request_ref") if isinstance(existing, Mapping) else None,
        "evidence_ref": existing.get("evidence_ref") if isinstance(existing, Mapping) else None,
    }
    changed["updated_at"] = _ts(now)
    q["execution_lock"] = None
    validate_queue_v4(q)
    return q


def external_finding_v4(queue: Mapping[str, Any], command: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW" or task.get("review_policy") != "EXTERNAL":
        raise RuntimeProtocolError("external finding requires EXTERNAL ACTIVE/REVIEW")
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise RuntimeProtocolError("external finding requires candidate")
    existing = task.get("external_review")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == command["task_id"])
    changed["external_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "request_key": existing.get("request_key") if isinstance(existing, Mapping) else _request_key(task),
        "status": "FAIL",
        "request_ref": existing.get("request_ref") if isinstance(existing, Mapping) else None,
        "evidence_ref": command["evidence_ref"],
    }
    changed["status"] = "ACTIVE"
    changed["phase"] = "REPAIR"
    changed["blocker"] = None
    changed["updated_at"] = _ts(now)
    validate_queue_v4(q)
    return q


def external_pass_v4(
    queue: Mapping[str, Any],
    command: Mapping[str, Any],
    *,
    now: datetime,
    control_runtime_enabled: bool,
    integration_enabled: bool,
) -> dict[str, Any]:
    task = assert_event_identity(queue, command, now=now)
    if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW" or task.get("review_policy") != "EXTERNAL":
        raise RuntimeProtocolError("external PASS requires EXTERNAL ACTIVE/REVIEW")
    if not _review_passed(task):
        raise RuntimeProtocolError("external PASS requires internal PASS")
    candidate = task["candidate"]
    existing = task.get("external_review")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == command["task_id"])
    changed["external_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "request_key": existing.get("request_key") if isinstance(existing, Mapping) else _request_key(task),
        "status": "PASS",
        "request_ref": existing.get("request_ref") if isinstance(existing, Mapping) else None,
        "evidence_ref": command["evidence_ref"],
    }
    validate_queue_v4(q)
    return finish_passed_review_v4(
        q,
        task_id=command["task_id"],
        run_id=command["run_id"],
        now=now,
        control_runtime_enabled=control_runtime_enabled,
        integration_enabled=integration_enabled,
    )


def yield_holder_v4(queue: Mapping[str, Any], command: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    assert_event_identity(queue, command, now=now)
    q = deepcopy(queue)
    q["execution_lock"] = None
    validate_queue_v4(q)
    return q


def block_holder_v4(queue: Mapping[str, Any], *, task_id: str, run_id: str, blocker: str, now: datetime) -> dict[str, Any]:
    command = _holder_command(queue, task_id=task_id, run_id=run_id)
    assert_event_identity(queue, command, now=now)
    if not isinstance(blocker, str) or not blocker or len(blocker) > 200:
        raise RuntimeProtocolError("blocker invalid")
    q = deepcopy(queue)
    changed = next(item for item in q["tasks"] if item["task_id"] == task_id)
    changed["status"] = "BLOCKED"
    changed["phase"] = None
    changed["blocker"] = blocker
    changed["updated_at"] = _ts(now)
    q["execution_lock"] = None
    validate_queue_v4(q)
    return q


def _candidate_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_sha": candidate["candidate_sha"],
        "candidate_pr_number": candidate["candidate_pr_number"],
        "candidate_head_branch": candidate["candidate_head_branch"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
    }


def safe_work_capsule(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    live_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    validate_queue_v4(queue)
    task = _task(queue, task_id)
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping) or lock.get("task_id") != task_id or lock.get("run_id") != run_id:
        raise RuntimeProtocolError("safe capsule requires current holder")
    capsule: dict[str, Any] = {
        "protocol": RESULT_PROTOCOL_ID,
        "result": "WORK",
        "run_id": run_id,
        "task_token": task_token(task, run_id),
        "action": _work_action(task),
        "repository": task["repository"],
    }
    candidate = task.get("candidate")
    if isinstance(candidate, Mapping):
        capsule["candidate"] = _candidate_identity(candidate)
    if live_candidate is not None:
        capsule["live_candidate"] = dict(live_candidate)
    assert_public_safe(capsule)
    return capsule


def assert_public_safe(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in FORBIDDEN_PUBLIC_KEYS:
                raise RuntimeProtocolError("public capsule contains private-state key")
            assert_public_safe(item)
    elif isinstance(value, list):
        for item in value:
            assert_public_safe(item)


def compact_public_result(value: Mapping[str, Any]) -> str:
    assert_public_safe(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
