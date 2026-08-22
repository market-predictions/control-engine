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

pin_old = '''CONTROL_CODE_REF="recovery/187-policy-metadata-r1"
CONTROL_CODE_SHA="62cf2a88edd8700c073e51274d331210c7a36900"
'''
pin_new = '''CONTROL_CODE_REF="recovery/intake-immutable-result-collision-r1"
CONTROL_CODE_SHA="7e0e9e218467c3090dbfcbb63a51a819cc19aba6"
'''
count = text.count(pin_old)
if count != 1:
    raise SystemExit(f"expected exactly one A private-code pin, found {count}")
text = text.replace(pin_old, pin_new)

old = '''python "$GITHUB_WORKSPACE/control_engine/scheduled_worker_a.py" resume-a-unavailable \\
      --code-dir "$CODE_DIR" \\
'''
new = '''python -m control_engine.scheduled_worker_a_retry_guard \\
      --code-dir "$CODE_DIR" \\
'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"expected exactly one A retry reconciliation invocation, found {count}")
text = text.replace(old, new)

target.write_text(text, encoding="utf-8")
PY

chmod 700 "$PATCHED"
bash -n "$PATCHED"
exec bash "$PATCHED"