import pytest

from scripts import validate_private_control_v4 as validator


EXPECTED_CARRIER_PROMPT_MARKERS = (
    "CONTROL_V4_RUNTIME_TICK",
    "CONTROL_V4_RUNTIME_EVENT",
    "market-predictions/control-engine",
    "issue **#106**",
    "MUST NOT depend on direct Scheduled access to private",
    "integration_enabled=false",
    "candidate-less `BUILD` cannot be executed safely from carrier V1 alone; submit `YIELD`",
    "Fresh-holder and immediate pre-effect private-authority revalidation",
    "initial acquisition TICK",
    "no more than **660 seconds old**",
    "must not reset or renew this 660-second clock",
    "second same-`run_id` TICK",
    "no more than **15 seconds old**",
    "bounded to **300 seconds or less**",
    "it **must not** perform a target write",
    "submit `YIELD` for the current exact holder",
    "create a new unique `run_id` and submit a new initial acquisition TICK",
)


def _carrier_prompt() -> str:
    return "\n".join(EXPECTED_CARRIER_PROMPT_MARKERS)


def test_current_and_tick_age_repaired_prompt_hashes_are_the_only_transition_anchors():
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "7fe88ba0fdd96c7681346c926aa9671fabf3256c"
    assert validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA == "3492644d3cbf37cb273ad262c4f2129cde9a20ef"
    assert validator.CARRIER_PROMPT_REQUIRED_MARKERS == EXPECTED_CARRIER_PROMPT_MARKERS

    validator._validate_prompt_trust(
        "current reviewed prompt",
        validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
    )
    validator._validate_prompt_trust(
        _carrier_prompt(),
        validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA,
    )


@pytest.mark.parametrize(
    "superseded_hash",
    [
        "249c278d6e0d0e03f651fc9d45ec948a55b2a531",
        "51891935b53a44f195d8f3aac1a8cfe31170be04",
        "1ae9f3f982f2c42c2ff3354f4552e0650f321145",
    ],
)
def test_superseded_carrier_prompt_hashes_fail_closed(superseded_hash):
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust(_carrier_prompt(), superseded_hash)


def test_tick_age_repaired_prompt_hash_requires_every_fail_closed_marker():
    for marker in EXPECTED_CARRIER_PROMPT_MARKERS:
        # Remove every textual occurrence so substring overlap in another marker
        # cannot make this negative test pass accidentally.
        text = _carrier_prompt().replace(marker, "REMOVED_MARKER")
        with pytest.raises(
            validator.ValidationError,
            match="carrier-bound Runner prompt lacks required fail-closed transport markers",
        ):
            validator._validate_prompt_trust(
                text,
                validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA,
            )


def test_unknown_prompt_hash_fails_closed_even_with_carrier_markers():
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust(_carrier_prompt(), "f" * 40)
