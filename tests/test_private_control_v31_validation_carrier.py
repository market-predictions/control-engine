from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "private-control-v3-1-validation.yml"
VALIDATOR = ROOT / "scripts" / "validate_private_control_v31.py"


def test_private_v31_carrier_is_read_only_and_trusted_main_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:" in workflow
    assert "github.event.comment.user.login == 'market-predictions'" in workflow
    assert "ref: main" in workflow
    assert "permission-contents: read" in workflow
    assert "permission-contents: write" not in workflow
    assert "permission-pull-requests: write" not in workflow
    assert "control-runtime-state" not in workflow
    assert "DISPATCH_QUEUE.json" not in workflow
    assert "python scripts/validate_private_control_v31.py private-candidate private-base" in workflow


def test_private_v31_validator_never_executes_candidate_code():
    text = VALIDATOR.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "importlib", "runpy", "exec(", "eval(", "os.system", "Popen"):
        assert forbidden not in text
    assert "PRIVATE_CANDIDATE_EXECUTION=false" in text
    assert "PRIVATE_RUNTIME_MUTATION=false" in text
