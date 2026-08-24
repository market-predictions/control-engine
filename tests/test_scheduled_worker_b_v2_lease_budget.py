from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
RESILIENT = ROOT / "scripts" / "scheduled_worker_b_v2_resilient.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-b-v2.yml"


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


def test_historical_assurance_wall_clock_budget_is_strictly_inside_b1_lease(tmp_path: Path) -> None:
    base = SCRIPT.read_text(encoding="utf-8")
    lease_match = re.search(r"^LEASE_MINUTES=(\d+)$", base, flags=re.MULTILINE)
    assert lease_match is not None
    lease_seconds = int(lease_match.group(1)) * 60
    rendered = _render_resilient_script(tmp_path)
    budget_match = re.search(r"--max-seconds (\d+) \\", rendered)
    assert budget_match is not None
    assurance_seconds = int(budget_match.group(1))
    assert assurance_seconds == 600
    assert assurance_seconds + 300 <= lease_seconds
    assert assurance_seconds < lease_seconds


def test_historical_resilient_wrapper_preserves_bounded_redaction(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    assert "B1_TERMINAL_COMPLETION_DIAGNOSTIC_BEGIN" in rendered
    assert "B1_TERMINAL_COMPLETION_DIAGNOSTIC_END" in rendered
    assert 'tail -n 80 "$PRIVATE_TMP/complete.log"' in rendered
    assert "AUTHORIZATION: basic [REDACTED]" in rendered
    assert "x-access-token:[REDACTED]" in rendered


def test_retired_workflow_cannot_invoke_historical_resilient_or_semantic_worker() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Retired Provider B Recovery V2" in workflow
    assert "scheduled_worker_b_v2_resilient.sh" not in workflow
    assert "scheduled_worker_b_v2.sh" not in workflow
    assert "CONTROL_CLOUDFLARE_API_TOKEN" not in workflow
    assert "CONTROL_GITHUB_WRITE_TOKEN" not in workflow
    assert "LEGACY_PROVIDER_B_SEMANTIC_EXECUTION=false" in workflow
    assert "PRIVATE_CONTROL_WRITE=false" in workflow
    assert "PROVIDER_FALLBACK=false" in workflow


def test_historical_terminal_retry_patch_is_fail_closed(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    assert "if [ \"$completion_attempt\" -lt \"$MAX_CAS_ATTEMPTS\" ]; then" in rendered
    assert "FAIL_CLOSED_B1_TERMINAL_COMPLETION" in rendered
    assert 'fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION_${completion_class}"' in rendered


def test_historical_semantic_worker_failure_metadata_is_allowlisted(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    for fingerprint in (
        "POLICY_REJECTED",
        "PROVIDER_HTTP_FAILURE",
        "PROVIDER_TRANSPORT_UNAVAILABLE",
        "PROVIDER_TIMEOUT",
        "PROVIDER_RESPONSE_UNPARSEABLE",
        "PROVIDER_RESPONSE_CONTRACT_REJECTED",
        "WALL_CLOCK_BUDGET_EXHAUSTED",
        "UNKNOWN_WORKER_ERROR",
    ):
        assert fingerprint in rendered
    assert 'json.load(open(sys.argv[1], encoding="utf-8")).get("error_code")' in rendered
