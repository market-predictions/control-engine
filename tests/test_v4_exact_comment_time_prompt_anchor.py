import pytest

from scripts import validate_private_control_v4 as validator


HISTORICAL_EXACT_COMMENT_TIME_PROMPT_SHA = "fe269bf84744629eca133937854ee284239cbcc9"


def test_exact_comment_time_prompt_is_historical_and_not_current_trust():
    assert HISTORICAL_EXACT_COMMENT_TIME_PROMPT_SHA in validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current canonical EVENT wire contract",
    ):
        validator._validate_prompt_trust(
            "\n".join(validator.CANONICAL_EVENT_TIMESTAMP_PROMPT_REQUIRED_MARKERS),
            HISTORICAL_EXACT_COMMENT_TIME_PROMPT_SHA,
        )


def test_current_canonical_prompt_still_requires_exact_comment_time_markers():
    prompt = "\n".join(
        (
            *validator.CARRIER_PROMPT_REQUIRED_MARKERS,
            *validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_TIMESTAMP_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
        )
    )
    for marker in validator.CANONICAL_EVENT_TIMESTAMP_PROMPT_REQUIRED_MARKERS:
        with pytest.raises(
            validator.ValidationError,
            match="canonical EVENT Runner prompt lacks exact-comment timestamp markers",
        ):
            validator._validate_prompt_trust(
                prompt.replace(marker, "REMOVED_MARKER", 1),
                validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
            )
