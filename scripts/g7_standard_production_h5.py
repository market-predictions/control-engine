from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g7_standard_production_h3 as fenced

runner = fenced.runner

STANDARD_CONTRACT = {
    "executor": runner.MODEL_ID,
    "max_tokens": fenced.MAX_TOKENS,
    "tools_enabled": False,
    "retry_count": 0,
    "provider_switches": 0,
    "model_switches": 0,
    "paid_fallback": False,
    "execution_mode": "one_bounded_direct_call",
}

_original_measure_semantic_budget = runner.measure_semantic_budget
_original_build_semantic_pack = runner.build_semantic_pack


def _canonical_task(queue_path: str, task_id: str) -> dict:
    queue = json.loads(Path(queue_path).read_text(encoding="utf-8"))
    matches = [item for item in queue.get("tasks", []) if item.get("task_id") == task_id]
    if len(matches) != 1:
        raise runner.CloudflareB1Error("H5 canonical task identity mismatch")
    return matches[0]


def _with_contract(evidence):
    value = deepcopy(evidence)
    if not isinstance(value, dict):
        raise runner.CloudflareB1Error("bounded evidence must be an object")
    value["standard_execution_contract"] = deepcopy(STANDARD_CONTRACT)
    return value


def _measure_semantic_budget_with_contract(*, bounded_evidence, **kwargs):
    return _original_measure_semantic_budget(
        bounded_evidence=_with_contract(bounded_evidence),
        **kwargs,
    )


def _build_semantic_pack_with_contract(*, bounded_evidence, **kwargs):
    return _original_build_semantic_pack(
        bounded_evidence=_with_contract(bounded_evidence),
        **kwargs,
    )


def main() -> int:
    try:
        queue_path = sys.argv[sys.argv.index("--queue") + 1]
        task_id = sys.argv[sys.argv.index("--task-id") + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit("H5 requires --queue and --task-id") from exc

    task = _canonical_task(queue_path, task_id)
    if task.get("merge_policy") != "NEVER":
        raise runner.CloudflareB1Error("Gate-7 H5 canonical merge_policy must be NEVER")

    def with_current_task(evidence):
        value = _with_contract(evidence)
        value["canonical_task_policy"] = {
            "merge_policy": task.get("merge_policy"),
            "project_integration_authorized": task.get("project_integration_authorized"),
            "principal_manual_relay_count": task.get("principal_manual_relay_count"),
        }
        return value

    def measure(*, bounded_evidence, **kwargs):
        return _original_measure_semantic_budget(
            bounded_evidence=with_current_task(bounded_evidence),
            **kwargs,
        )

    def build(*, bounded_evidence, **kwargs):
        return _original_build_semantic_pack(
            bounded_evidence=with_current_task(bounded_evidence),
            **kwargs,
        )

    runner.measure_semantic_budget = measure
    runner.build_semantic_pack = build
    return fenced.main()


if __name__ == "__main__":
    raise SystemExit(main())
