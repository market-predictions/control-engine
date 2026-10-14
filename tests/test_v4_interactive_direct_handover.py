"""Contract checks for the direct ChatGPT Control handover path.

This tests source wiring only; a live owner-dispatch and V4 state transition
are required before claiming end-to-end success.
"""
from pathlib import Path

WORKFLOW = Path(".github/workflows/control-v4-runtime-carrier.yml")


def _job():
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("\n  interactive-control-start:\n", 1)[1]


def test_direct_dispatch_is_default_and_legacy_work_opt_in():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "default: control-go" in workflow
    old = workflow.split("\n  interactive-resume:\n", 1)[1].split(
        "\n  interactive-control-start:\n", 1
    )[0]
    assert "inputs.mode == 'legacy-work'" in old
    job = _job()
    assert "inputs.mode == 'control-go'" in job
    assert "github.run_attempt == 1" in job
    assert "github.actor == 'market-predictions'" in job


def test_direct_path_uses_existing_carrier_and_no_second_authority():
    job = _job()
    assert "python scripts/control_v4_runtime_carrier.py" in job
    assert "CONTROL_V4_RUNTIME_TICK" in job
    assert "v41:gh:" in job
    assert "CONTROL_INTERACTIVE_HANDOVER_V1" in job
    assert "steps.carrier.outputs.result_json" in job
    assert "steps.private-token.outputs.token" in job
    for forbidden in (
        "CONTROL_INTERACTIVE_WAKE_V2",
        "CONTROL_INTERACTIVE_READY_V2",
        "Work readiness",
        "AGENT_TOKEN",
        "permission-pull-requests: write",
        "CONTROL_V4_RUNTIME_TICK_AUTO",
        "CONTROL_RUNTIME_AUTHORITY_V4.json",
        "CONTROL_RUNNER_V4.json",
    ):
        assert forbidden not in job


def test_handover_is_one_transport_receipt_not_a_semantic_pass():
    job = _job()
    assert 'result.get("result") not in {"WORK", "BUSY", "NO_WORK", "UNSUPPORTED"}' in job
    assert '"CONTROL_INTERACTIVE_HANDOVER_V1' in job
    assert "posted.get(\"body\") != body" in job
    assert "issues/106/comments" in job
    assert "INTERNAL_PASS" not in job
    assert "EXTERNAL_PASS" not in job


def test_failed_receipt_publication_releases_existing_holder():
    job = _job()
    assert 'id: handover' in job
    assert 'steps.handover.outcome != \'success\'' in job
    assert '"CONTROL_V4_RUNTIME_EVENT "' in job
    assert 'command["event"] = "YIELD"' in job
    assert 'from scripts.control_v4_runtime_carrier import main' in job

def test_holder_release_failure_is_reported_not_silently_accepted():
    job = _job().split("      - name: Release holder if handover publication failed", 1)[1]
    assert 'lines.get("ok") != "true"' in job
    assert 'result.get("result") != "YIELDED"' in job
    assert 'result.get("run_id") != capsule["run_id"]' in job
    assert 'raise SystemExit("holder release not confirmed")' in job
    assert 'raise SystemExit("holder release returned no matching YIELDED result")' in job


def test_ambiguous_handover_is_reconciled_before_release():
    job = _job()
    publication = job.split("      - name: Publish bounded handover", 1)[1].split(
        "      - name: Release holder", 1)[0]
    release = job.split("      - name: Release holder", 1)[1]
    assert "def verify_existing():" in publication
    assert 'item.get("body") == body' in publication
    assert 'item.get("performed_via_github_app")' in publication
    assert 'receipt_id = verify_existing()' in publication
    assert 'if receipt_id is None:' in publication
    assert 'output.write("safe_to_yield=true' in publication
    assert "handover uncertain; preserve holder until lease expiry" in publication
    assert "steps.handover.outputs.safe_to_yield == 'true'" in release
