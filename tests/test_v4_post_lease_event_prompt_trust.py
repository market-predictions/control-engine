from __future__ import annotations

import pytest

from scripts import validate_private_control_v4 as validator


def _trusted_post_lease_prompt() -> str:
    return "\n".join(
        (*validator.CARRIER_PROMPT_REQUIRED_MARKERS, *validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS)
    )


def test_post_lease_event_recovery_prompt_has_exact_public_trust_anchor() -> None:
    assert (
        validator.REVIEWED_POST_LEASE_EVENT_RECOVERY_RUNNER_PROMPT_BLOB_SHA
        == "f9d3b1f1158aa0c84b486120f22b5173417f54e7"
    )
    validator._validate_prompt_trust(
        _trusted_post_lease_prompt(),
        validator.REVIEWED_POST_LEASE_EVENT_RECOVERY_RUNNER_PROMPT_BLOB_SHA,
    )


def test_post_lease_event_recovery_prompt_fails_closed_without_each_liveness_marker() -> None:
    for marker in validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS:
        prompt = _trusted_post_lease_prompt().replace(marker, "", 1)
        with pytest.raises(
            validator.ValidationError,
            match="post-lease EVENT recovery Runner prompt lacks required fail-closed liveness markers",
        ):
            validator._validate_prompt_trust(
                prompt,
                validator.REVIEWED_POST_LEASE_EVENT_RECOVERY_RUNNER_PROMPT_BLOB_SHA,
            )


def test_unrecognized_prompt_blob_remains_fail_closed() -> None:
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust(_trusted_post_lease_prompt(), "0" * 40)
