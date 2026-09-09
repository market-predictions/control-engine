import pytest

from scripts import control_v4_runtime_carrier as carrier


def test_runtime_ref_readback_tolerates_short_git_ref_propagation(monkeypatch):
    expected = "a" * 40
    observed = iter(["b" * 40, "b" * 40, expected])
    sleeps = []

    monkeypatch.setattr(carrier, "_git_ref_head", lambda _branch: next(observed))
    monkeypatch.setattr(carrier.time, "sleep", lambda seconds: sleeps.append(seconds))

    carrier._await_git_ref_head(carrier.RUNTIME_BRANCH, expected)

    assert sleeps == [carrier.REF_READBACK_DELAY_SECONDS, carrier.REF_READBACK_DELAY_SECONDS]


def test_runtime_ref_readback_is_bounded_and_fails_closed(monkeypatch):
    expected = "a" * 40
    sleeps = []

    monkeypatch.setattr(carrier, "_git_ref_head", lambda _branch: "b" * 40)
    monkeypatch.setattr(carrier.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(carrier.CarrierError, match="mandatory private control-runtime-state ref readback failed"):
        carrier._await_git_ref_head(carrier.RUNTIME_BRANCH, expected)

    assert len(sleeps) == carrier.REF_READBACK_ATTEMPTS - 1


def test_runtime_write_uses_direct_git_ref_readback_helper():
    text = carrier.__file__
    assert text.endswith("control_v4_runtime_carrier.py")
    source = open(text, encoding="utf-8").read()
    assert "_await_git_ref_head(RUNTIME_BRANCH, new_commit)" in source
    assert "_git_ref_head(\"main\") != state[\"main_sha\"]" in source
    assert "git/ref/heads/" in source
    assert "if _branch_head(RUNTIME_BRANCH) != new_commit" not in source
