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
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from control_engine import migration_v31 as v31_migration

MISSION_SCHEMA = Path("schemas/mission_contract_v4.schema.json")
REPOSITORY_SCHEMA = Path("schemas/repository_authority_v4.schema.json")
QUEUE_SCHEMA = Path("schemas/dispatch_queue_v4.schema.json")
MISSION_DIR = Path("control/missions")
REPOSITORY_DIR = Path("control/repository-authority")
LEASE_SECONDS = 5400
PENDING_DRIFT_BLOCKER = "MISSION_REVISION_DISCIPLINE_VIOLATION_PENDING"
REVISION_RE = re.compile(r"^(?P<day>\d{4}-\d{2}-\d{2})-r(?P<sequence>[1-9]\d*)$")


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


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise V4ValidationError(f"invalid timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise V4ValidationError(f"timestamp must be timezone-aware: {value}")
    return parsed.astimezone(timezone.utc)


def _revision_key(value: object) -> tuple[int, date]:
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


def _revision_precedes(source: object, current: object) -> bool:
    source_sequence, source_day = _revision_key(source)
    current_sequence, current_day = _revision_key(current)
    return source_sequence < current_sequence and source_day <= current_day


def _canonical_repository(value: object) -> str:
    if not isinstance(value, str) or value.count("/") != 1:
        raise V4ValidationError("repository identity invalid")
    owner, repository = value.split("/", 1)
    if not owner or not repository:
        raise V4ValidationError("repository identity invalid")
    return f"{owner.lower()}/{repository.lower()}"


def _validate_v31_migration_facts(queue: dict[str, Any]) -> None:
    try:
        v31_migration.validate_migration_facts(queue)
    except v31_migration.MigrationError as exc:
        raise V4ValidationError("V3.1 migration facts are invalid") from exc


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


def _carry_map(mission: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for carry in mission.get("done_carry_forward", []):
        target = carry["target_gap_id"]
        if target in result:
            raise V4ValidationError(f"{mission['mission_id']}: duplicate carry-forward target {target}")
        target_gap = _gap(mission, target)
        if target_gap["gap_state"] != "RETIRED":
            raise V4ValidationError(
                f"{mission['mission_id']}:{target}: carry-forward target must be RETIRED"
            )
        if not _revision_precedes(carry["source_mission_revision"], mission["mission_revision"]):
            raise V4ValidationError(
                f"{mission['mission_id']}:{target}: carry-forward source must be an older revision"
            )
        result[target] = carry
    return result


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

    carry_by_target = _carry_map(mission)
    for gap in gaps.values():
        if gap["gap_state"] != "OPEN":
            continue
        for dependency in gap["depends_on"]:
            if gaps[dependency]["gap_state"] == "RETIRED" and dependency not in carry_by_target:
                raise V4ValidationError(
                    f"{mission['mission_id']}:{gap['gap_id']}: RETIRED dependency {dependency} requires carry-forward"
                )


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
        supersedes = mission.get("supersedes_revision")
        if supersedes is not None and not _revision_precedes(
            supersedes, mission["mission_revision"]
        ):
            raise V4ValidationError(
                f"{mission_id}: Mission revision must advance monotonically"
            )
        _validate_mission_graph(mission)
        missions[mission_id] = mission
        mission_shas[mission_id] = git_blob_sha(path)

    for path in repository_paths:
        authority = load_json(path)
        _validate(authority, repository_schema, str(path.relative_to(authority_root)))
        repository = _canonical_repository(authority["repository"])
        if repository in repositories:
            raise V4ValidationError(f"duplicate repository authority: {repository}")
        repositories[repository] = authority
        repository_shas[repository] = git_blob_sha(path)

    for mission in missions.values():
        if _canonical_repository(mission["repository"]) not in repositories:
            raise V4ValidationError(f"{mission['mission_id']}: missing repository authority")
        for gap in mission["gaps"]:
            if _canonical_repository(gap["repository"]) not in repositories:
                raise V4ValidationError(
                    f"{mission['mission_id']}:{gap['gap_id']}: missing repository authority"
                )

    return missions, repositories, mission_shas, repository_shas


def _validate_source_fact(
    mission: dict[str, Any],
    carry: dict[str, Any],
    migration_by_ref: dict[str, dict[str, Any]],
    task_by_id: dict[str, dict[str, Any]],
) -> None:
    source_ref = carry["source_fact_ref"]
    target_repository = _canonical_repository(
        _gap(mission, carry["target_gap_id"])["repository"]
    )
    expected = (
        mission["mission_id"],
        carry["source_mission_revision"],
        carry["source_gap_id"],
        target_repository,
    )

    if carry["source_fact_kind"] == "MIGRATION_FACT":
        fact = migration_by_ref.get(source_ref)
        if fact is None:
            raise V4ValidationError(f"missing carry-forward migration fact: {source_ref}")
        actual = (
            fact["mission_id"],
            fact["mission_revision"],
            fact["gap_id"],
            _canonical_repository(fact["repository"]),
        )
        if actual != expected:
            raise V4ValidationError(f"carry-forward migration fact mismatch: {source_ref}")
        return

    task = task_by_id.get(source_ref)
    if task is None or task["status"] != "DONE":
        raise V4ValidationError(f"missing terminal V4_DONE source task: {source_ref}")
    if _canonical_sha256(task) != carry["source_task_sha256"]:
        raise V4ValidationError(f"carry-forward V4_DONE digest mismatch: {source_ref}")
    actual = (
        task["mission_id"],
        task["mission_revision"],
        task["gap_id"],
        _canonical_repository(task["repository"]),
    )
    if actual != expected:
        raise V4ValidationError(f"carry-forward V4_DONE task mismatch: {source_ref}")
    if task["candidate"] is None or task["last_review"] is None:
        raise V4ValidationError(f"V4_DONE source lacks reviewed candidate evidence: {source_ref}")
    if task["last_review"].get("outcome") != "PASS":
        raise V4ValidationError(f"V4_DONE source review is not PASS: {source_ref}")
    if task["review_policy"] == "EXTERNAL":
        external = task["external_review"]
        if external is None or external.get("status") != "PASS":
            raise V4ValidationError(f"V4_DONE source external review is not PASS: {source_ref}")


def validate_v4_queue(queue: dict[str, Any], authority_root: Path, *, schema_root: Path) -> None:
    _validate(queue, _load_schema(schema_root, QUEUE_SCHEMA), "V4 queue")
    _validate_v31_migration_facts(queue)
    missions, _, mission_shas, repository_shas = load_v4_authority(
        authority_root, schema_root=schema_root
    )

    migration_by_ref: dict[str, dict[str, Any]] = {}
    for fact in queue["migration_facts"]:
        ref = fact["source_task_id"]
        if ref in migration_by_ref:
            raise V4ValidationError(f"duplicate migration fact source identity: {ref}")
        migration_by_ref[ref] = fact

    task_by_id: dict[str, dict[str, Any]] = {}
    logical_ids: set[tuple[str, str, str]] = set()
    for task in queue["tasks"]:
        task_id = task["task_id"]
        if task_id in task_by_id:
            raise V4ValidationError(f"duplicate task_id: {task_id}")
        task_by_id[task_id] = task
        logical = (task["mission_id"], task["mission_revision"], task["gap_id"])
        if logical in logical_ids:
            raise V4ValidationError(f"duplicate logical task identity: {logical}")
        logical_ids.add(logical)

    carry_targets: set[tuple[str, str, str]] = set()
    for mission in missions.values():
        for target, carry in _carry_map(mission).items():
            logical = (mission["mission_id"], mission["mission_revision"], target)
            carry_targets.add(logical)
            _validate_source_fact(mission, carry, migration_by_ref, task_by_id)

    for task in queue["tasks"]:
        logical = (task["mission_id"], task["mission_revision"], task["gap_id"])
        mission = missions.get(task["mission_id"])
        is_current = mission is not None and mission["mission_revision"] == task["mission_revision"]

        if is_current:
            if logical in carry_targets:
                raise V4ValidationError(f"current task duplicates protected carry-forward: {logical}")
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
                "repository_authority_blob_sha": repository_shas[
                    _canonical_repository(gap["repository"])
                ],
            }
            for field, expected_value in expected.items():
                if task[field] != expected_value:
                    raise V4ValidationError(f"{field} drift: {logical}")
        elif task["status"] not in {"DONE", "SUPERSEDED"}:
            raise V4ValidationError(f"non-current task must be terminal historical fact: {logical}")

        status = task["status"]
        phase = task["phase"]
        if status == "QUEUED" and phase != "BUILD":
            raise V4ValidationError(f"QUEUED task must be BUILD: {logical}")
        if status == "ACTIVE" and phase not in {"BUILD", "REVIEW", "REPAIR", "INTEGRATE", "CONVERGE"}:
            raise V4ValidationError(f"ACTIVE task has invalid phase: {logical}")
        if status in {"READY", "BLOCKED", "DONE", "SUPERSEDED"} and phase is not None:
            raise V4ValidationError(f"{status} task must have null phase: {logical}")
        if task["blocker"] == PENDING_DRIFT_BLOCKER and not (
            status == "ACTIVE" and phase == "REVIEW"
        ):
            raise V4ValidationError(
                f"pending Mission drift marker requires ACTIVE/REVIEW: {logical}"
            )

        candidate = task["candidate"]
        for record_field in ("last_review", "external_review"):
            record = task[record_field]
            if record is not None:
                if candidate is None:
                    raise V4ValidationError(f"{record_field} exists without candidate: {logical}")
                if record["candidate_sha"] != candidate["candidate_sha"]:
                    raise V4ValidationError(f"{record_field} candidate drift: {logical}")

    lock = queue["execution_lock"]
    if lock is None:
        return

    started = _parse_time(lock["started_at"])
    expires = _parse_time(lock["expires_at"])
    if expires - started != timedelta(seconds=LEASE_SECONDS):
        raise V4ValidationError("execution_lock lease must be exactly 5400 seconds")
    holder = task_by_id.get(lock["task_id"])
    if holder is None or holder["status"] != "ACTIVE":
        raise V4ValidationError("execution_lock must target an ACTIVE task")


def forward_queue_v31_to_v4(
    old_queue: dict[str, Any],
    authority_root: Path,
    *,
    schema_root: Path,
) -> dict[str, Any]:
    """Transform only a quiescent V3.1 snapshot; never invent V4 carry-forward authority."""
    if old_queue.get("version") != "3.1" or old_queue.get("principal_manual_relay_count") != 0:
        raise V4ValidationError("forward transform requires V3.1 queue with relay 0")
    _validate_v31_migration_facts(old_queue)

    missions, _, mission_shas, repository_shas = load_v4_authority(
        authority_root, schema_root=schema_root
    )
    migration_facts = copy.deepcopy(old_queue.get("migration_facts", []))

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
        if _canonical_repository(gap["repository"]) != _canonical_repository(
            old_task.get("repository")
        ):
            raise V4ValidationError("queued V3.1 task repository does not match V4 gap repository")
        if gap["gap_state"] != "OPEN":
            continue

        tasks.append(
            {
                "task_id": f"MISSION--{mission['mission_id']}--{mission['mission_revision']}--{gap['gap_id']}",
                "mission_id": mission["mission_id"],
                "mission_revision": mission["mission_revision"],
                "mission_contract_blob_sha": mission_shas[mission["mission_id"]],
                "repository_authority_blob_sha": repository_shas[
                    _canonical_repository(gap["repository"])
                ],
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
        "migration_facts": migration_facts,
        "tasks": tasks,
    }
    validate_v4_queue(queue, authority_root, schema_root=schema_root)
    return queue


def _validated_realized_gaps(
    v4_mission: dict[str, Any],
    v4_queue: dict[str, Any],
    *,
    authority_root: Path,
    schema_root: Path,
) -> set[str]:
    """Derive realized work only from the validated canonical current V4 queue."""
    validate_v4_queue(v4_queue, authority_root, schema_root=schema_root)
    realized: set[str] = set()
    for task in v4_queue["tasks"]:
        if (
            task["mission_id"] != v4_mission["mission_id"]
            or task["mission_revision"] != v4_mission["mission_revision"]
            or task["status"] != "DONE"
        ):
            continue
        gap = _gap(v4_mission, task["gap_id"])
        if _canonical_repository(task["repository"]) != _canonical_repository(gap["repository"]):
            raise V4ValidationError("rollback DONE task repository mismatch")
        candidate = task["candidate"]
        review = task["last_review"]
        if candidate is None or review is None:
            raise V4ValidationError("rollback DONE task lacks reviewed candidate evidence")
        if review.get("outcome") != "PASS":
            raise V4ValidationError("rollback DONE task review is not PASS")
        if task["review_policy"] == "EXTERNAL":
            external = task["external_review"]
            if external is None or external.get("status") != "PASS":
                raise V4ValidationError("rollback DONE task external review is not PASS")
        if task["blocker"] is not None:
            raise V4ValidationError("rollback DONE task cannot retain blocker")
        realized.add(task["gap_id"])
    return realized


def _legacy_completed_gaps(
    pre_cutover_v31_queue: dict[str, Any], pre_cutover_v31_mission: dict[str, Any]
) -> set[str]:
    if pre_cutover_v31_queue.get("version") != "3.1" or pre_cutover_v31_queue.get("principal_manual_relay_count") != 0:
        raise V4ValidationError("rollback requires frozen V3.1 queue with relay 0")
    _validate_v31_migration_facts(pre_cutover_v31_queue)
    completed: set[str] = set()
    for fact in pre_cutover_v31_queue.get("migration_facts", []):
        if (
            fact["mission_id"] == pre_cutover_v31_mission["mission_id"]
            and fact["mission_revision"] == pre_cutover_v31_mission["mission_revision"]
        ):
            source_gap = _gap(pre_cutover_v31_mission, fact["gap_id"])
            expected_repository = source_gap.get(
                "repository", pre_cutover_v31_mission["repository"]
            )
            if _canonical_repository(fact["repository"]) != _canonical_repository(
                expected_repository
            ):
                raise V4ValidationError("legacy completion repository mismatch")
            completed.add(fact["gap_id"])
    return completed


def derive_rollback_v31_mission(
    pre_cutover_v31_mission: dict[str, Any],
    v4_mission: dict[str, Any],
    *,
    pre_cutover_v31_queue: dict[str, Any],
    v4_queue: dict[str, Any],
    authority_root: Path,
    schema_root: Path,
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
    if not _revision_precedes(
        pre_cutover_v31_mission["mission_revision"], v4_mission["mission_revision"]
    ):
        raise V4ValidationError("V4 Mission revision must advance monotonically")

    prior_revision = pre_cutover_v31_mission["mission_revision"]
    prior_sequence, prior_day = _revision_key(prior_revision)
    rollback_sequence, rollback_day = _revision_key(rollback_revision)
    if rollback_sequence <= prior_sequence or rollback_day < prior_day:
        raise V4ValidationError("rollback Mission revision must advance monotonically")

    known = {gap["gap_id"] for gap in pre_cutover_v31_mission["gaps"]}
    legacy_completed_gap_ids = _legacy_completed_gaps(
        pre_cutover_v31_queue, pre_cutover_v31_mission
    )
    if not legacy_completed_gap_ids <= known:
        raise V4ValidationError("legacy completion references unknown gap")
    realized = _validated_realized_gaps(
        v4_mission,
        v4_queue,
        authority_root=authority_root,
        schema_root=schema_root,
    )
    if not realized <= known:
        raise V4ValidationError("realized V4 work cannot map to frozen V3.1 Mission")

    rollback = copy.deepcopy(pre_cutover_v31_mission)
    rollback["mission_revision"] = rollback_revision
    rollback["supersedes_revision"] = prior_revision
    retired = legacy_completed_gap_ids | realized
    for gap in rollback["gaps"]:
        gap_id = gap["gap_id"]
        gap["gap_state"] = "RETIRED" if gap_id in retired else "OPEN"
        if gap_id not in retired and isinstance(gap.get("depends_on"), list):
            gap["depends_on"] = [dependency for dependency in gap["depends_on"] if dependency not in retired]
    return rollback


def derive_empty_rollback_v31_queue(pre_cutover_queue: dict[str, Any]) -> dict[str, Any]:
    """Return an empty V3.1 work queue; restored V3.1 TICK rematerializes OPEN work."""
    if pre_cutover_queue.get("version") != "3.1" or pre_cutover_queue.get("principal_manual_relay_count") != 0:
        raise V4ValidationError("rollback requires frozen V3.1 queue with relay 0")
    _validate_v31_migration_facts(pre_cutover_queue)
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
