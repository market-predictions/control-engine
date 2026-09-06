import pytest

from scripts import validate_private_control_v4 as validator


def _trusted_prompt() -> str:
    return "\n".join(
        validator.CARRIER_PROMPT_REQUIRED_MARKERS
        + validator.EXACT_COMMENT_TIME_PROMPT_REQUIRED_MARKERS
    )


def test_exact_comment_time_prompt_hash_is_trusted_only_with_all_required_markers():
    assert validator.REVIEWED_EXACT_COMMENT_TIME_RUNNER_PROMPT_BLOB_SHA == (
        "fe269bf84744629eca133937854ee284239cbcc9"
    )
    validator._validate_prompt_trust(
        _trusted_prompt(),
        validator.REVIEWED_EXACT_COMMENT_TIME_RUNNER_PROMPT_BLOB_SHA,
    )

    for marker in validator.EXACT_COMMENT_TIME_PROMPT_REQUIRED_MARKERS:
        with pytest.raises(
            validator.ValidationError,
            match="exact-comment-time Runner prompt lacks required fail-closed timestamp markers",
        ):
            validator._validate_prompt_trust(
                _trusted_prompt().replace(marker, "REMOVED_MARKER"),
                validator.REVIEWED_EXACT_COMMENT_TIME_RUNNER_PROMPT_BLOB_SHA,
            )
