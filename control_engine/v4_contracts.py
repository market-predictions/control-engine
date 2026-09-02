from __future__ import annotations

"""Passive deterministic contracts for Control V4.

This module has no network, scheduler, merge, provider, or runtime-write capability.
It validates inert V4 data and provides pure transition/transform helpers for the
reviewed V3.1 -> V4 cutover and pre-V4-80 rollback path.
"""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaValidationError

from control_engine import kernel_v31


PUBLIC_ROOT = Path(__file__).resolve().parents[1]
MISSION_SCHEMA_REL = "schemas/mission_contract_v4.schema.json"
REPOSITORY_SCHEMA_REL = "schemas/repository_authority_v4.schema.json"
QUEUE_SCHEMA_REL = "schemas/dispatch_queue_v4.schema.json"
V4_VERSION = "4.0"
LEASE_SECONDS = 5400
PENDING_DRIFT_BLOCKER = "MISSION_REVISION_DISCIPLINE_VIOLATION_PENDING"
REVISION_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})-r(?P<sequence>[1-9]\d*)$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class V4ValidationError(ValueError):
    pass


def _schema(rel: str) -> dict[str, Any]:
    try:
        value = json.loads((PUBLIC_ROOT / rel).read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise V4ValidationError("trusted V4 schema unavailable") from exc
    if not isinstance(value, dict):
        raise V4ValidationError("trusted V4 schema root invalid")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise V4ValidationError("trusted V4 schema invalid") from exc
    return value


def _validate_schema(instance: Mapping[str, Any], rel: str) -> None:
    try:
        Draft202012Validator(_schema(rel)).validate(instance)
    except JsonSchemaValidationError as exc:
        raise V4ValidationError("document violates trusted V4 schema") from exc


def _zero(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def _sha1(value: object) -> bool:
    return isinstance(value, str) and SHA1_RE.fullmatch(value) is not None


def _parse_ts(value: object) -> datetime:
    if not isinstance(value, str):
        raise V4ValidationError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise V4ValidationError("timestamp invalid") from exc
    if parsed.tzinfo is None:
        raise V4ValidationError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        raise V4ValidationError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def revision_key(value: object) -> tuple[int, date]:
    if not isinstance(value, str):
        raise V4ValidationError("Mission revision invalid")
    match = REVISION_RE.fullmatch(value)
    if match is None:
        raise V4ValidationError("Mission revision invalid")
    try:
        day = date.fromisoformat(match.group("day"))
    except ValueError as exc:
        raise V4ValidationError("Mission revision invalid") from exc
    return int(match.group("sequence")), day


def revision_strictly_precedes(source: object, target: object) -> bool:
    source_sequence, source_day = revision_key(source)
    target_sequence, target_day = revision_key(target)
    return source_sequence < target_sequence and source_day <= target_day


def canonical_task_sha256(task: Mapping[str, Any]) -> str:
    encoded = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_acyclic(gaps: Sequence[Mapping[str, Any]]) -> None:
    graph = {str(gap["gap_id"]): list(gap.get("depends_on", [])) for gap in gaps}
    state: dict[str, int] = {}
    for start in graph:
        if state.get(start) == 2:
            continue
        state[start] = 1
        stack: list[tuple[str, Any]] = [(start, iter(graph[start]))]
        while stack:
            node, deps = stack[-1]
            try:
                dep = next(deps)
            except StopIteration:
                state[node] = 2
                stack.pop()
                continue
            if dep not in graph:
                raise V4ValidationError("unknown gap dependency")
            dep_state = state.get(dep, 0)
            if dep_state == 1:
                raise V4ValidationError("cyclic gap dependency")
            if dep_state == 0:
                state[dep] = 1
                stack.append((dep, iter(graph[dep])))


def validate_mission_v4(mission: Mapping[str, Any]) -> None:
    _validate_schema(mission, MISSION_SCHEMA_REL)
    if not _zero(mission.get("principal_manual_relay_count")):
        raise V4ValidationError("Mission relay count must be exact integer zero")
    revision_key(mission.get("mission_revision"))

    gaps = list(mission["gaps"])
    gap_ids = [gap["gap_id"] for gap in gaps]
    if len(gap_ids) != len(set(gap_ids)):
        raise V4ValidationError("Mission gap identity duplicated")
    gap_by_id = {gap["gap_id"]: gap for gap in gaps}
    for gap in gaps:
        if gap["repository"].lower() != mission["repository"].lower():
            raise V4ValidationError("gap repository differs from Mission repository")
        if any(dep not in gap_by_id for dep in gap["depends_on"]):
            raise V4ValidationError("gap dependency invalid")
    _assert_acyclic(gaps)

    carry = list(mission.get("done_carry_forward", []))
    target_ids = [item["target_gap_id"] for item in carry]
    if len(target_ids) != len(set(target_ids)):
        raise V4ValidationError("carry-forward target duplicated")
    carry_by_target = {item["target_gap_id"]: item for item in carry}
    for item in carry:
        target = gap_by_id.get(item["target_gap_id"])
        if target is None:
            raise V4ValidationError("carry-forward target gap missing")
        if target["gap_state"] != "RETIRED":
            raise V4ValidationError("carry-forward target must be RETIRED")
        if not revision_strictly_precedes(item["source_mission_revision"], mission["mission_revision"]):
            raise V4ValidationError("carry-forward source revision must strictly precede current revision")

    for gap in gaps:
        if gap["gap_state"] != "OPEN":
            continue
        for dep in gap["depends_on"]:
            if gap_by_id[dep]["gap_state"] == "RETIRED" and dep not in carry_by_target:
                raise V4ValidationError("OPEN dependency on RETIRED prerequisite lacks carry-forward")


def validate_repository_authority_v4(authority: Mapping[str, Any]) -> None:
    _validate_schema(authority, REPOSITORY_SCHEMA_REL)
    if not _zero(authority.get("principal_manual_relay_count")):
        raise V4ValidationError("repository authority relay count must be exact integer zero")


def validate_authority_set(
    missions: Sequence[Mapping[str, Any]], authorities: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    mission_by_id: dict[str, Mapping[str, Any]] = {}
    for mission in missions:
        validate_mission_v4(mission)
        mission_id = mission["mission_id"]
        if mission_id in mission_by_id:
            raise V4ValidationError("Mission identity duplicated")
        mission_by_id[mission_id] = mission

    authority_by_repo: dict[str, Mapping[str, Any]] = {}
    for authority in authorities:
        validate_repository_authority_v4(authority)
        repo_key = authority["repository"].lower()
        if repo_key in authority_by_repo:
            raise V4ValidationError("repository authority duplicated")
        authority_by_repo[repo_key] = authority

    for mission in missions:
        if mission["repository"].lower() not in authority_by_repo:
            raise V4ValidationError("Mission repository lacks V4 repository authority")
    return mission_by_id, authority_by_repo


def _review_matches_candidate(review: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return (
        review.get("candidate_sha") == candidate.get("candidate_sha")
        and review.get("expected_base_branch") == candidate.get("expected_base_branch")
        and review.get("expected_base_sha") == candidate.get("expected_base_sha")
    )


def _task_review_passed(task: Mapping[str, Any]) -> bool:
    candidate = task.get("candidate")
    review = task.get("last_review")
    if not isinstance(candidate, Mapping) or not isinstance(review, Mapping):
        return False
    if review.get("verdict") != "PASS" or not _review_matches_candidate(review, candidate):
        return False
    if task.get("review_policy") == "EXTERNAL":
        external = task.get("external_review")
        if not isinstance(external, Mapping):
            return False
        if external.get("status") != "PASS" or not _review_matches_candidate(external, candidate):
            return False
    return True


def validate_queue_v4(queue: Mapping[str, Any]) -> None:
    _validate_schema(queue, QUEUE_SCHEMA_REL)
    if queue.get("version") != V4_VERSION or not _zero(queue.get("principal_manual_relay_count")):
        raise V4ValidationError("V4 queue identity invalid")

    fact_keys: set[tuple[str, str, str]] = set()
    for fact in queue["migration_facts"]:
        if not _zero(fact.get("principal_manual_relay_count")):
            raise V4ValidationError("migration fact relay count must remain zero")
        key = (fact["mission_id"], fact["mission_revision"], fact["gap_id"])
        if key in fact_keys:
            raise V4ValidationError("migration fact identity duplicated")
        fact_keys.add(key)

    task_ids: set[str] = set()
    logical_ids: set[tuple[str, str, str]] = set()
    task_by_id: dict[str, Mapping[str, Any]] = {}
    for task in queue["tasks"]:
        task_id = task["task_id"]
        logical = (task["mission_id"], task["mission_revision"], task["gap_id"])
        if task_id in task_ids or logical in logical_ids:
            raise V4ValidationError("V4 task identity duplicated")
        task_ids.add(task_id)
        logical_ids.add(logical)
        task_by_id[task_id] = task
        _parse_ts(task["created_at"])
        _parse_ts(task["updated_at"])

        candidate = task.get("candidate")
        review = task.get("last_review")
        external = task.get("external_review")
        if candidate is None and (review is not None or external is not None):
            raise V4ValidationError("review evidence exists without candidate")
        if isinstance(review, Mapping) and (not isinstance(candidate, Mapping) or not _review_matches_candidate(review, candidate)):
            raise V4ValidationError("internal review candidate/base identity is stale")
        if isinstance(external, Mapping) and (not isinstance(candidate, Mapping) or not _review_matches_candidate(external, candidate)):
            raise V4ValidationError("external review candidate/base identity is stale")

        if task.get("blocker") == PENDING_DRIFT_BLOCKER:
            if task.get("status") != "ACTIVE" or task.get("phase") != "REVIEW":
                raise V4ValidationError("pending Mission-drift marker requires ACTIVE/REVIEW")

        if task.get("status") in {"READY", "DONE"} and not _task_review_passed(task):
            raise V4ValidationError("READY/DONE task lacks exact PASS evidence")
        if task.get("status") == "ACTIVE" and task.get("phase") in {"INTEGRATE", "CONVERGE"} and not _task_review_passed(task):
            raise V4ValidationError("integration/convergence task lacks exact PASS evidence")

    lock = queue.get("execution_lock")
    if lock is not None:
        started = _parse_ts(lock["started_at"])
        expires = _parse_ts(lock["expires_at"])
        if expires - started != timedelta(seconds=LEASE_SECONDS):
            raise V4ValidationError("V4 lock lease must be exactly 5400 seconds")
        holder = task_by_id.get(lock["task_id"])
        if holder is None or holder.get("status") != "ACTIVE":
            raise V4ValidationError("execution lock must identify one ACTIVE task")


def validate_carry_forward_evidence(mission: Mapping[str, Any], queue: Mapping[str, Any]) -> None:
    validate_mission_v4(mission)
    validate_queue_v4(queue)
    gaps = {gap["gap_id"]: gap for gap in mission["gaps"]}

    for item in mission.get("done_carry_forward", []):
        target_repo = gaps[item["target_gap_id"]]["repository"].lower()
        if item["source_fact_kind"] == "MIGRATION_FACT":
            matches = [
                fact for fact in queue["migration_facts"]
                if fact["mission_id"] == mission["mission_id"]
                and fact["mission_revision"] == item["source_mission_revision"]
                and fact["gap_id"] == item["source_gap_id"]
                and fact["repository"].lower() == target_repo
                and fact["source_result_ref"] == item["source_fact_ref"]
            ]
            if len(matches) != 1:
                raise V4ValidationError("MIGRATION_FACT carry-forward evidence does not resolve exactly")
            continue

        matches = [
            task for task in queue["tasks"]
            if task["task_id"] == item["source_fact_ref"]
            and task["mission_id"] == mission["mission_id"]
            and task["mission_revision"] == item["source_mission_revision"]
            and task["gap_id"] == item["source_gap_id"]
            and task["repository"].lower() == target_repo
            and task["status"] == "DONE"
        ]
        if len(matches) != 1 or not _task_review_passed(matches[0]):
            raise V4ValidationError("V4_DONE carry-forward evidence does not resolve exactly")
        if canonical_task_sha256(matches[0]) != item.get("source_task_sha256"):
            raise V4ValidationError("V4_DONE carry-forward digest mismatch")


def _task(queue: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    matches = [task for task in queue["tasks"] if task["task_id"] == task_id]
    if len(matches) != 1:
        raise V4ValidationError("task identity does not resolve exactly")
    return matches[0]


def _assert_holder(queue: Mapping[str, Any], task_id: str, run_id: str, now: datetime) -> None:
    validate_queue_v4(queue)
    lock = queue.get("execution_lock")
    if not isinstance(lock, Mapping):
        raise V4ValidationError("current execution lock absent")
    if lock.get("task_id") != task_id or lock.get("run_id") != run_id:
        raise V4ValidationError("current execution lock identity mismatch")
    if _parse_ts(lock.get("expires_at")) <= now.astimezone(timezone.utc):
        raise V4ValidationError("current execution lock expired")


def acquire_task_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    now: datetime,
    control_runtime_enabled: bool,
    integration_enabled: bool,
    ready_drift_reconciliation: bool = False,
) -> dict[str, Any]:
    """Pure model of the single allowed atomic acquisition CAS."""
    validate_queue_v4(queue)
    if control_runtime_enabled is not True:
        raise V4ValidationError("protected runtime disabled: acquisition forbidden")
    if queue.get("execution_lock") is not None:
        raise V4ValidationError("execution lock already present")
    if now.tzinfo is None:
        raise V4ValidationError("acquisition time must be timezone-aware")

    q = deepcopy(queue)
    task = next((item for item in q["tasks"] if item["task_id"] == task_id), None)
    if task is None:
        raise V4ValidationError("selected task missing")

    status = task["status"]
    if status == "QUEUED":
        task["status"] = "ACTIVE"
        task["phase"] = "BUILD"
    elif status == "ACTIVE":
        pass
    elif status == "READY" and ready_drift_reconciliation:
        task["status"] = "ACTIVE"
        task["phase"] = "REVIEW"
        task["blocker"] = PENDING_DRIFT_BLOCKER
    elif status == "READY" and task["integration_policy"] == "AUTO_AFTER_PASS" and integration_enabled is True:
        task["status"] = "ACTIVE"
        task["phase"] = "INTEGRATE"
    else:
        raise V4ValidationError("selected task is not eligible for atomic acquisition")

    task["updated_at"] = _ts(now)
    q["execution_lock"] = {
        "run_id": run_id,
        "task_id": task_id,
        "started_at": _ts(now),
        "expires_at": _ts(now + timedelta(seconds=LEASE_SECONDS)),
    }
    validate_queue_v4(q)
    return q


def finish_passed_review_v4(
    queue: Mapping[str, Any],
    *,
    task_id: str,
    run_id: str,
    now: datetime,
    control_runtime_enabled: bool,
    integration_enabled: bool,
) -> dict[str, Any]:
    """Pure holder-fenced transition after all required review evidence is PASS."""
    if control_runtime_enabled is not True:
        raise V4ValidationError("protected runtime disabled: semantic transition forbidden")
    if now.tzinfo is None:
        raise V4ValidationError("review time must be timezone-aware")
    _assert_holder(queue, task_id, run_id, now)

    q = deepcopy(queue)
    task = next(item for item in q["tasks"] if item["task_id"] == task_id)
    if task["status"] != "ACTIVE" or task["phase"] != "REVIEW":
        raise V4ValidationError("passed-review transition requires ACTIVE/REVIEW")
    if task.get("blocker") == PENDING_DRIFT_BLOCKER:
        raise V4ValidationError("ordinary REVIEW forbidden while drift reconciliation is pending")
    candidate = task.get("candidate")
    if not isinstance(candidate, Mapping):
        raise V4ValidationError("passed review requires exact candidate")
    task["last_review"] = {
        "candidate_sha": candidate["candidate_sha"],
        "expected_base_branch": candidate["expected_base_branch"],
        "expected_base_sha": candidate["expected_base_sha"],
        "verdict": "PASS",
        "reviewed_at": _ts(now),
    }
    if task["review_policy"] == "EXTERNAL":
        external = task.get("external_review")
        if (
            not isinstance(external, Mapping)
            or external.get("status") != "PASS"
            or not _review_matches_candidate(external, candidate)
        ):
            raise V4ValidationError("EXTERNAL review policy requires exact candidate/base external PASS")

    if task["integration_policy"] == "HOLD_AFTER_PASS" or integration_enabled is False:
        task["status"] = "READY"
        task["phase"] = None
        task["updated_at"] = _ts(now)
        q["execution_lock"] = None
    else:
        task["status"] = "ACTIVE"
        task["phase"] = "INTEGRATE"
        task["updated_at"] = _ts(now)

    validate_queue_v4(q)
    return q


def v4_root_task_id(mission_id: str, revision: str, gap_id: str) -> str:
    for value in (mission_id, revision, gap_id):
        if not isinstance(value, str) or not value or "--" in value or "\n" in value or "\r" in value:
            raise V4ValidationError("task identity component invalid")
    return "--".join(("MISSION", mission_id, revision, gap_id))


def forward_transform_v31_to_v4(
    v31_queue: Mapping[str, Any],
    *,
    missions: Sequence[Mapping[str, Any]],
    mission_blob_shas: Mapping[str, str],
    authorities: Sequence[Mapping[str, Any]],
    authority_blob_shas: Mapping[str, str],
    transformed_at: datetime,
) -> dict[str, Any]:
    """Transform the exact fenced V3.1 queue into one validated V4 queue.

    This bounded transform deliberately supports the cutover shape that is proven
    at V4-30: no live claims and only queued IMPLEMENTATION roots. Any material
    input drift fails closed and must be reviewed instead of guessed through.
    """
    if v31_queue.get("version") != "3.1" or not _zero(v31_queue.get("principal_manual_relay_count")):
        raise V4ValidationError("source queue is not canonical V3.1")
    try:
        kernel_v31.validate(v31_queue)
    except kernel_v31.KernelError as exc:
        raise V4ValidationError("source V3.1 queue invalid") from exc
    if transformed_at.tzinfo is None:
        raise V4ValidationError("transform time must be timezone-aware")

    mission_by_id, authority_by_repo = validate_authority_set(missions, authorities)
    for mission_id, mission in mission_by_id.items():
        if not _sha1(mission_blob_shas.get(mission_id)):
            raise V4ValidationError("Mission blob SHA missing or invalid")
        repo = mission["repository"].lower()
        if not _sha1(authority_blob_shas.get(repo)):
            raise V4ValidationError("repository-authority blob SHA missing or invalid")
        if repo not in authority_by_repo:
            raise V4ValidationError("repository authority missing")

    source_tasks: dict[tuple[str, str], Mapping[str, Any]] = {}
    for task in v31_queue.get("tasks", []):
        if task.get("lifecycle_model") != kernel_v31.PROTOCOL_ID:
            raise V4ValidationError("non-V3.1 task present at fenced cutover")
        if task.get("status") == kernel_v31.STATUS_EXECUTING or task.get("claim") is not None:
            raise V4ValidationError("live V3.1 claim present at cutover")
        if task.get("status") in {kernel_v31.STATUS_TERMINAL, kernel_v31.STATUS_SUPERSEDED}:
            continue
        if task.get("status") != kernel_v31.STATUS_QUEUED or task.get("operation") != "IMPLEMENTATION":
            raise V4ValidationError("cutover input differs from reviewed queued-implementation shape")
        key = (task.get("mission_id"), task.get("gap_id"))
        if not all(isinstance(part, str) and part for part in key) or key in source_tasks:
            raise V4ValidationError("source logical task identity invalid or duplicated")
        source_tasks[key] = task

    v4_tasks: list[dict[str, Any]] = []
    for (mission_id, gap_id), source in sorted(source_tasks.items()):
        mission = mission_by_id.get(mission_id)
        if mission is None:
            raise V4ValidationError("source task Mission missing from V4 authority")
        gap_matches = [gap for gap in mission["gaps"] if gap["gap_id"] == gap_id]
        if len(gap_matches) != 1:
            raise V4ValidationError("source task gap missing from V4 Mission")
        gap = gap_matches[0]
        if gap["gap_state"] == "RETIRED":
            carry = [item for item in mission.get("done_carry_forward", []) if item["target_gap_id"] == gap_id]
            if len(carry) != 1:
                raise V4ValidationError("queued V3.1 work cannot disappear into unproven RETIRED target")
            continue
        repo_key = mission["repository"].lower()
        v4_tasks.append({
            "task_id": v4_root_task_id(mission_id, mission["mission_revision"], gap_id),
            "mission_id": mission_id,
            "mission_revision": mission["mission_revision"],
            "mission_contract_blob_sha": mission_blob_shas[mission_id],
            "repository_authority_blob_sha": authority_blob_shas[repo_key],
            "gap_id": gap_id,
            "repository": gap["repository"],
            "acceptance": deepcopy(gap["acceptance"]),
            "integration_policy": gap["integration_policy"],
            "review_policy": gap["review_policy"],
            "convergence_required": bool(gap.get("convergence_required", False)),
            "status": "QUEUED",
            "phase": "BUILD",
            "candidate": None,
            "last_review": None,
            "external_review": None,
            "blocker": None,
            "created_at": source.get("created_at", _ts(transformed_at)),
            "updated_at": _ts(transformed_at),
        })

    output = {
        "version": V4_VERSION,
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": deepcopy(v31_queue.get("migration_facts", [])),
        "tasks": v4_tasks,
    }
    validate_queue_v4(output)
    for mission in missions:
        validate_carry_forward_evidence(mission, output)
    return output


def derive_satisfied_gap_ids(
    pre_v31_queue: Mapping[str, Any], v4_queue: Mapping[str, Any]
) -> dict[str, set[str]]:
    """Derive only completion that the canonical queues can prove exactly.

    If a consequential V4 effect landed but is not yet reconciled into canonical
    V4 DONE state, the rollback procedure must reconcile that fact first. This
    function never guesses from repository similarity or stale status.
    """
    try:
        kernel_v31.validate(pre_v31_queue)
    except kernel_v31.KernelError as exc:
        raise V4ValidationError("pre-cutover V3.1 queue invalid") from exc
    validate_queue_v4(v4_queue)

    satisfied: dict[str, set[str]] = {}
    for fact in pre_v31_queue.get("migration_facts", []):
        if fact.get("protocol_id") != "CONTROL_V3_1_MIGRATION_FACT" or fact.get("fact") != "LEGACY_PROJECT_INTEGRATION_COMPLETED":
            raise V4ValidationError("unsupported pre-cutover migration fact")
        satisfied.setdefault(fact["mission_id"], set()).add(fact["gap_id"])
    for task in v4_queue["tasks"]:
        if task["status"] != "DONE":
            continue
        if not _task_review_passed(task):
            raise V4ValidationError("V4 DONE task lacks exact review evidence")
        satisfied.setdefault(task["mission_id"], set()).add(task["gap_id"])
    return satisfied


def derive_rollback_missions_v31(
    pre_cutover_missions: Sequence[Mapping[str, Any]],
    *,
    satisfied_gap_ids: Mapping[str, Iterable[str]],
    rollback_revisions: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Derive dependency-live V3.1 rollback Missions from frozen V3.1 truth."""
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in pre_cutover_missions:
        if source.get("protocol_id") != "MISSION_CONTRACT_V3_1":
            raise V4ValidationError("rollback source Mission is not V3.1")
        mission_id = source.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id or mission_id in seen:
            raise V4ValidationError("rollback Mission identity invalid or duplicated")
        seen.add(mission_id)
        new_revision = rollback_revisions.get(mission_id)
        if not isinstance(new_revision, str) or not revision_strictly_precedes(source.get("mission_revision"), new_revision):
            raise V4ValidationError("rollback Mission revision must move forward monotonically")
        ids = {gap["gap_id"] for gap in source.get("gaps", [])}
        satisfied = set(satisfied_gap_ids.get(mission_id, ()))
        if not satisfied.issubset(ids):
            raise V4ValidationError("satisfied gap does not exist in frozen Mission")

        mission = deepcopy(source)
        old_revision = mission["mission_revision"]
        mission["mission_revision"] = new_revision
        mission["supersedes_revision"] = old_revision
        for gap in mission["gaps"]:
            if gap["gap_id"] in satisfied:
                gap["gap_state"] = "RETIRED"
            else:
                gap["gap_state"] = "OPEN"
                gap["depends_on"] = [dep for dep in gap.get("depends_on", []) if dep not in satisfied]
                if any(dep not in ids for dep in gap["depends_on"]):
                    raise V4ValidationError("rollback dependency unknown")
        output.append(mission)
    return output


def build_rollback_v31_queue(
    pre_v31_queue: Mapping[str, Any],
    v4_queue: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce V3.1-valid rollback queue evidence without synthetic V3.1 results.

    Stale nonterminal pre-cutover tasks are omitted. Exact terminal/result facts
    that were already valid before cutover may remain. Unfinished work is later
    materialized by canonical V3.1 FEED under the reviewed rollback Missions.
    """
    try:
        kernel_v31.validate(pre_v31_queue)
    except kernel_v31.KernelError as exc:
        raise V4ValidationError("pre-cutover V3.1 queue invalid") from exc
    validate_queue_v4(v4_queue)
    if v4_queue.get("execution_lock") is not None:
        raise V4ValidationError("rollback queue replacement requires no live V4 holder")

    preserved_terminal = [
        deepcopy(task) for task in pre_v31_queue.get("tasks", [])
        if task.get("lifecycle_model") == kernel_v31.PROTOCOL_ID
        and task.get("status") == kernel_v31.STATUS_TERMINAL
    ]
    output = {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": deepcopy(pre_v31_queue.get("migration_facts", [])),
        "tasks": preserved_terminal,
    }
    try:
        kernel_v31.validate(output)
    except kernel_v31.KernelError as exc:
        raise V4ValidationError("derived rollback queue is not V3.1-valid") from exc
    return output


def derive_rollback_v31(
    *,
    pre_v31_queue: Mapping[str, Any],
    v4_queue: Mapping[str, Any],
    pre_cutover_missions: Sequence[Mapping[str, Any]],
    rollback_revisions: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, set[str]]]:
    satisfied = derive_satisfied_gap_ids(pre_v31_queue, v4_queue)
    missions = derive_rollback_missions_v31(
        pre_cutover_missions,
        satisfied_gap_ids=satisfied,
        rollback_revisions=rollback_revisions,
    )
    queue = build_rollback_v31_queue(pre_v31_queue, v4_queue)
    return missions, queue, satisfied