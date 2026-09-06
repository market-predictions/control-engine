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
    "use the connected GitHub app",
    "public transport entrypoint is mandatory",
    "must not silently exit",
    "at least **120 seconds old**",
    "**MUST immediately post exactly one recovery replay**",
    "exact same TICK body and same `run_id`",
    "**MUST post one fresh initial TICK**",
    "performs exactly one public transport write",
    "earliest TICK for that `run_id` remains the sole initial acquisition TICK and lease-freshness anchor",
    "must be no more than **660 seconds old**",
    "recovery replays and later revalidation TICKs **must not reset or renew this 660-second clock**",
    "no more than **15 seconds old**",
    "bounded to **300 seconds or less**",
    "it **must not** perform a target write",
    "submit `YIELD` for the current exact holder",
    "create a new unique `run_id` and submit a new initial acquisition TICK",
)


def _carrier_prompt() -> str:
    return "\n".join(EXPECTED_CARRIER_PROMPT_MARKERS)


def test_current_and_recovery_prompt_hashes_are_the_only_transition_anchors():
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "4bc8ce5a73e1238427b1ce999be5cd5a6378988c"
    assert validator.REVIEWED_CARRIER_RUNNER_PROMPT_BLOB_SHA == "804c8570141934c5a0b5fa86583c867995ce51f4"
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
        "7fe88ba0fdd96c7681346c926aa9671fabf3256c",
        "249c278d6e0d0e03f651fc9d45ec948a55b2a531",
        "3492644d3cbf37cb273ad262c4f2129cde9a20ef",
        "1ae9f3f982f2c42c2ff3354f4552e0650f321145",
        "6c7c3cc41a7c97cb551e4d55d3d309a4d913cfe3",
    ],
)
def test_superseded_carrier_prompt_hashes_fail_closed(superseded_hash):
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust(_carrier_prompt(), superseded_hash)


def test_recovery_prompt_hash_requires_every_fail_closed_marker():
    for marker in EXPECTED_CARRIER_PROMPT_MARKERS:
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
