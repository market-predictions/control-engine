# Gate-7 H3 deterministic post-call provenance fence.
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import g7_standard_production as runner

MAX_TOKENS = 1024
PROVENANCE_PROTOCOL = "CONTROL_STANDARD_EXECUTOR_PROVENANCE_V1"
_original_run_workers_ai_once = runner.run_workers_ai_once
_call_count = 0
_last_provenance: dict[str, object] | None = None


def _write_provenance(payload: dict[str, object]) -> None:
    global _last_provenance
    _last_provenance = payload
    path = os.environ.get("CONTROL_G7_PROVENANCE_PATH")
    if path:
        Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run_once_with_provenance(*, account_id: str, api_token: str, messages: list[dict[str, str]], **kwargs):
    global _call_count
    _call_count += 1
    if _call_count != 1:
        raise runner.CloudflareB1Error("Gate-7 H3 forbids a second semantic executor call")

    configured = {
        "protocol_id": PROVENANCE_PROTOCOL,
        "executor": runner.MODEL_ID,
        "call_count": _call_count,
        "max_tokens": MAX_TOKENS,
        "tools_enabled": False,
        "retry_count": 0,
        "provider_switches": 0,
        "model_switches": 0,
        "paid_fallback": False,
        "response_received": False,
    }
    _write_provenance(configured)
    try:
        response = _original_run_workers_ai_once(
            account_id=account_id,
            api_token=api_token,
            messages=messages,
            max_tokens=MAX_TOKENS,
            **kwargs,
        )
    except Exception:
        _write_provenance(configured)
        raise

    completed = dict(configured)
    completed["response_received"] = True
    response_id = response.get("id") if isinstance(response, dict) else None
    if isinstance(response_id, str) and response_id:
        completed["response_id"] = response_id
    _write_provenance(completed)
    return response


def _output_path(argv: list[str]) -> Path:
    try:
        index = argv.index("--output")
        return Path(argv[index + 1])
    except (ValueError, IndexError) as exc:
        raise SystemExit("Gate-7 H3 requires --output") from exc


def _validate_success_provenance() -> dict[str, object]:
    provenance = _last_provenance
    required = {
        "protocol_id": PROVENANCE_PROTOCOL,
        "executor": runner.MODEL_ID,
        "call_count": 1,
        "max_tokens": MAX_TOKENS,
        "tools_enabled": False,
        "retry_count": 0,
        "provider_switches": 0,
        "model_switches": 0,
        "paid_fallback": False,
        "response_received": True,
    }
    if not isinstance(provenance, dict):
        raise runner.CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_STANDARD_PROVENANCE_MISSING")
    for key, value in required.items():
        if provenance.get(key) != value:
            raise runner.CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_STANDARD_PROVENANCE_MISMATCH")
    if _call_count != 1:
        raise runner.CloudflareB1ExecutionUnavailable("EXECUTION_UNAVAILABLE_STANDARD_CALL_COUNT")
    return provenance


def _replace_with_unavailable(path: Path, result: dict[str, object], code: str) -> None:
    payload = {
        "version": "1.0",
        "task_id": result.get("task_id"),
        "run_id": result.get("run_id"),
        "role": "governance_release_assurance",
        "outcome": "EXECUTION_UNAVAILABLE",
        "summary": "Gate-7 H3 post-call executor provenance failed closed before canonical semantic verdict persistence.",
        "candidate_sha": result.get("candidate_sha"),
        "findings": [code],
        "evidence": ["Semantic output was not accepted because deterministic post-call provenance was absent or mismatched."],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    runner.run_workers_ai_once = _run_once_with_provenance
    output = _output_path(sys.argv)
    rc = runner.main()
    if rc != 0:
        return rc

    result = json.loads(output.read_text(encoding="utf-8"))
    outcome = result.get("outcome")
    if outcome in {"PASS", "FAIL", "INDETERMINATE"}:
        try:
            provenance = _validate_success_provenance()
        except runner.CloudflareB1ExecutionUnavailable as exc:
            _replace_with_unavailable(output, result, exc.code)
            return 0
        evidence = result.get("evidence")
        if not isinstance(evidence, list):
            _replace_with_unavailable(output, result, "EXECUTION_UNAVAILABLE_STANDARD_PROVENANCE_RESULT_CONTRACT")
            return 0
        compact = json.dumps(provenance, sort_keys=True, separators=(",", ":"))
        evidence.append(f"{PROVENANCE_PROTOCOL}:{compact}")
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    elif outcome == "EXECUTION_UNAVAILABLE":
        if _call_count > 1:
            _replace_with_unavailable(output, result, "EXECUTION_UNAVAILABLE_STANDARD_CALL_COUNT")
    else:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
