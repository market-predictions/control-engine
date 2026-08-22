#!/usr/bin/env bash
set -euo pipefail

SOURCE="${GITHUB_WORKSPACE:-$(pwd)}/scripts/scheduled_worker_a_v2.sh"
PATCHED="${RUNNER_TEMP:-/tmp}/scheduled_worker_a_v2_retry_guard_${GITHUB_RUN_ID:-local}_${GITHUB_RUN_ATTEMPT:-1}.sh"

python - "$SOURCE" "$PATCHED" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text(encoding="utf-8")
old = '''python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" resume-a-unavailable \\
      --code-dir "$CODE_DIR" \\
'''
new = '''python -m control_engine.scheduled_worker_a_retry_guard \\
      --code-dir "$CODE_DIR" \\
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one A retry reconciliation invocation, found {count}")
target.write_text(text.replace(old, new), encoding="utf-8")
PY

chmod 700 "$PATCHED"
bash -n "$PATCHED"
exec bash "$PATCHED"
