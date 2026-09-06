import pytest

from scripts import validate_private_control_v4 as validator


def _carrier_prompt() -> str:
    return "\n".join(validator.CARRIER_PROMPT_REQUIRED_MARKERS)


def test_current_and_exact_carrier_prompt_hashes_are_the_only_transition_anchors():
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "7fe88ba0fdd96c7681346c926aa9671fabf3256c"
    assert validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA == "1ae9f3f982f2c42c2ff3354f4552e0650f321145"
    validator._validate_prompt_trust("current reviewed prompt", validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA)
    validator._validate_prompt_trust(_carrier_prompt(), validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA)


def test_carrier_prompt_hash_requires_all_fail_closed_transport_markers():
    for marker in validator.CARRIER_PROMPT_REQUIRED_MARKERS:
        text = _carrier_prompt().replace(marker, "REMOVED_MARKER", 1)
        with pytest.raises(
            validator.ValidationError,
            match="carrier-bound Runner prompt lacks required fail-closed transport markers",
        ):
            validator._validate_prompt_trust(text, validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA)


def test_unknown_prompt_hash_fails_closed_even_with_carrier_markers():
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust(_carrier_prompt(), "f" * 40)
