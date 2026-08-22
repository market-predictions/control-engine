#!/usr/bin/env bash
set -euo pipefail

SOURCE="${GITHUB_WORKSPACE:-$(pwd)}/scripts/scheduled_worker_b_v2.sh"
PATCHED="${RUNNER_TEMP:-/tmp}/scheduled_worker_b_v2_resilient_${GITHUB_RUN_ID:-local}_${GITHUB_RUN_ATTEMPT:-1}.sh"

python - "$SOURCE" "$PATCHED" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
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
  fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION"
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one terminal-completion retry block, found {count}")
target.write_text(text.replace(old, new), encoding="utf-8")
PY

chmod 700 "$PATCHED"
bash -n "$PATCHED"
exec bash "$PATCHED"
