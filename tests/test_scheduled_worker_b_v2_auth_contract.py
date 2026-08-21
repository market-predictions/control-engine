from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scheduled_worker_b_v2.sh"


def test_connected_runtime_auth_is_ephemeral_and_single_path() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "git -C \"$STATE_DIR\" config http.https://github.com/.extraheader" not in text
    assert "GIT_CONFIG_COUNT=1" in text
    assert "GIT_CONFIG_KEY_0=http.https://github.com/.extraheader" in text
    assert "GIT_CONFIG_VALUE_0=\"$AUTH_HEADER\"" in text
    assert "connected_runtime claim" in text
    assert "connected_runtime complete" in text


def test_inference_never_receives_private_github_token() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("env -i")
    end = text.index("model_rc=$?", start)
    assert "CONTROL_GITHUB_WRITE_TOKEN" not in text[start:end]
    assert "GH_TOKEN" not in text[start:end]
