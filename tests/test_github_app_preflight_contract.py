from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "github_app_preflight.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"


def test_preflight_classifies_configuration_auth_and_installation_failures() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "APP_ID_MISSING_OR_INVALID",
        "APP_PRIVATE_KEY_MISSING",
        "APP_PRIVATE_KEY_PARSE_FAILED",
        "APP_AUTH_FAILED",
        "APP_INSTALLATION_LOOKUP_FAILED",
        "APP_INSTALLATION_NOT_FOUND",
        "APP_AUTH_PREFLIGHT_OK",
    ):
        assert marker in text
    assert "https://api.github.com/app" in text
    assert "https://api.github.com/app/installations?per_page=100" in text
    assert "openssl pkey" in text
    assert "openssl dgst -sha256 -sign" in text


def test_preflight_never_prints_secret_material() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "set -x" not in text
    assert 'echo "$PRIVATE_KEY"' not in text
    assert 'printf \'%s\\n\' "$PRIVATE_KEY" > "$KEY_FILE"' in text
    assert "cat \"$KEY_FILE\"" not in text
    assert "cat \"$APP_JSON\"" not in text
    assert "cat \"$INSTALL_JSON\"" not in text


def test_workflow_runs_preflight_before_token_integration_and_model_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    preflight = text.index("Preflight GitHub App identity and installation")
    token = text.index("Create short-lived Control GitHub App token")
    integration = text.index("Execute preferred deterministic PROJECT_INTEGRATION")
    runtime = text.index("Reconcile, claim and execute one model-driven A1 task")
    assert preflight < token < integration < runtime
    assert "steps.app-preflight.outcome == 'success'" in text
    assert "PREFLIGHT_CLASS: ${{ steps.app-preflight.outputs.status_class }}" in text
    assert "${PREFLIGHT_CLASS:-APP_PREFLIGHT_FAILED}" in text
    assert "'scripts/github_app_preflight.sh'" in text
