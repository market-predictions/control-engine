from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "control-v4-authority-adoption.yml"


def test_adoption_uses_bounded_direct_git_ref_readback_after_update_refs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "def read_main_ref_sha():" in text
    assert "git/ref/heads/main" in text
    assert "for attempt in range(6):" in text
    assert "time.sleep(0.5)" in text
    assert "if adopted == CANDIDATE:" in text
    assert "mandatory exact authority post-adoption readback failed" in text
