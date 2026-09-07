from __future__ import annotations

import pytest

from scripts import validate_private_control_v4 as validator


def _trusted_prompt() -> str:
    return "\n".join(
        (
            *validator.CARRIER_PROMPT_REQUIRED_MARKERS,
            *validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_TIMESTAMP_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
        )
    )


def test_canonical_event_fairness_prompt_has_exact_public_trust_anchor() -> None:
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "0a536651ad3096e2c6de44e6dd25d0cea14ec8e1"
    validator._validate_prompt_trust(
        _trusted_prompt(),
        validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
    )


@pytest.mark.parametrize("prompt_oid", sorted(validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS))
def test_all_predecessor_runner_prompt_hashes_are_rejected_after_wire_cutover(prompt_oid: str) -> None:
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current canonical EVENT wire contract",
    ):
        validator._validate_prompt_trust("", prompt_oid)


@pytest.mark.parametrize(
    "markers,error",
    [
        (validator.CARRIER_PROMPT_REQUIRED_MARKERS, "canonical EVENT Runner prompt lacks required carrier transport markers"),
        (validator.POST_LEASE_EVENT_RECOVERY_PROMPT_REQUIRED_MARKERS, "canonical EVENT Runner prompt lacks post-lease recovery markers"),
        (validator.CANONICAL_EVENT_TIMESTAMP_PROMPT_REQUIRED_MARKERS, "canonical EVENT Runner prompt lacks exact-comment timestamp markers"),
        (validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS, "canonical EVENT Runner prompt lacks exact wire/fairness markers"),
    ],
)
def test_canonical_event_fairness_prompt_fails_closed_without_each_required_marker(markers, error) -> None:
    for marker in markers:
        # Remove every occurrence: some canonical marker phrases are intentionally
        # repeated across marker families, and leaving another occurrence would
        # not actually test absence of the required semantic marker.
        prompt = _trusted_prompt().replace(marker, "")
        with pytest.raises(validator.ValidationError, match=error):
            validator._validate_prompt_trust(
                prompt,
                validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
            )
