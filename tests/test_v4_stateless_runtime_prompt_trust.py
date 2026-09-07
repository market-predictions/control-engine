from __future__ import annotations

import pytest

from scripts import validate_private_control_v4 as validator


def _trusted_prompt() -> str:
    return "\n".join(
        (
            *validator.CARRIER_PROMPT_REQUIRED_MARKERS,
            *validator.STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS,
            *validator.TARGET_EFFECT_PROMPT_REQUIRED_MARKERS,
            *validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS,
        )
    )


def test_stateless_runtime_prompt_has_one_exact_current_trust_anchor() -> None:
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "f415d7c7c0c52ea7d8f338bb361bbbb8b15095d6"
    validator._validate_prompt_trust(_trusted_prompt(), validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA)


@pytest.mark.parametrize("prompt_oid", sorted(validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS))
def test_all_predecessor_runner_prompts_are_rejected(prompt_oid: str) -> None:
    with pytest.raises(validator.ValidationError, match="obsolete Runner prompt is not trusted"):
        validator._validate_prompt_trust(_trusted_prompt(), prompt_oid)


@pytest.mark.parametrize(
    "markers,error",
    [
        (validator.CARRIER_PROMPT_REQUIRED_MARKERS, "carrier boundary markers"),
        (validator.STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS, "stateless current-state transport markers"),
        (validator.TARGET_EFFECT_PROMPT_REQUIRED_MARKERS, "target-effect freshness markers"),
        (validator.CANONICAL_EVENT_FAIRNESS_PROMPT_REQUIRED_MARKERS, "exact EVENT/fairness markers"),
    ],
)
def test_current_prompt_fails_closed_when_required_semantics_are_removed(markers, error) -> None:
    for marker in markers:
        prompt = _trusted_prompt().replace(marker, "")
        with pytest.raises(validator.ValidationError, match=error):
            validator._validate_prompt_trust(prompt, validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA)


@pytest.mark.parametrize("stale_marker", validator.FORBIDDEN_HISTORY_RECOVERY_PROMPT_MARKERS)
def test_obsolete_history_recovery_semantics_are_forbidden(stale_marker: str) -> None:
    with pytest.raises(validator.ValidationError, match="obsolete public-history recovery state"):
        validator._validate_prompt_trust(
            _trusted_prompt() + "\n" + stale_marker,
            validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA,
        )
