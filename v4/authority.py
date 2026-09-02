#!/usr/bin/env python3
"""Deterministic passive validation and migration helpers for Control V4.

This module reads local checkouts only. It has no GitHub mutation, runtime writer,
scheduler, provider, merge, deployment, delivery, or consequential authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

MISSION_SCHEMA = Path("schemas/mission_contract_v4.schema.json")
REPOSITORY_SCHEMA = Path("schemas/repository_authority_v4.schema.json")
QUEUE_SCHEMA = Path("schemas/dispatch_queue_v4.schema.json")
MISSION_DIR = Path("control/missions")
REPOSITORY_DIR = Path("control/repository-authority")
LEASE_SECONDS = 5400


class V4ValidationError(ValueError):
    """Raised when V4 authority or runtime data fails closed validation."""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def git_blob_sha_bytes(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def git_blob_sha(path: Path) -> str:
    return git_blob_sha_bytes(path.read_bytes())


def _parse_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise V4ValidationError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise V4ValidationError(f"timestamp must be timezone-aware: {value}")
    return parsed.astimezone(timezone.utc)


def _load_schema(schema_root: Path, relative: Path) -> dict[str, Any]:
    schema = load_json(schema_root / relative)
    Draft202012Validator.check_schema(schema)
    return schema


def _validate(instance: Any, schema: dict[str, Any], label: str) -> None:
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path))
    if not errors:
        return
    detail = "; ".join(
        f"{'.'.join(map(str, error.path)) or '<root>'}: {error.message}"
        for error in errors[:8]
    )
    raise V4ValidationError(f"{label}: {detail}")


def _convergence_required(gap: dict[str, Any]) -> bool:
    return bool(gap.get("convergence_required", False))


def _gap(mission: dict[str, Any], gap_id: str) -> dict[str, Any]:
    matches = [gap for gap in mission["gaps"] if gap["gap_id"] == gap_id]
    if len(matches) != 1:
        raise V4ValidationError(f"{mission['mission_id']}: expected exactly one gap {gap_id}")
    return matches[0]


def _validate_mission_graph(mission: dict[str, Any]) -> None:
    gaps = {gap["gap_id"]: gap for gap in mission["gaps"]}
    if len(gaps) != len(mission["gaps"]):
        raise V4ValidationError(f"{mission['mission_id']}: duplicate gap_id")

    for gap in gaps.values():
        dependencies = set(gap["depends_on"])
        unknown = dependencies - gaps.keys()
        if unknown:
            raise V4ValidationError(
                f"{mission['mission_id']}:{gap['gap_id']} unknown dependencies: {sorted(unknown)}"
            )
        if gap["gap_id"] in dependencies:
            raise V4ValidationError(f"{mission['mission_id']}:{gap['gap_id']} depends on itself")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(gap_id: str) -> None:
        if gap_id in visited:
            return
        if gap_id in visiting:
            raise V4ValidationError(f"{mission['mission_id']} dependency cycle at {gap_id}")
        visiting.add(gap_id)
        for dependency in gaps[gap_id]["depends_on"]:
            visit(dependency)
        visiting.remove(gap_id)
        visited.add(gap_id)

    for gap_id in sorted(gaps):
        visit(gap_id)


def load_v4_authority(
    authority_root: Path,
    *,
    schema_root: Path,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[str, str],
]:
    mission_schema = _load_schema(schema_root, MISSION_SCHEMA)
    repository_schema = _load_schema(schema_root, REPOSITORY_SCHEMA)

    missions: dict[str, dict[str, Any]] = {}
    mission_shas: dict[str, str] = {}
    repositories: dict[str, dict[str, Any]] = {}
    repository_shas: dict[str, str] = {}

    mission_paths = sorted((authority_root / MISSION_DIR).glob("*.mission.json"))
    repository_paths = sorted((authority_root / REPOSITORY_DIR).glob("*.json"))
    if not mission_paths or not repository_paths:
        raise V4ValidationError("V4 authority is incomplete")

    for path in mission_paths:
        mission = load_json(path)
        _validate(mission, mission_schema, str(path.relative_to(authority_root)))
        mission_id = mission["mission_id"]
        if mission_id in missions:
            raise V4ValidationError(f"duplicate mission_id: {mission_id}")
        _validate_mission_graph(mission)
        missions[mission_id] = mission
        mission_shas[mission_id] = git_blob_sha(path)

    for path in repository_paths:
        authority = load_json(path)
        _validate(authority, repository_schema, str(path.relative_to(authority_root)))
        repository = authority["repository"]
        if repository in repositories:
            raise V4ValidationError(f"duplicate repository authority: {repository}")
        repositories[repository] = authority
        repository_shas[repository] = git_blob_sha(path)

    for mission in missions.values():
        if mission["repository"] not in repositories:
            raise V4ValidationError(f"{mission['mission_id']}: missing repository authority")
        for gap in mission["gaps"]:
            if gap["repository"] not in repositories:
                raise V4ValidationError(
                    f"{mission['mission_id']}:{gap['gap_id']}: missing repository authority"
                )

    return missions, repositories, mission_shas, repository_shas


def validate_v4_queue(queue: dict[str, Any], authority_root: Path, *, schema_root: Path) -> None:
    _validate(queue, _load_schema(schema_root, QUEUE_SCHEMA), "V4 queue")
    missions, _, mission_shas, repository_shas = load_v4_authority(
        authority_root, schema_root=schema_root
    )

    task_ids: set[str] = set()
    logical_ids: set[tuple[str, str, str]] = set()
    carry_ids: set[tuple[str, str, str]] = set()

    for fact in queue["migration_facts"]:
        logical = (fact["mission_id"], fact["target_mission_revision"], fact["gap_id"])
        if logical in carry_ids:
            raise V4ValidationError(f"duplicate DONE_CARRY_FORWARD: {logical}")
        mission = missions.get(fact["mission_id"])
        if mission is None or mission["mission_revision"] != fact["target_mission_revision"]:
            raise V4ValidationError(f"carry-forward targets non-current mission: {logical}")
        _gap(mission, fact["gap_id"])
        carry_ids.add(logical)

    for task in queue["tasks"]:
        task_id = task["task_id"]
        if task_id in task_ids:
            raise V4ValidationError(f"duplicate task_id: {task_id}")
        task_ids.add(task_id)

        logical = (task["mission_id"], task["mission_revision"], task["gap_id"])
        if logical in logical_ids or logical in carry_ids:
            raise V4ValidationError(f"duplicate logical task/carry-forward identity: {logical}")
        logical_ids.add(logical)

        mission = missions.get(task["mission_id"])
        if mission is None or mission["mission_revision"] != task["mission_revision"]:
            raise V4ValidationError(f"task targets non-current mission: {logical}")
        gap = _gap(mission, task["gap_id"])
        if gap["gap_state"] != "OPEN":
            raise V4ValidationError(f"task targets retired gap: {logical}")

        expected = {
            "repository": gap["repository"],
            "acceptance": gap["acceptance"],
            "integration_policy": gap["integration_policy"],
            "review_policy": gap["review_policy"],
            "convergence_required": _convergence_required(gap),
            "mission_contract_blob_sha": mission_shas[task["mission_id"]],
            "repository_authority_blob_sha": repository_shas[gap["repository"]],
        }
        for field, expected_value in expected.items():
            if task[field] != expected_value:
                raise V4ValidationError(f"{field} drift: {logical}")

        status = task["status"]
        phase = task["phase"]
        if status == "QUEUED" and phase != "BUILD":
            raise V4ValidationError(f"QUEUED task must be BUILD: {logical}")
        if status == "ACTIVE" and phase not in {"BUILD", "REVIEW", "REPAIR", "INTEGRATE", "CONVERGE"}:
            raise V4ValidationError(f"ACTIVE task has invalid phase: {logical}")
        if status in {"READY", "BLOCKED", "DONE", "SUPERSEDED"} and phase is not None:
            raise V4ValidationError(f"{status} task must have null phase: {logical}")

        candidate = task["candidate"]
        for record_field in ("last_review", "external_review"):
            record = task[record_field]
            if record is not None:
                if candidate is None:
                    raise V4ValidationError(f"{record_field} exists without candidate: {logical}")
                if record["candidate_sha"] != candidate["candidate_sha"]:
                    raise V4ValidationError(f"{record_field} candidate drift: {logical}")

    lock = queue["execution_lock"]
    if lock is not None:
        started = _parse_time(lock["started_at"])
        expires = _parse_time(lock["expires_at"])
        if int((expires - started).total_seconds()) != LEASE_SECONDS:
            raise V4ValidationError("execution_lock lease must be exactly 5400 seconds")
        matches = [task for task in queue["tasks"] if task["task_id"] == lock["task_id"]]
        if len(matches) != 1 or matches[0]["status"] != "ACTIVE":
            raise V4ValidationError("execution_lock must reference exactly one ACTIVE task")


def forward_queue_v31_to_v4(
    old_queue: dict[str, Any],
    authority_root: Path,
    *,
    schema_root: Path,
) -> dict[str, Any]:
    """Deterministically transform only a quiescent V3.1 snapshot into V4 runtime data."""
    if old_queue.get("version") != "3.1" or old_queue.get("principal_manual_relay_count") != 0:
        raise V4ValidationError("forward transform requires V3.1 queue with relay 0")

    missions, _, mission_shas, repository_shas = load_v4_authority(
        authority_root, schema_root=schema_root
    )

    carry: list[dict[str, Any]] = []
    carry_keys: set[tuple[str, str, str]] = set()
    for fact in old_queue.get("migration_facts", []):
        if fact.get("fact") != "LEGACY_PROJECT_INTEGRATION_COMPLETED":
            raise V4ValidationError(f"unsupported V3.1 migration fact: {fact.get('fact')}")
        mission = missions.get(fact.get("mission_id"))
        if mission is None or mission.get("supersedes_revision") != fact.get("mission_revision"):
            raise V4ValidationError("legacy completion does not map to exact V4 Mission supersession")
        _gap(mission, fact["gap_id"])
        logical = (mission["mission_id"], mission["mission_revision"], fact["gap_id"])
        if logical in carry_keys:
            raise V4ValidationError(f"duplicate legacy completion: {logical}")
        carry_keys.add(logical)
        carry.append(
            {
                "fact": "DONE_CARRY_FORWARD",
                "mission_id": mission["mission_id"],
                "target_mission_revision": mission["mission_revision"],
                "gap_id": fact["gap_id"],
                "source_ref": fact["source_result_ref"],
            }
        )

    tasks: list[dict[str, Any]] = []
    for old_task in old_queue.get("tasks", []):
        forbidden_values = (
            old_task.get("claim"),
            old_task.get("outcome"),
            old_task.get("result_ref"),
            old_task.get("terminal_run_id"),
        )
        if old_task.get("status") != "QUEUED" or any(value is not None for value in forbidden_values):
            raise V4ValidationError("forward transform accepts only quiescent QUEUED V3.1 tasks")

        mission = missions.get(old_task.get("mission_id"))
        if mission is None or mission.get("supersedes_revision") != old_task.get("mission_revision"):
            raise V4ValidationError("queued V3.1 task does not map to exact V4 Mission supersession")
        gap = _gap(mission, old_task["gap_id"])
        logical = (mission["mission_id"], mission["mission_revision"], gap["gap_id"])
        if logical in carry_keys or gap["gap_state"] != "OPEN":
            continue

        tasks.append(
            {
                "task_id": f"MISSION--{mission['mission_id']}--{mission['mission_revision']}--{gap['gap_id']}",
                "mission_id": mission["mission_id"],
                "mission_revision": mission["mission_revision"],
                "mission_contract_blob_sha": mission_shas[mission["mission_id"]],
                "repository_authority_blob_sha": repository_shas[gap["repository"]],
                "gap_id": gap["gap_id"],
                "repository": gap["repository"],
                "acceptance": copy.deepcopy(gap["acceptance"]),
                "integration_policy": gap["integration_policy"],
                "review_policy": gap["review_policy"],
                "convergence_required": _convergence_required(gap),
                "status": "QUEUED",
                "phase": "BUILD",
                "candidate": None,
                "last_review": None,
                "external_review": None,
                "blocker": None,
                "created_at": old_task["created_at"],
                "updated_at": old_task["updated_at"],
            }
        )

    queue = {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": None,
        "migration_facts": carry,
        "tasks": tasks,
    }
    validate_v4_queue(queue, authority_root, schema_root=schema_root)
    return queue


def _validated_realized_gaps(
    v4_mission: dict[str, Any], realized_facts: list[dict[str, Any]]
) -> set[str]:
    required = {"mission_id", "mission_revision", "gap_id", "repository", "candidate_sha", "target_ref"}
    realized: set[str] = set()
    for fact in realized_facts:
        if set(fact) != required:
            raise V4ValidationError("rollback realized fact has unexpected shape")
        if fact["mission_id"] != v4_mission["mission_id"] or fact["mission_revision"] != v4_mission["mission_revision"]:
            raise V4ValidationError("rollback realized fact targets wrong Mission revision")
        gap = _gap(v4_mission, fact["gap_id"])
        if fact["repository"] != gap["repository"]:
            raise V4ValidationError("rollback realized fact repository mismatch")
        if len(fact["candidate_sha"]) != 40 or any(c not in "0123456789abcdef" for c in fact["candidate_sha"]):
            raise V4ValidationError("rollback realized fact requires exact 40-char candidate SHA")
        if not fact["target_ref"]:
            raise V4ValidationError("rollback realized fact requires target_ref")
        realized.add(fact["gap_id"])
    return realized


def derive_rollback_v31_mission(
    pre_cutover_v31_mission: dict[str, Any],
    v4_mission: dict[str, Any],
    *,
    legacy_completed_gap_ids: set[str],
    realized_facts: list[dict[str, Any]],
    rollback_revision: str,
) -> dict[str, Any]:
    """Create a governed V3.1 rollback Mission without fabricating V3.1 results."""
    if pre_cutover_v31_mission.get("protocol_id") != "MISSION_CONTRACT_V3_1":
        raise V4ValidationError("rollback requires frozen V3.1 Mission")
    if v4_mission.get("protocol_id") != "MISSION_CONTRACT_V4":
        raise V4ValidationError("rollback requires current V4 Mission")
    if v4_mission.get("mission_id") != pre_cutover_v31_mission.get("mission_id"):
        raise V4ValidationError("rollback Mission identity mismatch")
    if v4_mission.get("supersedes_revision") != pre_cutover_v31_mission.get("mission_revision"):
        raise V4ValidationError("V4 Mission is not based on frozen V3.1 revision")

    known = {gap["gap_id"] for gap in pre_cutover_v31_mission["gaps"]}
    if not legacy_completed_gap_ids <= known:
        raise V4ValidationError("legacy completion references unknown gap")
    realized = _validated_realized_gaps(v4_mission, realized_facts)
    if not realized <= known:
        raise V4ValidationError("realized V4 work cannot map to frozen V3.1 Mission")

    rollback = copy.deepcopy(pre_cutover_v31_mission)
    prior_revision = rollback["mission_revision"]
    rollback["mission_revision"] = rollback_revision
    rollback["supersedes_revision"] = prior_revision
    retired = legacy_completed_gap_ids | realized
    for gap in rollback["gaps"]:
        gap["gap_state"] = "RETIRED" if gap["gap_id"] in retired else "OPEN"
    return rollback


def derive_empty_rollback_v31_queue(pre_cutover_queue: dict[str, Any]) -> dict[str, Any]:
    """Return an empty V3.1 work queue; V3.1 TICK rematerializes OPEN rollback Mission work."""
    if pre_cutover_queue.get("version") != "3.1" or pre_cutover_queue.get("principal_manual_relay_count") != 0:
        raise V4ValidationError("rollback requires frozen V3.1 queue with relay 0")
    return {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": copy.deepcopy(pre_cutover_queue.get("migration_facts", [])),
        "tasks": [],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="control-engine checkout containing V4 schemas",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    authority = sub.add_parser("validate-authority")
    authority.add_argument("--authority-root", type=Path, required=True)

    queue = sub.add_parser("validate-queue")
    queue.add_argument("--authority-root", type=Path, required=True)
    queue.add_argument("--queue", type=Path, required=True)

    forward = sub.add_parser("forward")
    forward.add_argument("--authority-root", type=Path, required=True)
    forward.add_argument("--old-queue", type=Path, required=True)
    forward.add_argument("--out", type=Path, required=True)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    schema_root: Path = args.schema_root

    if args.command == "validate-authority":
        load_v4_authority(args.authority_root, schema_root=schema_root)
        print("CONTROL_V4_AUTHORITY_VALIDATION=PASS")
        return
    if args.command == "validate-queue":
        validate_v4_queue(load_json(args.queue), args.authority_root, schema_root=schema_root)
        print("CONTROL_V4_QUEUE_VALIDATION=PASS")
        return
    if args.command == "forward":
        transformed = forward_queue_v31_to_v4(
            load_json(args.old_queue), args.authority_root, schema_root=schema_root
        )
        write_json(args.out, transformed)
        print("CONTROL_V4_FORWARD_TRANSFORM=PASS")
        return
    raise AssertionError(args.command)


if __name__ == "__main__":
    main()
