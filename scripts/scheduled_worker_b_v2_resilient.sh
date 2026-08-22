#!/usr/bin/env bash
set -euo pipefail

SOURCE="${GITHUB_WORKSPACE:-$(pwd)}/scripts/scheduled_worker_b_v2.sh"
PATCHED="${RUNNER_TEMP:-/tmp}/scheduled_worker_b_v2_resilient_${GITHUB_RUN_ID:-local}_${GITHUB_RUN_ATTEMPT:-1}.sh"

python - "$SOURCE" "$PATCHED" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")

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
