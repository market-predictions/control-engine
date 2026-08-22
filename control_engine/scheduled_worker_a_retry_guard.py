from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from control_engine import scheduled_worker_a as base


SUPERSEDED_FINDING_PREFIX = "Auto-generated assurance retry superseded by explicit canonical successor "


def _intent_records(intake_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(intake_dir.glob("*.json")):
        payload = base._load(path)
        intent = payload.get("queue_intent")
        if isinstance(intent, dict):
            records.append((path, intent))
    return records


def _explicit_successor(
    intake_dir: Path,
    *,
    source_revision: str,
    auto_task_id: str | None,
    candidate_sha: str,
    handover_id: str | None,
) -> str | None:
    matches: list[dict[str, Any]] = []
    for _, intent in _intent_records(intake_dir):
        if intent.get("supersedes_revision") != source_revision:
            continue
        task_id = intent.get("task_id")
        if not isinstance(task_id, str) or not task_id or task_id == auto_task_id:
            continue
        matches.append(intent)
    if len(matches) > 1:
        raise base.ActuatorContractError(
            f"multiple explicit assurance successors supersede revision {source_revision!r}"
        )
    if not matches:
        return None
    successor = matches[0]
    if successor.get("operation") != "ASSURANCE":
        raise base.ActuatorContractError("explicit successor operation is not ASSURANCE")
    if successor.get("candidate_sha") != candidate_sha:
        raise base.ActuatorContractError("explicit successor candidate binding differs from exhausted assurance")
    if handover_id is not None and successor.get("handover_id") != handover_id:
        raise base.ActuatorContractError("explicit successor handover binding differs from exhausted assurance")
    task_id = successor.get("task_id")
    assert isinstance(task_id, str)
    return task_id


def _guarded_retry_factory(original):
    def guarded(queue_path: str, task: dict[str, Any]) -> str | None:
        if task.get("operation") != "ASSURANCE" or task.get("last_verdict") != "NONE":
            return original(queue_path, task)
        if task.get("assurance_result_ref") not in (None, ""):
            return original(queue_path, task)

        maximum = task.get("max_attempts")
        # A one-shot lifecycle means one execution attempt, not one attempt per
        # synthetic task generation. Never turn max_attempts=1 into an implicit
        # unbounded lineage of -R2/-R3 tasks.
        if maximum == 1:
            return None

        intake_dir = Path(queue_path).parent / "project-intake"
        _, source = base._matching_intake(intake_dir, task)
        source_intent = source.get("queue_intent")
        if not isinstance(source_intent, dict):
            raise base.ActuatorContractError("source assurance intake has no queue_intent")
        source_revision = source_intent.get("revision")
        candidate_sha = task.get("candidate_sha")
        if not isinstance(source_revision, str) or not source_revision:
            raise base.ActuatorContractError("source assurance intake revision is missing")
        if not isinstance(candidate_sha, str):
            raise base.ActuatorContractError("exhausted assurance candidate identity is missing")
        auto_task_id = base._next_assurance_retry_task_id(str(task.get("task_id")))
        explicit = _explicit_successor(
            intake_dir,
            source_revision=source_revision,
            auto_task_id=auto_task_id,
            candidate_sha=candidate_sha,
            handover_id=task.get("handover_id"),
        )
        if explicit is not None:
            return None
        return original(queue_path, task)

    return guarded


def _block_parallel_auto_successors(code_dir: str, queue_path: str) -> list[str]:
    queue = base._load(queue_path)
    parallel, _, dispatcher_state = base._private_modules(code_dir)
    intake_dir = Path(queue_path).parent / "project-intake"
    records = _intent_records(intake_dir)
    intents_by_revision = {
        intent.get("revision"): intent
        for _, intent in records
        if isinstance(intent.get("revision"), str)
    }
    superseders: dict[str, list[dict[str, Any]]] = {}
    for _, intent in records:
        supersedes = intent.get("supersedes_revision")
        if isinstance(supersedes, str) and supersedes:
            superseders.setdefault(supersedes, []).append(intent)

    blocked: list[str] = []
    for task in queue.get("tasks", []):
        if task.get("state") != "ASSURANCE_QUEUED" or base._has_active_ownership(task):
            continue
        revision = task.get("intake_revision")
        if not isinstance(revision, str) or not revision:
            continue
        intent = intents_by_revision.get(revision)
        if not isinstance(intent, dict):
            continue
        source_revision = intent.get("supersedes_revision")
        if not isinstance(source_revision, str) or not source_revision:
            continue
        source_intent = intents_by_revision.get(source_revision)
        if not isinstance(source_intent, dict):
            continue
        source_task_id = source_intent.get("task_id")
        if not isinstance(source_task_id, str) or not source_task_id:
            continue
        expected_auto = base._next_assurance_retry_task_id(source_task_id)
        if task.get("task_id") != expected_auto:
            continue

        siblings = [
            item
            for item in superseders.get(source_revision, [])
            if item.get("task_id") != task.get("task_id")
        ]
        if not siblings:
            continue
        if len(siblings) > 1:
            raise base.ActuatorContractError(
                f"multiple explicit successors compete with auto retry {task.get('task_id')!r}"
            )
        sibling = siblings[0]
        if sibling.get("operation") != "ASSURANCE":
            raise base.ActuatorContractError("parallel explicit successor operation is not ASSURANCE")
        if sibling.get("candidate_sha") != task.get("candidate_sha"):
            raise base.ActuatorContractError("parallel explicit successor candidate binding differs")
        if task.get("handover_id") is not None and sibling.get("handover_id") != task.get("handover_id"):
            raise base.ActuatorContractError("parallel explicit successor handover binding differs")

        updated = dispatcher_state.transition(task, "BLOCKED")
        base._clear_inactive_ownership(updated)
        finding = SUPERSEDED_FINDING_PREFIX + str(sibling.get("task_id")) + "."
        findings = list(task.get("last_findings", []))
        if finding not in findings:
            findings.append(finding)
        updated["last_findings"] = findings
        task.clear()
        task.update(updated)
        blocked.append(str(task["task_id"]))

    if blocked:
        parallel.validate_parallel_queue(queue)
        Path(queue_path).write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    return blocked


def resume_a_unavailable(code_dir: str, queue_path: str, output: str | None) -> None:
    original = base._ensure_assurance_retry_intake
    base._ensure_assurance_retry_intake = _guarded_retry_factory(original)
    try:
        base.resume_a_unavailable(code_dir, queue_path, output)
    finally:
        base._ensure_assurance_retry_intake = original

    additionally_blocked = _block_parallel_auto_successors(code_dir, queue_path)
    if output and additionally_blocked:
        path = Path(output)
        payload = base._load(path) if path.exists() else {
            "resumed": [],
            "blocked": [],
            "generated_assurance_retries": [],
        }
        blocked = list(payload.get("blocked", []))
        for task_id in additionally_blocked:
            if task_id not in blocked:
                blocked.append(task_id)
        payload["blocked"] = blocked
        base._write_private(path, payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded successor guard for Scheduled Worker A V2 reconciliation")
    parser.add_argument("--code-dir", required=True)
    parser.add_argument("--queue", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        resume_a_unavailable(args.code_dir, args.queue, args.output)
    except Exception as exc:
        print(f"ACTUATOR_CONTRACT_ERROR:{type(exc).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
