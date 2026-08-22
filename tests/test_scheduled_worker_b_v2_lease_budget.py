from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
RESILIENT = ROOT / "scripts" / "scheduled_worker_b_v2_resilient.sh"


def _render_resilient_script(tmp_path: Path) -> str:
    wrapper = RESILIENT.read_text(encoding="utf-8")
    match = re.search(
        r"python - \"\$SOURCE\" \"\$PATCHED\" <<'PY'\n(?P<patcher>.*?)\nPY\n",
        wrapper,
        flags=re.DOTALL,
    )
    assert match is not None
    output = tmp_path / "scheduled_worker_b_v2_patched.sh"
    completed = subprocess.run(
        [sys.executable, "-", str(SCRIPT), str(output)],
        input=match.group("patcher"),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return output.read_text(encoding="utf-8")


def test_assurance_wall_clock_budget_is_strictly_inside_b1_lease(tmp_path: Path) -> None:
    base = SCRIPT.read_text(encoding="utf-8")
    lease_match = re.search(r"^LEASE_MINUTES=(\d+)$", base, flags=re.MULTILINE)
    assert lease_match is not None
    lease_seconds = int(lease_match.group(1)) * 60

    rendered = _render_resilient_script(tmp_path)
    budget_match = re.search(r"--max-seconds (\d+) \\", rendered)
    assert budget_match is not None
    assurance_seconds = int(budget_match.group(1))

    # Regression for CONTROL-193 R3 attempt 2: the pinned inference worker's
    # 2400-second default could outlive the 900-second B1 claim, causing current-
    # lease validation to fail before any immutable worker-result was persisted.
    completion_reserve_seconds = 300
    assert assurance_seconds == 600
    assert assurance_seconds + completion_reserve_seconds <= lease_seconds
    assert assurance_seconds < lease_seconds
    assert rendered.count("--max-seconds 600") == 1


def test_lease_budget_fence_preserves_terminal_retry_patch(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    assert "if [ \"$completion_attempt\" -lt \"$MAX_CAS_ATTEMPTS\" ]; then" in rendered
    assert "FAIL_CLOSED_B1_TERMINAL_COMPLETION" in rendered
    assert "CONTROL_RUNTIME_CAS_CONFLICT" not in rendered[rendered.index("for completion_attempt"):]
