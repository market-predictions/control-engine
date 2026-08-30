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


def _current_gap_prefixes(missions: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    prefixes: dict[str, dict[str, Any]] = {}
    for wrapped in missions:
        mission = wrapped.get("mission")
        if not isinstance(mission, Mapping):
            raise MigrationError("wrapped Mission is invalid")
        mission_id = mission.get("mission_id")
        revision = mission.get("mission_revision")
        repository = mission.get("repository")
        gaps = mission.get("gaps")
        if not all(isinstance(v, str) and v for v in (mission_id, revision, repository)) or not isinstance(gaps, list):
            raise MigrationError("Mission identity is invalid")
        for gap in gaps:
            if not isinstance(gap, Mapping) or gap.get("gap_state") != "OPEN":
                continue
            gap_id = gap.get("gap_id")
            if not isinstance(gap_id, str) or not gap_id:
                raise MigrationError("Mission gap identity is invalid")
            prefix = core.deterministic_root_id(mission_id, revision, gap_id)
            if prefix in prefixes:
                raise MigrationError("duplicate deterministic Mission gap identity")
            prefixes[prefix] = {
                "mission_id": mission_id,
                "mission_revision": revision,
                "gap_id": gap_id,
                "repository": repository,
            }
    return prefixes


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


def _matches_legacy_root(task_id: str, root_id: str) -> bool:
    return task_id == root_id or task_id.startswith(root_id + "--")


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
    """One-time V1→V3.1 convergence.

    Only the exact supported V1 queue format is migratable. A legacy terminal
    COMPLETED PROJECT_INTEGRATION for a gap in a current governed Mission
    revision becomes an inert satisfaction fact. No legacy task object survives
    in the active queue. BLOCKED/PASS/EXECUTING/QUEUED evidence remains only in
    Git history and is never upgraded into V3.1 authority.
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

    prefixes = _current_gap_prefixes(missions)
    facts_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
    imported_at = _ts(now)
    for task in tasks:
        if not isinstance(task, Mapping) or not _completed_legacy_integration(task):
            continue
        task_id = task["task_id"]
        matches = [
            (prefix, authority)
            for prefix, authority in prefixes.items()
            if _matches_legacy_root(task_id, prefix)
        ]
        if len(matches) != 1:
            continue
        _, authority = matches[0]
        identity = (authority["mission_id"], authority["mission_revision"], authority["gap_id"])
        fact = {
            "protocol_id": MIGRATION_PROTOCOL_ID,
            "fact": MIGRATION_FACT,
            **authority,
            "source_task_id": task_id,
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
    """Run the existing pure Feed with ephemeral shadows for inert migration facts.

    Each shadow uses the exact deterministic root id so Feed treats that migrated
    gap as already observed. It also has the legacy completed-integration shape
    so downstream dependencies see the fact as satisfied. Shadows exist only in
    memory and are removed before the queue is returned or persisted.
    """
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
