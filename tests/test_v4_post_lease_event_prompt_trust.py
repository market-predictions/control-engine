from __future__ import annotations

import pytest

from scripts import validate_private_control_v4 as validator


HISTORICAL_POST_LEASE_PROMPT_SHA = "f9d3b1f1158aa0c84b486120f22b5173417f54e7"


def _trusted_current_prompt() -> str:
    return "\n".join(
        (
            *validator.CARRIER_PROMPT_REQUIRED_MARKERS,
            *validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_TIMESTAMP_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
        )
    )


def test_post_lease_predecessor_prompt_is_historical_and_not_current_trust() -> None:
    assert HISTORICAL_POST_LEASE_PROMPT_SHA in validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current canonical EVENT wire contract",
    ):
        validator._validate_prompt_trust(
            _trusted_current_prompt(),
            HISTORICAL_POST_LEASE_PROMPT_SHA,
        )


def test_current_canonical_prompt_requires_every_post_lease_liveness_marker() -> None:
    for marker in validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS:
        prompt = _trusted_current_prompt().replace(marker, "", 1)
        with pytest.raises(
            validator.ValidationError,
            match="canonical EVENT Runner prompt lacks post-lease recovery markers",
        ):
            validator._validate_prompt_trust(
                prompt,
                validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
            )


def test_unrecognized_prompt_blob_remains_fail_closed() -> None:
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust(_trusted_current_prompt(), "0" * 40)
