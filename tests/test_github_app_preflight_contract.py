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


def test_lifecycle_workflow_runs_preflight_before_ephemeral_token_and_state_mutation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    preflight = text.index("Preflight GitHub App identity and installation")
    token = text.index("Create short-lived private-state token")
    reconcile = text.index("Reconcile canonical private runtime state")
    claim = text.index("Persist exact preferred canonical A1 claim")
    assert preflight < token < reconcile < claim
    assert "steps.app-token.outputs.token" in text
    assert "'scripts/github_app_preflight.sh'" not in text  # push wake is bounded to actuator changes
    assert "bash -n scripts/github_app_preflight.sh" in text
    assert "CONTROL_CLOUDFLARE_API_TOKEN" not in text
    assert "CONTROL_CLOUDFLARE_ACCOUNT_ID" not in text
