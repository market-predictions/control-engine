#!/usr/bin/env python3
"""Apply Control Minimal Core V1 lifecycle mutations to private canonical state.

This is deterministic lifecycle plumbing only. It performs no implementation,
assurance, merge, release, provider routing, or semantic inference.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from control_engine import minimal_core as core
from scripts import project_integration_executor as integration

QUEUE_REL = "control/DISPATCH_QUEUE.json"
RUNS_REL = "control/DISPATCH_RUNS.json"
RESULT_DIR = Path("control/worker-results")
AUTO_TASK_ID = "AUTO"
LEASE_SECONDS = 5400


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _result_ref(task_id: str, run_id: str) -> str:
    return str(RESULT_DIR / f"{task_id}--{run_id}.json")


def _persisted_results(state_dir: Path, queue: dict) -> dict[tuple[str, str], tuple[dict, str]]:
    found: dict[tuple[str, str], tuple[dict, str]] = {}
    for task in queue.get("tasks", []):
        if task.get("lifecycle_model") != core.PROTOCOL_ID or task.get("status") != core.STATUS_EXECUTING:
            continue
        claim = task.get("claim")
        if not isinstance(claim, dict) or not isinstance(claim.get("run_id"), str):
            continue
        run_id = claim["run_id"]
        ref = _result_ref(task["task_id"], run_id)
        path = state_dir / ref
        if path.is_file():
            found[(task["task_id"], run_id)] = (_load(path), ref)
    return found


def _reconcile_files(state_dir: Path, now: datetime) -> dict[str, list[str]]:
    queue_path = state_dir / QUEUE_REL
    runs_path = state_dir / RUNS_REL
    queue = _load(queue_path)
    runs = _load(runs_path)
    queue, runs, report = core.reconcile(
        queue,
        runs,
        persisted_results=_persisted_results(state_dir, queue),
        now=now,
    )
    _write(queue_path, queue)
    _write(runs_path, runs)
    return report


def _assert_no_legacy_conflict(queue: dict, role: str, repository: str) -> None:
    """Fail closed until any pre-cutover owner of this role/repository is gone."""
    for task in queue.get("tasks", []):
        if task.get("lifecycle_model") == core.PROTOCOL_ID:
            continue
        if not task.get("active_run_id"):
            continue
        if task.get("active_role") == role:
            raise RuntimeError("legacy role claim must be reconciled before Minimal Core claim")
        if task.get("repository") == repository:
            raise RuntimeError("legacy repository claim must be reconciled before Minimal Core claim")


def _init_state(state_dir: Path) -> None:
    integration._init_repo(state_dir, f"https://github.com/{integration.CONTROL_REPOSITORY}.git")
    integration._run(["git", "config", "user.name", "control-minimal-core[bot]"], cwd=state_dir)
    integration._run(["git", "config", "user.email", "control-minimal-core[bot]@users.noreply.github.com"], cwd=state_dir)


def _persist(token: str, state_dir: Path, observed: tuple[str, str], message: str) -> bool:
    if integration._remote_identity(token, state_dir) != observed:
        return False
    changed = integration._changed_paths(state_dir)
    allowed = {QUEUE_REL, RUNS_REL}
    if not changed:
        return True
    if not changed.issubset(allowed):
        raise RuntimeError("Minimal Core write scope exceeded")
    return integration._persist(
        token,
        state_dir,
        message=message,
        paths=[QUEUE_REL, RUNS_REL],
        allowed=allowed,
    )


def _with_cas(token: str, mutate, *, message: str):
    """Apply one queue/runs mutation and return the winning attempt's readback."""
    with tempfile.TemporaryDirectory(prefix="control-minimal-core-") as temp:
        state_dir = Path(temp) / "state"
        _init_state(state_dir)
        for attempt in range(1, integration.MAX_CAS_ATTEMPTS + 1):
            integration._reset_state(token, state_dir)
            observed = integration._identity(state_dir)
            value = mutate(state_dir)
            if _persist(token, state_dir, observed, message):
                integration._reset_state(token, state_dir)
                readback_queue = _load(state_dir / QUEUE_REL)
                return value, readback_queue, attempt
        raise RuntimeError("CONTROL_MINIMAL_CORE_CAS_CONFLICT")


def command_reconcile(token: str) -> int:
    def mutate(state_dir: Path):
        return _reconcile_files(state_dir, _now())

    report, _, attempt = _with_cas(token, mutate, message="runtime: reconcile Control Minimal Core")
    print("CONTROL_MINIMAL_CORE_RECONCILE=SUCCESS")
    print(f"CONTROL_MINIMAL_CORE_FINALIZED={json.dumps(report['finalized_results'])}")
    print(f"CONTROL_MINIMAL_CORE_EXPIRED={json.dumps(report['expired_claims'])}")
    print(f"CONTROL_MINIMAL_CORE_CAS_ATTEMPT={attempt}")
    return 0


def command_claim(token: str, worker_instance: str, requested_task_id: str) -> int:
    role = core.WORKER_ROLE.get(worker_instance)
    if role is None:
        raise RuntimeError("unsupported worker instance")

    def mutate(state_dir: Path):
        _reconcile_files(state_dir, _now())
        queue_path = state_dir / QUEUE_REL
        runs_path = state_dir / RUNS_REL
        queue = _load(queue_path)
        runs = _load(runs_path)
        task_id = requested_task_id
        if task_id == AUTO_TASK_ID:
            selected = core.select_task(queue, role)
            if selected is None:
                return {"idle": True}
            task_id = selected["task_id"]
        matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
        if len(matches) != 1:
            raise RuntimeError("Minimal Core task identity is not unique")
        _assert_no_legacy_conflict(queue, role, matches[0].get("repository", ""))
        queue, runs, claimed = core.claim(
            queue,
            runs,
            task_id=task_id,
            worker_instance=worker_instance,
            backend=f"canonical-minimal-core/{worker_instance.lower()}",
            now=_now(),
            lease_seconds=LEASE_SECONDS,
        )
        _write(queue_path, queue)
        _write(runs_path, runs)
        return {
            "idle": False,
            "task_id": task_id,
            "run_id": claimed["claim"]["run_id"],
            "candidate_sha": claimed.get("candidate_sha") or "",
            "repository": claimed["repository"],
            "expires_at": claimed["claim"]["expires_at"],
        }

    captured, readback_queue, attempt = _with_cas(
        token,
        mutate,
        message=f"runtime: claim Minimal Core {worker_instance}",
    )
    if captured["idle"]:
        print("CONTROL_MINIMAL_CORE_CLAIM=NO_ELIGIBLE_WORK")
        return 0

    core.assert_current_claim(
        readback_queue,
        task_id=captured["task_id"],
        worker_instance=worker_instance,
        run_id=captured["run_id"],
        now=_now(),
    )
    print("CONTROL_MINIMAL_CORE_CLAIM=START_PROVEN")
    print(f"CONTROL_MINIMAL_CORE_TASK_ID={captured['task_id']}")
    print(f"CONTROL_MINIMAL_CORE_RUN_ID={captured['run_id']}")
    print(f"CONTROL_MINIMAL_CORE_REPOSITORY={captured['repository']}")
    print(f"CONTROL_MINIMAL_CORE_CANDIDATE_SHA={captured['candidate_sha']}")
    print(f"CONTROL_MINIMAL_CORE_CLAIM_EXPIRES_AT={captured['expires_at']}")
    print(f"CONTROL_MINIMAL_CORE_CAS_ATTEMPT={attempt}")
    return 0


def command_record(token: str, task_id: str) -> int:
    def mutate(state_dir: Path):
        queue_path = state_dir / QUEUE_REL
        runs_path = state_dir / RUNS_REL
        queue = _load(queue_path)
        runs = _load(runs_path)
        matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
        if len(matches) != 1 or matches[0].get("lifecycle_model") != core.PROTOCOL_ID:
            raise RuntimeError("Minimal Core task identity is not unique")
        task = matches[0]
        if task.get("status") == core.STATUS_EXECUTING:
            claim = task.get("claim")
            if not isinstance(claim, dict) or not isinstance(claim.get("run_id"), str):
                raise RuntimeError("Minimal Core active run is missing")
            result_ref = _result_ref(task_id, claim["run_id"])
        elif task.get("status") == core.STATUS_TERMINAL:
            result_ref = task.get("result_ref")
            if not isinstance(result_ref, str) or not result_ref:
                raise RuntimeError("Minimal Core terminal result ref is missing")
        else:
            raise RuntimeError("Minimal Core result target is not executing or terminal")

        result_path = state_dir / result_ref
        if not result_path.is_file():
            raise RuntimeError("Minimal Core result is missing")
        result = _load(result_path)
        queue, runs, successor_id = core.finalize_result(
            queue,
            runs,
            task_id=task_id,
            result=result,
            result_ref=result_ref,
            now=_now(),
        )
        _write(queue_path, queue)
        _write(runs_path, runs)
        return {
            "outcome": result.get("outcome"),
            "successor_id": successor_id,
        }

    captured, readback_queue, attempt = _with_cas(
        token,
        mutate,
        message=f"runtime: finalize Minimal Core {task_id}",
    )
    projection = core.explain_task(readback_queue, task_id)
    print("CONTROL_MINIMAL_CORE_RECORD=TERMINAL")
    print(f"CONTROL_MINIMAL_CORE_TASK_ID={task_id}")
    print(f"CONTROL_MINIMAL_CORE_OUTCOME={captured['outcome']}")
    print(f"CONTROL_MINIMAL_CORE_SUCCESSOR={captured['successor_id'] or ''}")
    print(f"CONTROL_MINIMAL_CORE_RESULT_REF={projection['result_ref']}")
    print(f"CONTROL_MINIMAL_CORE_CAS_ATTEMPT={attempt}")
    return 0


def command_explain(token: str, task_id: str) -> int:
    with tempfile.TemporaryDirectory(prefix="control-minimal-core-read-") as temp:
        state_dir = Path(temp) / "state"
        _init_state(state_dir)
        integration._reset_state(token, state_dir)
        projection = core.explain_task(_load(state_dir / QUEUE_REL), task_id)
        print(json.dumps(projection, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control Minimal Core V1 private-state bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("reconcile")

    claim = sub.add_parser("claim")
    claim.add_argument("--worker-instance", choices=[core.INSTANCE_A1, core.INSTANCE_B1], required=True)
    claim.add_argument("--task-id", default=AUTO_TASK_ID)

    record = sub.add_parser("record")
    record.add_argument("--task-id", required=True)

    explain = sub.add_parser("explain")
    explain.add_argument("--task-id", required=True)
    return parser


def main() -> int:
    token = os.environ.get("CONTROL_GITHUB_WRITE_TOKEN", "")
    if not token:
        print("CONTROL_MINIMAL_CORE=NO_TOKEN")
        return 78
    args = build_parser().parse_args()
    try:
        if args.command == "reconcile":
            return command_reconcile(token)
        if args.command == "claim":
            return command_claim(token, args.worker_instance, args.task_id)
        if args.command == "record":
            return command_record(token, args.task_id)
        if args.command == "explain":
            return command_explain(token, args.task_id)
        raise RuntimeError("unsupported command")
    except Exception as exc:
        print(f"CONTROL_MINIMAL_CORE=FAILED:{type(exc).__name__}:{str(exc)[-1200:]}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
