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
    return parallel, queue_mod


def _task(queue: dict[str, Any], task_id: str) -> dict[str, Any]:
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise ActuatorContractError(f"expected exactly one task identity, found {len(matches)}")
    return matches[0]


def list_resumable_b(code_dir: str, queue_path: str, output: str) -> None:
    """Identify resumable B records; canonical CLI owns the actual transition."""
    parallel, _ = _private_modules(code_dir)
    queue = _load(queue_path)
    parallel.validate_parallel_queue(queue)
    resumable: list[str] = []
    for task in queue.get("tasks", []):
        if task.get("state") != "EXECUTION_UNAVAILABLE":
            continue
        if task.get("resume_state") != "ASSURANCE_QUEUED":
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
            raise ActuatorContractError("unavailable B task still has active ownership")
        resumable.append(task["task_id"])
    target = Path(output)
    target.write_text("".join(f"{task_id}\n" for task_id in resumable), encoding="utf-8")
    target.chmod(0o600)


def select_b1(code_dir: str, queue_path: str, output: str) -> None:
    parallel, queue_mod = _private_modules(code_dir)
    queue = _load(queue_path)
    selected = parallel.select_task_for_instance(
        queue,
        queue_mod.ROLE_B,
        parallel.INSTANCE_B1,
    )
    if selected is None:
        _write_private(output, {"selected": False})
        return
    _write_private(
        output,
        {
            "selected": True,
            "task_id": selected["task_id"],
            "repository": selected.get("repository"),
            "candidate_sha": selected.get("candidate_sha"),
            "candidate_pr": selected.get("candidate_pr"),
            "governance_issue": selected.get("governance_issue"),
            "state": selected.get("state"),
        },
    )


def assert_current_claim(
    code_dir: str,
    queue_path: str,
    task_id: str,
    output: str | None,
) -> None:
    parallel, queue_mod = _private_modules(code_dir)
    queue = _load(queue_path)
    task = _task(queue, task_id)
    if task.get("active_role") != queue_mod.ROLE_B:
        raise ActuatorContractError("canonical claim role is not governance_release_assurance")
    if task.get("active_worker_instance") != parallel.INSTANCE_B1:
        raise ActuatorContractError("canonical claim worker is not B1")
    run_id = task.get("active_run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ActuatorContractError("canonical claim run id is missing")
    parallel.assert_claim_current(
        queue,
        task_id=task_id,
        role=queue_mod.ROLE_B,
        worker_instance=parallel.INSTANCE_B1,
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
                "handover_id": task.get("handover_id"),
                "repository": task.get("repository"),
                "candidate_sha": task.get("candidate_sha"),
                "candidate_pr": task.get("candidate_pr"),
                "governance_issue": task.get("governance_issue"),
                "state": task.get("state"),
            },
        )


def assert_finalized(code_dir: str, queue_path: str, task_id: str, run_id: str) -> None:
    parallel, _ = _private_modules(code_dir)
    queue = _load(queue_path)
    parallel.validate_parallel_queue(queue)
    task = _task(queue, task_id)
    if not isinstance(run_id, str) or not run_id:
        raise ActuatorContractError("finalization run id missing")
    for field in (
        "active_run_id",
        "active_role",
        "active_worker_instance",
        "claim_started_at",
        "claim_expires_at",
    ):
        if task.get(field) is not None:
            raise ActuatorContractError(f"finalized task still has {field}")
    if task.get("last_terminal_completion_run_id") != run_id:
        raise ActuatorContractError("task is inactive but exact terminal completion was not consumed")
    result_ref = task.get("last_terminal_completion_result_ref")
    if not isinstance(result_ref, str) or not result_ref.startswith("control/worker-results/") or not result_ref.endswith(".json"):
        raise ActuatorContractError("exact terminal completion result reference is missing")
    assurance_ref = task.get("assurance_result_ref")
    if assurance_ref != f"control-runtime-state:{result_ref}":
        raise ActuatorContractError("assurance result reference differs from terminal completion provenance")
    if queue.get("principal_manual_relay_count") != 0 or task.get("principal_manual_relay_count") != 0:
        raise ActuatorContractError("principal_manual_relay_count changed from zero")


def read_private_field(path: str, field: str) -> str:
    payload = _load(path)
    value = payload.get(field)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        raise ActuatorContractError("requested private field must be scalar")
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private-state helper for Scheduled Worker B V2")
    sub = parser.add_subparsers(dest="command", required=True)

    resumable = sub.add_parser("list-resumable-b")
    resumable.add_argument("--code-dir", required=True)
    resumable.add_argument("--queue", required=True)
    resumable.add_argument("--output", required=True)

    select = sub.add_parser("select-b1")
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
        if args.command == "list-resumable-b":
            list_resumable_b(args.code_dir, args.queue, args.output)
        elif args.command == "select-b1":
            select_b1(args.code_dir, args.queue, args.output)
        elif args.command == "assert-claim":
            assert_current_claim(args.code_dir, args.queue, args.task_id, args.output)
        elif args.command == "assert-finalized":
            assert_finalized(args.code_dir, args.queue, args.task_id, args.run_id)
        elif args.command == "field":
            sys.stdout.write(read_private_field(args.file, args.name))
        else:  # pragma: no cover
            raise ActuatorContractError("unsupported command")
    except Exception as exc:
        sys.stderr.write(f"ACTUATOR_CONTRACT_ERROR:{type(exc).__name__}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
