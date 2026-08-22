from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import re
import sys
from typing import Any


class ActuatorContractError(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_private(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    target.chmod(0o600)


def _private_modules(code_dir: str | Path):
    root = str(Path(code_dir).resolve())
    if root not in sys.path:
        sys.path.insert(0, root)
    parallel = importlib.import_module("tools.control_parallel_execution_v1")
    queue_mod = importlib.import_module("tools.control_queue_v1")
    dispatcher_state = importlib.import_module("dispatcher.state")
    return parallel, queue_mod, dispatcher_state


def _task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise ActuatorContractError(f"expected exactly one task identity, found {len(matches)}")
    return matches[0]


def _has_active_ownership(task: dict[str, Any]) -> bool:
    return any(
        task.get(field) is not None
        for field in (
            "active_run_id",
            "active_role",
            "active_worker_instance",
            "claim_started_at",
            "claim_expires_at",
        )
    )


def _clear_inactive_ownership(task: dict[str, Any]) -> None:
    task["active_run_id"] = None
    task["active_role"] = None
    task["active_worker_instance"] = None
    task["claim_started_at"] = None
    task["claim_expires_at"] = None
    task["resume_state"] = None


def _next_assurance_retry_task_id(task_id: str) -> str | None:
    match = re.search(r"-R(\d+)$", task_id)
    if match:
        generation = int(match.group(1))
        if generation >= 3:
            return None
        return f"{task_id[:match.start()]}-R{generation + 1}"
    return f"{task_id}-R2"


def _next_handover_id(handover_id: str) -> str:
    match = re.search(r"-H(\d+)$", handover_id)
    if not match:
        raise ActuatorContractError("assurance retry source handover id is not generation-bound")
    return f"{handover_id[:match.start()]}-H{int(match.group(1)) + 1}"


def _matching_intake(intake_dir: Path, task_id: str) -> tuple[Path, dict[str, Any]]:
    matches: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(intake_dir.glob("*.json")):
        payload = _load(path)
        intent = payload.get("queue_intent")
        if isinstance(intent, dict) and intent.get("task_id") == task_id:
            matches.append((path, payload))
    if len(matches) != 1:
        raise ActuatorContractError(
            f"expected exactly one project intake for exhausted assurance task, found {len(matches)}"
        )
    return matches[0]


def _replace_task_identity(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_replace_task_identity(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_task_identity(item, old, new) for key, item in value.items()}
    return value


def _ensure_assurance_retry_intake(queue_path: str, task: dict[str, Any]) -> str | None:
    if task.get("operation") != "ASSURANCE" or task.get("last_verdict") != "NONE":
        return None
    if task.get("assurance_result_ref") not in (None, ""):
        return None
    candidate_sha = task.get("candidate_sha")
    if not isinstance(candidate_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", candidate_sha):
        raise ActuatorContractError("verdictless exhausted assurance has invalid candidate identity")

    old_task_id = task["task_id"]
    new_task_id = _next_assurance_retry_task_id(old_task_id)
    if new_task_id is None:
        return None

    queue = _load(queue_path)
    existing_tasks = [item for item in queue.get("tasks", []) if item.get("task_id") == new_task_id]
    if len(existing_tasks) > 1:
        raise ActuatorContractError("duplicate assurance retry task identity")
    if len(existing_tasks) == 1:
        existing = existing_tasks[0]
        if existing.get("candidate_sha") != candidate_sha or existing.get("operation") != "ASSURANCE":
            raise ActuatorContractError("existing assurance retry task has conflicting binding")
        return new_task_id

    intake_dir = Path(queue_path).parent / "project-intake"
    if not intake_dir.is_dir():
        raise ActuatorContractError("canonical project-intake directory is missing")
    _, source = _matching_intake(intake_dir, old_task_id)
    source_intent = source.get("queue_intent")
    if not isinstance(source_intent, dict):
        raise ActuatorContractError("source assurance intake has no queue_intent")
    if source_intent.get("candidate_sha") != candidate_sha:
        raise ActuatorContractError("source assurance intake candidate does not match queue")
    source_revision = source_intent.get("revision")
    if not isinstance(source_revision, str) or not source_revision:
        raise ActuatorContractError("source assurance intake revision is missing")
    source_handover = source_intent.get("handover_id")
    if not isinstance(source_handover, str) or not source_handover:
        raise ActuatorContractError("source assurance intake handover is missing")

    new_project_id = new_task_id.replace("-", "_")
    target = intake_dir / f"{new_project_id}.json"
    # Execution retries reuse the same still-unconsumed immutable assurance request.
    # Task/revision identity advances, governance/handover identity does not.
    retry_handover = source_handover
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    successor = _replace_task_identity(source, old_task_id, new_task_id)
    successor["project_id"] = new_project_id
    successor["status"] = "ASSURANCE_READY"
    intent = successor["queue_intent"]
    intent["revision"] = new_task_id
    intent["supersedes_revision"] = source_revision
    intent["task_id"] = new_task_id
    intent["handover_id"] = retry_handover
    intent["priority"] = int(source_intent.get("priority", 0)) - 1
    intent["max_attempts"] = int(source_intent.get("max_attempts", task.get("max_attempts", 3)))
    intent["last_verdict"] = "NONE"
    intent["last_findings"] = []
    intent["current_blocker"] = None
    intent["created_at"] = now
    intent["updated_at"] = now
    instruction = intent.get("instruction")
    if not isinstance(instruction, str) or not instruction:
        raise ActuatorContractError("source assurance intake instruction is missing")
    intent["instruction"] = (
        instruction
        + " This is the final bounded automatic execution-retry generation after the predecessor exhausted its runtime attempt budget without producing any verdict. Do not inherit or infer a verdict from the predecessor."
    )
    criteria = intent.get("acceptance_criteria")
    if not isinstance(criteria, list):
        raise ActuatorContractError("source assurance intake acceptance criteria are missing")
    final_retry = "This R3 generation is the final automatic execution retry; if it exhausts without a durable verdict, converge terminally instead of creating R4."
    if final_retry not in criteria:
        criteria.append(final_retry)

    if target.exists():
        existing = _load(target)
        existing_intent = existing.get("queue_intent", {})
        if (
            existing_intent.get("task_id") != new_task_id
            or existing_intent.get("candidate_sha") != candidate_sha
            or existing_intent.get("supersedes_revision") != source_revision
        ):
            raise ActuatorContractError("existing assurance retry intake conflicts with expected binding")
        existing_handover = existing_intent.get("handover_id")
        if existing_handover != retry_handover:
            expected_blocker = f"INTAKE_RECONCILIATION_BLOCKED: authoritative handover is missing: {existing_handover}"
            if existing_intent.get("current_blocker") != expected_blocker:
                raise ActuatorContractError("existing assurance retry handover drift is not the known auto-blocker")
            target.write_text(json.dumps(successor, indent=2) + "\n", encoding="utf-8")
            target.chmod(0o600)
        return new_task_id

    target.write_text(json.dumps(successor, indent=2) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return new_task_id


def _has_exhaustion_marker(task: dict[str, Any]) -> bool:
    findings = task.get("last_findings", [])
    return isinstance(findings, list) and any(
        finding == "Attempt budget exhausted during scheduled reconciliation."
        for finding in findings
    )


def resume_a_unavailable(code_dir: str, queue_path: str, output: str | None) -> None:
    """Converge inactive retry state before intake materialization and selection.

    Canonical unavailable A work is resumed through the pinned private state
    helper. Any inactive queued task whose attempt budget is already exhausted
    is transitioned to canonical BLOCKED so selection and claimability cannot
    diverge after lease recovery. A verdictless exhausted assurance task may
    materialize exactly one further immutable execution generation, capped at
    R3, while reusing its still-unconsumed assurance-request handover.
    Already-converged BLOCKED records are eligible only when they carry the
    exact scheduled-reconciliation exhaustion marker.
    """
    parallel, _, dispatcher_state = _private_modules(code_dir)
    queue = _load(queue_path)
    parallel.validate_parallel_queue(queue)
    resumed: list[str] = []
    blocked: list[str] = []
    generated_assurance_retries: list[str] = []

    for task in queue.get("tasks", []):
        if task.get("state") != "EXECUTION_UNAVAILABLE":
            continue
        if task.get("resume_state") not in {"IMPLEMENTATION_QUEUED", "REPAIR_QUEUED"}:
            continue
        if _has_active_ownership(task):
            raise ActuatorContractError("unavailable A task still has active ownership")

        before_state = task["state"]
        updated = dispatcher_state.resume_unavailable(task)
        if updated.get("state", "").endswith("_EXECUTING"):
            raise ActuatorContractError("resume unexpectedly created an executing claim")
        _clear_inactive_ownership(updated)
        task.clear()
        task.update(updated)
        if task["state"] == "BLOCKED":
            blocked.append(task["task_id"])
        elif task["state"] != before_state:
            resumed.append(task["task_id"])

    for task in queue.get("tasks", []):
        if task.get("state") != "BLOCKED" or not _has_exhaustion_marker(task):
            continue
        attempt = task.get("attempt")
        maximum = task.get("max_attempts")
        if not isinstance(attempt, int) or not isinstance(maximum, int) or attempt < maximum:
            continue
        if _has_active_ownership(task):
            raise ActuatorContractError("blocked exhausted assurance still has active ownership")
        retry_task_id = _ensure_assurance_retry_intake(queue_path, task)
        if not retry_task_id:
            continue
        finding = f"Verdictless execution exhaustion materialized bounded successor intake {retry_task_id}."
        if finding not in task.get("last_findings", []):
            task["last_findings"] = list(task.get("last_findings", [])) + [finding]
            blocked.append(task["task_id"])
        generated_assurance_retries.append(retry_task_id)

    queued_states = {"IMPLEMENTATION_QUEUED", "REPAIR_QUEUED", "ASSURANCE_QUEUED"}
    for task in queue.get("tasks", []):
        if task.get("state") not in queued_states:
            continue
        attempt = task.get("attempt")
        maximum = task.get("max_attempts")
        if not isinstance(attempt, int) or not isinstance(maximum, int) or attempt < maximum:
            continue
        if _has_active_ownership(task):
            raise ActuatorContractError("attempt-exhausted queued task still has active ownership")

        retry_task_id = None
        if task.get("state") == "ASSURANCE_QUEUED":
            retry_task_id = _ensure_assurance_retry_intake(queue_path, task)

        updated = dispatcher_state.transition(task, "BLOCKED")
        _clear_inactive_ownership(updated)
        updated["last_findings"] = list(task.get("last_findings", [])) + [
            "Attempt budget exhausted during scheduled reconciliation."
        ]
        if retry_task_id:
            updated["last_findings"].append(
                f"Verdictless execution exhaustion materialized bounded successor intake {retry_task_id}."
            )
            generated_assurance_retries.append(retry_task_id)
        task.clear()
        task.update(updated)
        if task["task_id"] not in blocked:
            blocked.append(task["task_id"])

    parallel.validate_parallel_queue(queue)
    if resumed or blocked:
        Path(queue_path).write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    if output:
        _write_private(
            output,
            {
                "resumed": resumed,
                "blocked": blocked,
                "generated_assurance_retries": generated_assurance_retries,
            },
        )


def select_a1(code_dir: str, queue_path: str, output: str) -> None:
    parallel, queue_mod, _ = _private_modules(code_dir)
    queue = _load(queue_path)
    selected = parallel.select_task_for_instance(queue, queue_mod.ROLE_A, parallel.INSTANCE_A1)
    if selected is None:
        _write_private(output, {"selected": False})
        return
    if selected.get("attempt", 0) >= selected.get("max_attempts", 0):
        raise ActuatorContractError("private selector returned attempt-exhausted A task")
    _write_private(
        output,
        {
            "selected": True,
            "task_id": selected["task_id"],
            "repository": selected.get("repository"),
            "operation": selected.get("operation"),
            "state": selected.get("state"),
            "work_branch": selected.get("work_branch"),
            "target_branch": selected.get("target_branch"),
        },
    )


def assert_current_claim(code_dir: str, queue_path: str, task_id: str, output: str | None) -> None:
    parallel, queue_mod, _ = _private_modules(code_dir)
    queue = _load(queue_path)
    task = _task(queue, task_id)
    if task.get("active_role") != queue_mod.ROLE_A:
        raise ActuatorContractError("canonical claim role is not implementation_operations")
    if task.get("active_worker_instance") != parallel.INSTANCE_A1:
        raise ActuatorContractError("canonical claim worker is not A1")
    run_id = task.get("active_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ActuatorContractError("canonical claim run id is missing")
    parallel.assert_claim_current(queue, task_id=task_id, role=queue_mod.ROLE_A, worker_instance=parallel.INSTANCE_A1, run_id=run_id, now=datetime.now(timezone.utc))
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise ActuatorContractError("principal_manual_relay_count changed from zero")
    if output:
        _write_private(output, {"task_id": task_id, "run_id": run_id, "repository": task.get("repository"), "operation": task.get("operation"), "state": task.get("state"), "work_branch": task.get("work_branch"), "target_branch": task.get("target_branch")})


def assert_finalized(code_dir: str, queue_path: str, task_id: str, run_id: str) -> None:
    parallel, _, _ = _private_modules(code_dir)
    queue = _load(queue_path)
    parallel.validate_parallel_queue(queue)
    task = _task(queue, task_id)
    if task.get("active_run_id") is not None:
        raise ActuatorContractError("finalized task still has active_run_id")
    if task.get("active_role") is not None:
        raise ActuatorContractError("finalized task still has active_role")
    if task.get("active_worker_instance") is not None:
        raise ActuatorContractError("finalized task still has active_worker_instance")
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise ActuatorContractError("principal_manual_relay_count changed from zero")
    if not isinstance(run_id, str) or not run_id:
        raise ActuatorContractError("finalization run id missing")


def read_private_field(path: str, field: str) -> str:
    payload = _load(path)
    value = payload.get(field)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        raise ActuatorContractError("requested private field must be scalar")
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private-state helper for Scheduled Worker A V2")
    sub = parser.add_subparsers(dest="command", required=True)
    resume = sub.add_parser("resume-a-unavailable")
    resume.add_argument("--code-dir", required=True)
    resume.add_argument("--queue", required=True)
    resume.add_argument("--output")
    select = sub.add_parser("select-a1")
    select.add_argument("--code-dir", required=True)
    select.add_argument("--queue", required=True)
    select.add_argument("--output", required=True)
    claim = sub.add_parser("assert-claim")
    claim.add_argument("--code-dir", required=True)
    claim.add_argument("--queue", required=True)
    claim.add_argument("--task-id", required=True)
    claim.add_argument("--output")
    finalized = sub.add_parser("assert-finalized")
    finalized.add_argument("--code-dir", required=True)
    finalized.add_argument("--queue", required=True)
    finalized.add_argument("--task-id", required=True)
    finalized.add_argument("--run-id", required=True)
    field = sub.add_parser("field")
    field.add_argument("--file", required=True)
    field.add_argument("--name", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "resume-a-unavailable":
            resume_a_unavailable(args.code_dir, args.queue, args.output)
        elif args.command == "select-a1":
            select_a1(args.code_dir, args.queue, args.output)
        elif args.command == "assert-claim":
            assert_current_claim(args.code_dir, args.queue, args.task_id, args.output)
        elif args.command == "assert-finalized":
            assert_finalized(args.code_dir, args.queue, args.task_id, args.run_id)
        elif args.command == "field":
            sys.stdout.write(read_private_field(args.file, args.name))
        else:
            raise ActuatorContractError("unsupported command")
    except Exception as exc:
        sys.stderr.write(f"ACTUATOR_CONTRACT_ERROR:{type(exc).__name__}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
