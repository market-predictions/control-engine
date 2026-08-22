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
    old_cas_only_branch = '''if ! grep -q 'CONTROL_RUNTIME_CAS_CONFLICT' "$PRIVATE_TMP/complete.log"; then
    fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION"
  fi'''
    assert old_cas_only_branch not in rendered


def test_terminal_failure_emits_only_bounded_redacted_diagnostic_block(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    assert "B1_TERMINAL_COMPLETION_DIAGNOSTIC_BEGIN" in rendered
    assert "B1_TERMINAL_COMPLETION_DIAGNOSTIC_END" in rendered
    assert 'tail -n 80 "$PRIVATE_TMP/complete.log"' in rendered
    assert "AUTHORIZATION: basic [REDACTED]" in rendered
    assert "x-access-token:[REDACTED]" in rendered

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "output=\"$(bash scripts/scheduled_worker_b_v2_resilient.sh 2>&1)\"" in workflow
    assert "/^B1_TERMINAL_COMPLETION_DIAGNOSTIC_BEGIN$/,/^B1_TERMINAL_COMPLETION_DIAGNOSTIC_END$/p" in workflow
    assert "printf '%s\\n' \"$diagnostic\"" in workflow


def test_terminal_failure_status_uses_only_allowlisted_fingerprints(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    expected = {
        "RESULT_IDENTITY_MISMATCH",
        "RESULT_ROLE_MISMATCH",
        "RESULT_FIELDS_MISMATCH",
        "CANDIDATE_MISMATCH",
        "IMMUTABLE_RUNTIME_COLLISION",
        "RUNTIME_CAS_CONFLICT",
        "RESULT_BLOB_MISMATCH",
        "RESULT_BLOB_LOOKUP_INVALID",
        "RESULT_BLOB_AUTH_MISSING",
        "CLAIM_VALIDATION",
        "OTHER_CONNECTED_RUNTIME_ERROR",
        "UNKNOWN",
    }
    for fingerprint in expected:
        assert fingerprint in rendered
    assert 'fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION_${completion_class}"' in rendered
    assert "complete.log" not in re.search(
        r'fail_closed "FAIL_CLOSED_B1_TERMINAL_COMPLETION_\$\{completion_class\}"', rendered
    ).group(0)


def test_semantic_worker_error_persists_only_allowlisted_metadata_fingerprint(tmp_path: Path) -> None:
    rendered = _render_resilient_script(tmp_path)
    expected = {
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
        "UNKNOWN_WORKER_ERROR",
    }
    for fingerprint in expected:
        assert fingerprint in rendered
    assert 'json.load(open(sys.argv[1], encoding="utf-8")).get("error_code")' in rendered
    assert 'Provider-portable assurance worker failed; error_code=${semantic_failure_class}; PASS is forbidden.' in rendered
    # Raw model/provider content remains private; only inference_worker metadata
    # error_code is promoted into the canonical finding.
    generic_block = rendered[rendered.index("semantic_failure_class=UNKNOWN_WORKER_ERROR"):rendered.index("outcome=\"$(python -", rendered.index("semantic_failure_class=UNKNOWN_WORKER_ERROR"))]
    assert "model.log" not in generic_block
