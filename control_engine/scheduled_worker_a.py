from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
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


def resume_a_unavailable(code_dir: str, queue_path: str, output: str | None) -> None:
    """Resume only inactive A-role EXECUTION_UNAVAILABLE records.

    This closes the historical liveness hole where unavailable A work remained
    stranded forever because the planner did not invoke resume_unavailable().
    Attempt-exhausted tasks deterministically become BLOCKED through the
    canonical state helper rather than being retried indefinitely.
    """
    parallel, _, dispatcher_state = _private_modules(code_dir)
    queue = _load(queue_path)
    parallel.validate_parallel_queue(queue)
    resumed: list[str] = []
    blocked: list[str] = []

    for task in queue.get("tasks", []):
        if task.get("state") != "EXECUTION_UNAVAILABLE":
            continue
        if task.get("resume_state") not in {"IMPLEMENTATION_QUEUED", "REPAIR_QUEUED"}:
            continue
        if any(
            task.get(field) is not None
            for field in (
                "active_run_id",
                "active_role",
                "active_worker_instance",
                "claim_started_at",
                "claim_expires_at",
            )
        ):
            raise ActuatorContractError("unavailable A task still has active ownership")

        before_state = task["state"]
        updated = dispatcher_state.resume_unavailable(task)
        if updated.get("state", "").endswith("_EXECUTING"):
            raise ActuatorContractError("resume unexpectedly created an executing claim")
        updated["active_run_id"] = None
        updated["active_role"] = None
        updated["active_worker_instance"] = None
        updated["claim_started_at"] = None
        updated["claim_expires_at"] = None
        updated["resume_state"] = None
        task.clear()
        task.update(updated)
        if task["state"] == "BLOCKED":
            blocked.append(task["task_id"])
        elif task["state"] != before_state:
            resumed.append(task["task_id"])

    parallel.validate_parallel_queue(queue)
    if resumed or blocked:
        Path(queue_path).write_text(json.dumps(queue, indent=2) + "\n", encoding="utf-8")
    if output:
        _write_private(output, {"resumed": resumed, "blocked": blocked})


def select_a1(code_dir: str, queue_path: str, output: str) -> None:
    parallel, queue_mod, _ = _private_modules(code_dir)
    queue = _load(queue_path)
    selected = parallel.select_task_for_instance(
        queue,
        queue_mod.ROLE_A,
        parallel.INSTANCE_A1,
    )
    if selected is None:
        _write_private(output, {"selected": False})
        return
    payload = {
        "selected": True,
        "task_id": selected["task_id"],
        "repository": selected.get("repository"),
        "operation": selected.get("operation"),
        "state": selected.get("state"),
        "work_branch": selected.get("work_branch"),
        "target_branch": selected.get("target_branch"),
    }
    _write_private(output, payload)


def assert_current_claim(
    code_dir: str,
    queue_path: str,
    task_id: str,
    output: str | None,
) -> None:
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
    parallel.assert_claim_current(
        queue,
        task_id=task_id,
        role=queue_mod.ROLE_A,
        worker_instance=parallel.INSTANCE_A1,
        run_id=run_id,
        now=datetime.now(timezone.utc),
    )
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise ActuatorContractError("principal_manual_relay_count changed from zero")
    if output:
        _write_private(
            output,
            {
                "task_id": task_id,
                "run_id": run_id,
                "repository": task.get("repository"),
                "operation": task.get("operation"),
                "state": task.get("state"),
                "work_branch": task.get("work_branch"),
                "target_branch": task.get("target_branch"),
            },
        )


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
        else:  # pragma: no cover
            raise ActuatorContractError("unsupported command")
    except Exception as exc:
        # Never render private task payloads in public logs. Error classes are enough for the caller.
        sys.stderr.write(f"ACTUATOR_CONTRACT_ERROR:{type(exc).__name__}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
