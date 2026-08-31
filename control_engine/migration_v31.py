from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from control_engine import kernel_v31 as core

LEGACY_QUEUE_VERSION = "1.0"
MIGRATION_PROTOCOL_ID = "CONTROL_V3_1_MIGRATION_FACT"
MIGRATION_FACT = "LEGACY_PROJECT_INTEGRATION_COMPLETED"


class MigrationError(ValueError):
    pass


def _ts(value: datetime) -> str:
    if value.tzinfo is None:
        raise MigrationError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _identity_component(value: object, *, label: str) -> str:
    try:
        return core._identity_component(value)
    except core.KernelError as exc:
        raise MigrationError(f"{label} is invalid") from exc


def _current_gap_authority(missions: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    authorities: dict[tuple[str, str, str], dict[str, Any]] = {}
    for wrapped in missions:
        mission = wrapped.get("mission")
        if not isinstance(mission, Mapping):
            raise MigrationError("wrapped Mission is invalid")
        mission_id = _identity_component(mission.get("mission_id"), label="Mission identity")
        revision = _identity_component(mission.get("mission_revision"), label="Mission revision")
        repository = mission.get("repository")
        gaps = mission.get("gaps")
        if not isinstance(repository, str) or not repository or not isinstance(gaps, list):
            raise MigrationError("Mission identity is invalid")
        for gap in gaps:
            if not isinstance(gap, Mapping) or gap.get("gap_state") != "OPEN":
                continue
            gap_id = _identity_component(gap.get("gap_id"), label="Mission gap identity")
            identity = (mission_id, revision, gap_id)
            if identity in authorities:
                raise MigrationError("duplicate current Mission gap identity")
            authorities[identity] = {
                "mission_id": mission_id,
                "mission_revision": revision,
                "gap_id": gap_id,
                "repository": repository,
            }
    return authorities


def _completed_legacy_integration(task: Mapping[str, Any]) -> bool:
    return (
        task.get("lifecycle_model") != core.PROTOCOL_ID
        and task.get("operation") == "PROJECT_INTEGRATION"
        and task.get("status") == "TERMINAL"
        and task.get("outcome") == "COMPLETED"
        and isinstance(task.get("task_id"), str)
        and bool(task.get("task_id"))
        and isinstance(task.get("result_ref"), str)
        and bool(task.get("result_ref"))
    )


def _legacy_task_index(tasks: list[Any]) -> dict[str, Mapping[str, Any]]:
    index: dict[str, Mapping[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            continue
        if task_id in index:
            raise MigrationError("legacy task identity is not unique")
        index[task_id] = task
    return index


def _explicit_legacy_identity(task: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    values = (
        task.get("mission_id"),
        task.get("mission_revision"),
        task.get("mission_gap_id", task.get("gap_id")),
    )
    if all(value is None for value in values):
        return None
    if not all(isinstance(value, str) and value for value in values):
        return None
    try:
        mission_id = core._identity_component(values[0])
        revision = core._identity_component(values[1])
        gap_id = core._identity_component(values[2])
    except core.KernelError:
        return None
    repository = task.get("repository")
    if not isinstance(repository, str) or not repository:
        return None
    return mission_id, revision, gap_id, repository


def _legacy_predecessor_identity(
    task: Mapping[str, Any], task_index: Mapping[str, Mapping[str, Any]]
) -> tuple[str, str, str, str] | None:
    """Follow only explicit predecessor links; never parse ambiguous V1 task IDs."""
    current = task
    visited: set[str] = set()
    for _ in range(len(task_index) + 1):
        explicit = _explicit_legacy_identity(current)
        if explicit is not None:
            return explicit
        task_id = current.get("task_id")
        if not isinstance(task_id, str) or task_id in visited:
            return None
        visited.add(task_id)
        predecessor = current.get("predecessor_task_id")
        if not isinstance(predecessor, str) or not predecessor:
            return None
        next_task = task_index.get(predecessor)
        if next_task is None:
            return None
        current = next_task
    return None


def _validate_fact(fact: Mapping[str, Any]) -> None:
    required = {
        "protocol_id",
        "fact",
        "mission_id",
        "mission_revision",
        "gap_id",
        "repository",
        "source_task_id",
        "source_result_ref",
        "imported_at",
        "principal_manual_relay_count",
    }
    if set(fact) != required:
        raise MigrationError("migration fact fields are not exact")
    if fact.get("protocol_id") != MIGRATION_PROTOCOL_ID or fact.get("fact") != MIGRATION_FACT:
        raise MigrationError("migration fact protocol is invalid")
    for key in ("mission_id", "mission_revision", "gap_id", "repository", "source_task_id", "source_result_ref", "imported_at"):
        if not isinstance(fact.get(key), str) or not fact[key]:
            raise MigrationError(f"migration fact {key} is invalid")
    for key in ("mission_id", "mission_revision", "gap_id"):
        _identity_component(fact[key], label=f"migration fact {key}")
    relay = fact.get("principal_manual_relay_count")
    if not isinstance(relay, int) or isinstance(relay, bool) or relay != 0:
        raise MigrationError("migration fact manual relay count must remain integer zero")


def validate_migration_facts(queue: Mapping[str, Any]) -> None:
    facts = queue.get("migration_facts", [])
    if not isinstance(facts, list):
        raise MigrationError("migration_facts must be a list")
    identities: set[tuple[str, str, str]] = set()
    for fact in facts:
        if not isinstance(fact, Mapping):
            raise MigrationError("migration fact must be an object")
        _validate_fact(fact)
        identity = (fact["mission_id"], fact["mission_revision"], fact["gap_id"])
        if identity in identities:
            raise MigrationError("duplicate migration fact identity")
        identities.add(identity)


def migrate(queue: Mapping[str, Any], *, missions: Iterable[Mapping[str, Any]], now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One-time V1→V3.1 convergence using only explicit legacy identity evidence.

    A terminal COMPLETED PROJECT_INTEGRATION becomes an inert satisfaction fact
    only when its predecessor chain contains explicit mission_id,
    mission_revision and mission_gap_id/gap_id metadata matching a currently
    governed OPEN gap. Ambiguous V1 task-ID text is never parsed as authority.
    Unsupported or unverifiable legacy evidence is dropped rather than promoted.
    """
    version = queue.get("version")
    if version == "3.1":
        q = deepcopy(queue)
        core.validate(q)
        validate_migration_facts(q)
        return q, []
    if version != LEGACY_QUEUE_VERSION:
        raise MigrationError("unsupported queue version for V3.1 migration")

    tasks = queue.get("tasks")
    relay = queue.get("principal_manual_relay_count")
    if not isinstance(tasks, list) or not isinstance(relay, int) or isinstance(relay, bool) or relay != 0:
        raise MigrationError("legacy queue is not safely importable")

    authorities = _current_gap_authority(missions)
    task_index = _legacy_task_index(tasks)
    facts_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
    imported_at = _ts(now)
    for task in tasks:
        if not isinstance(task, Mapping) or not _completed_legacy_integration(task):
            continue
        explicit = _legacy_predecessor_identity(task, task_index)
        if explicit is None:
            continue
        mission_id, revision, gap_id, legacy_repository = explicit
        identity = (mission_id, revision, gap_id)
        authority = authorities.get(identity)
        if authority is None:
            continue
        repository = task.get("repository")
        if repository != legacy_repository or repository != authority["repository"]:
            continue
        fact = {
            "protocol_id": MIGRATION_PROTOCOL_ID,
            "fact": MIGRATION_FACT,
            **authority,
            "source_task_id": task["task_id"],
            "source_result_ref": task["result_ref"],
            "imported_at": imported_at,
            "principal_manual_relay_count": 0,
        }
        prior = facts_by_identity.get(identity)
        if prior is None or (fact["source_task_id"], fact["source_result_ref"]) < (prior["source_task_id"], prior["source_result_ref"]):
            facts_by_identity[identity] = fact

    facts = [facts_by_identity[key] for key in sorted(facts_by_identity)]
    q = {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": facts,
        "tasks": [],
    }
    core.validate(q)
    validate_migration_facts(q)
    return q, deepcopy(facts)


def gap_satisfied_by_fact(queue: Mapping[str, Any], mission_id: str, revision: str, gap_id: str) -> bool:
    validate_migration_facts(queue)
    return any(
        fact["mission_id"] == mission_id
        and fact["mission_revision"] == revision
        and fact["gap_id"] == gap_id
        for fact in queue.get("migration_facts", [])
    )


def feed(queue: Mapping[str, Any], *, missions: Iterable[Mapping[str, Any]], now: datetime) -> tuple[dict[str, Any], list[str]]:
    """Run pure Feed with ephemeral shadows for validated inert migration facts."""
    q = deepcopy(queue)
    core.validate(q)
    validate_migration_facts(q)
    shadows: list[dict[str, Any]] = []
    for fact in q.get("migration_facts", []):
        shadows.append({
            "task_id": core.deterministic_root_id(fact["mission_id"], fact["mission_revision"], fact["gap_id"]),
            "operation": "PROJECT_INTEGRATION",
            "status": "TERMINAL",
            "outcome": "COMPLETED",
            "_migration_shadow": True,
        })
    q["tasks"].extend(shadows)
    fed, created = core.feed(q, missions=missions, now=now)
    fed["tasks"] = [task for task in fed.get("tasks", []) if not task.get("_migration_shadow")]
    core.validate(fed)
    validate_migration_facts(fed)
    return fed, created
