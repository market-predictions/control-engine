from __future__ import annotations

from copy import deepcopy
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
    runner.measure_semantic_budget = _measure_semantic_budget_with_contract
    runner.build_semantic_pack = _build_semantic_pack_with_contract
    return fenced.main()


if __name__ == "__main__":
    raise SystemExit(main())
