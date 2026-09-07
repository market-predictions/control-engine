from __future__ import annotations

import pytest

from scripts import validate_private_control_v4 as validator


def _trusted_prompt() -> str:
    return "\n".join(
        (
            *validator.STATELESS_HANDSHAKE_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
        )
    )


def test_canonical_event_fairness_prompt_has_exact_public_trust_anchor() -> None:
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "09d50ff9f2c797b22f85f88314d562d7306abc53"
    validator._validate_prompt_trust(
        _trusted_prompt(),
        validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
    )


@pytest.mark.parametrize("prompt_oid", sorted(validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS))
def test_all_predecessor_runner_prompt_hashes_are_rejected_after_stateless_cutover(prompt_oid: str) -> None:
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current stateless V4 transport contract",
    ):
        validator._validate_prompt_trust("", prompt_oid)


@pytest.mark.parametrize(
    "markers,error",
    [
        (
            validator.STATELESS_HANDSHAKE_PROMPT_REQUIRED_MARKERS,
            "Runner prompt lacks required stateless current-state handshake markers",
        ),
        (
            validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
            "Runner prompt lacks exact EVENT wire/fairness markers",
        ),
    ],
)
def test_current_prompt_fails_closed_without_each_required_marker(markers, error) -> None:
    for marker in markers:
        prompt = _trusted_prompt().replace(marker, "")
        with pytest.raises(validator.ValidationError, match=error):
            validator._validate_prompt_trust(
                prompt,
                validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
            )
