from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-b-v2.yml"
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"
HELPER = ROOT / "control_engine" / "scheduled_worker_b.py"


def test_legacy_provider_b_workflow_is_retired_read_only_and_nonrecurring() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "name: Retired Provider B Recovery V2" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "cron:" not in text
    assert "\n  push:" not in text
    assert "pull_request:" not in text
    assert "github.repository == 'market-predictions/control-engine'" in text
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "actions/upload-artifact" not in text
    assert "actions/cache" not in text


def test_legacy_provider_b_workflow_has_no_private_or_provider_credentials() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "CONTROL_GITHUB_APP_ID",
        "CONTROL_GITHUB_APP_PRIVATE_KEY",
        "CONTROL_GITHUB_WRITE_TOKEN",
        "CONTROL_CLOUDFLARE_API_TOKEN",
        "CONTROL_CLOUDFLARE_ACCOUNT_ID",
        "CONTROL_CLOUDFLARE_FREE_FAIL_CLOSED_ATTESTED",
        "scheduled_worker_b_v2.sh",
        "scheduled_worker_b_v2_resilient.sh",
    ):
        assert forbidden not in text


def test_retirement_proof_forbids_semantic_b_fallback_and_private_write() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "CONTROL_PROVIDER_B_RECOVERY_V2=RETIRED" in text
    assert "LEGACY_PROVIDER_B_SEMANTIC_EXECUTION=false" in text
    assert "PRIVATE_CONTROL_WRITE=false" in text
    assert "PROVIDER_FALLBACK=false" in text
    assert "B2_B3=false" in text


def test_historical_provider_b_actuator_remains_non_forceful_evidence_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'CONTROL_RUNTIME_REF="control-runtime-state"' in text
    assert "--force" not in text
    assert "pull --rebase" not in text
    assert "set -x" not in text
    # Historical implementation may remain for auditability, but the active
    # workflow above must never invoke it.
    assert "scheduled_worker_b_v2.sh" not in WORKFLOW.read_text(encoding="utf-8")


def test_b1_helper_remains_available_to_canonical_gate8_runtime_only() -> None:
    text = HELPER.read_text(encoding="utf-8")
    assert "select-b1" in text
    assert "assert-claim" in text
    assert "governance_release_assurance" in text or "ROLE_B" in text
    assert "B1" in text
