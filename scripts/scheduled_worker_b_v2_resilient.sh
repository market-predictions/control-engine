#!/usr/bin/env bash
set -euo pipefail

SOURCE="${GITHUB_WORKSPACE:-$(pwd)}/scripts/scheduled_worker_b_v2.sh"
PATCHED="${RUNNER_TEMP:-/tmp}/scheduled_worker_b_v2_resilient_${GITHUB_RUN_ID:-local}_${GITHUB_RUN_ATTEMPT:-1}.sh"

# Deployment wake: 2026-08-22 expired R3 B1 claim reconciliation.
# Deployment wake: post-repair CONTROL-193 assurance lifecycle.
python - "$SOURCE" "$PATCHED" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")

# The private connected runtime is a tools package module. Directly executing
# CODE_DIR/tools/control_connected_worker_runtime_v1.py puts only CODE_DIR/tools
# on sys.path. Its fallback then imports control_parallel_execution_v1, which in
# turn imports tools.control_queue_v1 and fails before main() with an uncaught
# ModuleNotFoundError. Preserve the exact private code while exposing CODE_DIR as
# the package root to the subprocess.
complete_anchor = '''  GH_TOKEN="$CONTROL_GITHUB_WRITE_TOKEN" \\
    python "$CODE_DIR/tools/control_connected_worker_runtime_v1.py" complete "$@"
'''
complete_fixed = '''  GH_TOKEN="$CONTROL_GITHUB_WRITE_TOKEN" \\
  PYTHONPATH="$CODE_DIR${PYTHONPATH:+:$PYTHONPATH}" \\
    python "$CODE_DIR/tools/control_connected_worker_runtime_v1.py" complete "$@"
'''
count = text.count(complete_anchor)
if count != 1:
    raise SystemExit(f"expected exactly one connected runtime invocation anchor, found {count}")
text = text.replace(complete_anchor, complete_fixed)

# A B1 claim is deliberately hard-capped at 15 minutes. The pinned private
# inference worker otherwise defaults to a 2400-second wall-clock budget, which
# can outlive its owning claim and make terminal persistence impossible. Keep a
# five-minute reserve for evidence preparation and the three durable completion
# stages; provider unavailability at this bound is fail-closed by the existing
# result packaging path.
lease_match = re.search(r'^LEASE_MINUTES=(\d+)$', text, flags=re.MULTILINE)
if lease_match is None:
    raise SystemExit("missing B1 lease bound")
lease_seconds = int(lease_match.group(1)) * 60
assurance_max_seconds = 600
completion_reserve_seconds = 300
if assurance_max_seconds + completion_reserve_seconds > lease_seconds:
    raise SystemExit("assurance wall-clock budget does not fit inside B1 lease")

inference_anchor = '''    --role assurance \\
    --attempt-id "$run_id" \\
'''
inference_bounded = f'''    --role assurance \\
    --max-seconds {assurance_max_seconds} \\
    --attempt-id "$run_id" \\
'''
count = text.count(inference_anchor)
if count != 1:
    raise SystemExit(f"expected exactly one assurance inference anchor, found {count}")
text = text.replace(inference_anchor, inference_bounded)

# The private inference kernel already writes a deliberately sanitized metadata
# document for every non-unavailable worker error. Keep the model log private,
# but carry only its allowlisted error_code into the canonical INDETERMINATE
# finding. This makes semantic transport/contract failures actionable without
# leaking prompt, provider response, credentials or arbitrary exception text.
semantic_old = '''else
  python "$PRIVATE_TMP/make_result.py" \\
    --task-id "$task_id" \\
    --run-id "$run_id" \\
    --role governance_release_assurance \\
    --outcome INDETERMINATE \\
    --candidate-sha "$candidate_sha" \\
    --summary 'Assurance worker failed before producing a valid structured verdict.' \\
    --finding 'Provider-portable assurance worker failed; PASS is forbidden.' \\
    --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \\
    --output "$FINAL_RESULT" \\
    >"$PRIVATE_TMP/make-result.log" 2>&1
fi
'''
semantic_new = '''else
  semantic_failure_class=UNKNOWN_WORKER_ERROR
  if [ -s "$METADATA" ]; then
    semantic_failure_class="$(python - "$METADATA" <<'PYMETA'
import json
import sys

allowed = {
    "POLICY_REJECTED",
    "CREDENTIAL_FORMAT_REJECTED",
    "ACCOUNT_FORMAT_REJECTED",
    "PROVIDER_HTTP_FAILURE",
    "PROVIDER_TRANSPORT_UNAVAILABLE",
    "PROVIDER_TIMEOUT",
    "PROVIDER_RESPONSE_UNPARSEABLE",
    "PROVIDER_RESPONSE_CONTRACT_REJECTED",
    "TOOL_CALL_INVALID",
    "FINAL_JSON_INVALID",
    "FINAL_CONTENT_MISSING",
    "FINAL_JSON_PARSE_INVALID",
    "FINAL_JSON_EXACT_MISMATCH",
    "CONTEXT_BUDGET_EXHAUSTED",
    "TOOL_BUDGET_EXHAUSTED",
    "WALL_CLOCK_BUDGET_EXHAUSTED",
    "WORKER_CONTRACT_REJECTED",
    "UNEXPECTED_FAILURE",
}
try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get("error_code")
except Exception:
    value = None
print(value if value in allowed else "UNKNOWN_WORKER_ERROR")
PYMETA
)"
  fi
  python "$PRIVATE_TMP/make_result.py" \\
    --task-id "$task_id" \\
    --run-id "$run_id" \\
    --role governance_release_assurance \\
    --outcome INDETERMINATE \\
    --candidate-sha "$candidate_sha" \\
    --summary 'Assurance worker failed before producing a valid structured verdict.' \\
    --finding "Provider-portable assurance worker failed; error_code=${semantic_failure_class}; PASS is forbidden." \\
    --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \\
    --output "$FINAL_RESULT" \\
    >"$PRIVATE_TMP/make-result.log" 2>&1
fi
'''
count = text.count(semantic_old)
if count != 1:
    raise SystemExit(f"expected exactly one generic assurance-worker failure block, found {count}")
text = text.replace(semantic_old, semantic_new)

# EXECUTION_UNAVAILABLE must be as diagnosable as semantic INDETERMINATE without
# exposing provider bodies, prompts or arbitrary exception text. Reuse the
# pinned private inference kernel's SAFE_ERROR_CODES as the single allowlist;
# malformed/missing metadata collapses to a stable non-sensitive fingerprint.
unavailable_old = '''elif [ "$model_rc" = "75" ]; then
  python "$PRIVATE_TMP/make_result.py" \\
    --task-id "$task_id" \\
    --run-id "$run_id" \\
    --role governance_release_assurance \\
    --outcome EXECUTION_UNAVAILABLE \\
    --candidate-sha "$candidate_sha" \\
    --summary 'Configured FREE_FAIL_CLOSED assurance provider is unavailable; no fallback or paid route was selected.' \\
    --finding 'Provider-portable assurance adapter returned unavailable.' \\
    --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \\
    --output "$FINAL_RESULT" \\
    >"$PRIVATE_TMP/make-result.log" 2>&1
'''
unavailable_new = '''elif [ "$model_rc" = "75" ]; then
  unavailable_failure_class=UNKNOWN_WORKER_ERROR
  if [ -s "$METADATA" ]; then
    unavailable_failure_class="$(python - "$METADATA" "$PRIVATE_TMP" <<'PYMETA'
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(sys.argv[2])))
try:
    from inference_worker import SAFE_ERROR_CODES
    value = json.load(open(sys.argv[1], encoding="utf-8")).get("error_code")
except Exception:
    value = None
print(value if value in SAFE_ERROR_CODES else "UNKNOWN_WORKER_ERROR")
PYMETA
)"
  fi
  python "$PRIVATE_TMP/make_result.py" \\
    --task-id "$task_id" \\
    --run-id "$run_id" \\
    --role governance_release_assurance \\
    --outcome EXECUTION_UNAVAILABLE \\
    --candidate-sha "$candidate_sha" \\
    --summary 'Configured FREE_FAIL_CLOSED assurance provider is unavailable; no fallback or paid route was selected.' \\
    --finding "Provider-portable assurance adapter returned unavailable; error_code=${unavailable_failure_class}; no fallback or paid route selected." \\
    --evidence "public control-engine Actions run ${GITHUB_RUN_ID}; backend=scheduled-b-v2" \\
    --output "$FINAL_RESULT" \\
    >"$PRIVATE_TMP/make-result.log" 2>&1
'''
count = text.count(unavailable_old)
if count != 1:
    raise SystemExit(f"expected exactly one generic assurance-unavailable block, found {count}")
text = text.replace(unavailable_old, unavailable_new)

old = '''  if ! grep -q 'CONTROL_RUNTIME_CAS_CONFLICT' "$PRIVATE_TMP/complete.log"; then
    fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION"
  fi
'''
new = '''  # connected_complete is stage-idempotent: immutable result and completion
  # records are byte-checked, and each retry starts from freshly fetched private
  # runtime state. Retry boundedly for any completion transport/stage failure;
  # invariant failures remain fail-closed after the bounded retry budget.
  if [ "$completion_attempt" -lt "$MAX_CAS_ATTEMPTS" ]; then
    continue
  fi

  # Expose only a bounded, token-redacted completion diagnostic. The workflow
  # filters this marker block out of the otherwise swallowed worker output.
  printf 'B1_TERMINAL_COMPLETION_DIAGNOSTIC_BEGIN\\n' >&2
  if [ -f "$PRIVATE_TMP/complete.log" ]; then
    tail -n 80 "$PRIVATE_TMP/complete.log" \\
      | sed -E 's/AUTHORIZATION: basic [^[:space:]]+/AUTHORIZATION: basic [REDACTED]/g; s/x-access-token:[^[:space:]@]+/x-access-token:[REDACTED]/g' \\
      >&2 || true
  else
    printf 'complete.log missing\\n' >&2
  fi
  printf 'B1_TERMINAL_COMPLETION_DIAGNOSTIC_END\\n' >&2

  # Commit-status contexts are already the public non-sensitive liveness
  # surface. Publish only a stable allowlisted failure fingerprint there so the
  # exact completion class is recoverable without exposing private task/result
  # payloads or broadening GitHub permissions.
  completion_class=UNKNOWN
  if [ -f "$PRIVATE_TMP/complete.log" ]; then
    if grep -q 'worker result identity mismatch' "$PRIVATE_TMP/complete.log"; then
      completion_class=RESULT_IDENTITY_MISMATCH
    elif grep -q 'worker result role mismatch' "$PRIVATE_TMP/complete.log"; then
      completion_class=RESULT_ROLE_MISMATCH
    elif grep -q 'worker result fields do not match canonical result contract' "$PRIVATE_TMP/complete.log"; then
      completion_class=RESULT_FIELDS_MISMATCH
    elif grep -q 'assurance result candidate differs from current task' "$PRIVATE_TMP/complete.log"; then
      completion_class=CANDIDATE_MISMATCH
    elif grep -q 'immutable runtime collision' "$PRIVATE_TMP/complete.log"; then
      completion_class=IMMUTABLE_RUNTIME_COLLISION
    elif grep -q 'CONTROL_RUNTIME_CAS_CONFLICT' "$PRIVATE_TMP/complete.log"; then
      completion_class=RUNTIME_CAS_CONFLICT
    elif grep -q 'authoritative GitHub result blob SHA differs from local result bytes' "$PRIVATE_TMP/complete.log"; then
      completion_class=RESULT_BLOB_MISMATCH
    elif grep -q 'GitHub did not return an exact result blob SHA' "$PRIVATE_TMP/complete.log"; then
      completion_class=RESULT_BLOB_LOOKUP_INVALID
    elif grep -q 'GH_TOKEN is required to fetch authoritative result blob SHA' "$PRIVATE_TMP/complete.log"; then
      completion_class=RESULT_BLOB_AUTH_MISSING
    elif grep -q 'claim' "$PRIVATE_TMP/complete.log" && grep -q -E 'expired|not current|ownership|run' "$PRIVATE_TMP/complete.log"; then
      completion_class=CLAIM_VALIDATION
    elif grep -q '^ERROR:' "$PRIVATE_TMP/complete.log"; then
      completion_class=OTHER_CONNECTED_RUNTIME_ERROR
    fi
  fi
  fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION_${completion_class}"
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one terminal-completion retry block, found {count}")
target.write_text(text.replace(old, new), encoding="utf-8")
PY

chmod 700 "$PATCHED"
bash -n "$PATCHED"
exec bash "$PATCHED"
