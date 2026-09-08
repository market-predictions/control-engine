from __future__ import annotations

import pytest

from scripts import validate_private_control_v4 as validator


def _trusted_prompt() -> str:
    return "\n".join(
        (
            *validator.STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS,
            *validator.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS,
            *validator.LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS,
            *validator.POST_YIELD_CONTINUATION_PROMPT_REQUIRED_MARKERS,
            *validator.TARGET_EFFECT_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
            *validator.HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS,
        )
    )


def test_stateless_runner_prompt_has_exact_public_trust_anchor() -> None:
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "2cc54e0fbf21b93609d3c4e093bcdacfb566fcb0"
    validator._validate_prompt_trust(
        _trusted_prompt(),
        validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
    )


@pytest.mark.parametrize("prompt_oid", sorted(validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS))
def test_all_predecessor_runner_prompt_hashes_are_rejected(prompt_oid: str) -> None:
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current stateless transport contract",
    ):
        validator._validate_prompt_trust("", prompt_oid)


@pytest.mark.parametrize(
    "markers,error",
    [
        (validator.STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks required state-first transport markers"),
        (validator.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks required pre-acquisition command-binding/correlation markers"),
        (validator.LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks required live-TICK responsibility markers"),
        (validator.POST_YIELD_CONTINUATION_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks required post-yield continuation markers"),
        (validator.TARGET_EFFECT_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks target-effect freshness markers"),
        (validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks canonical EVENT/fairness markers"),
        (validator.HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS, "current Runner prompt lacks holder-closeout markers"),
    ],
)
def test_stateless_runner_prompt_fails_closed_without_each_required_marker(markers, error) -> None:
    for marker in dict.fromkeys(markers):
        prompt = _trusted_prompt().replace(marker, "")
        with pytest.raises(validator.ValidationError, match=error):
            validator._validate_prompt_trust(
                prompt,
                validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
            )


@pytest.mark.parametrize("obsolete_marker", validator.OBSOLETE_TRANSPORT_RECOVERY_MARKERS)
def test_current_runner_prompt_rejects_obsolete_public_history_recovery_semantics(obsolete_marker: str) -> None:
    prompt = _trusted_prompt() + "\n" + obsolete_marker
    with pytest.raises(
        validator.ValidationError,
        match="current Runner prompt retains obsolete public-history recovery semantics",
    ):
        validator._validate_prompt_trust(
            prompt,
            validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
        )
