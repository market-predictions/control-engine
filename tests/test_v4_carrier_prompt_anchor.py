import pytest

from scripts import validate_private_control_v4 as validator


EXPECTED_STATELESS_PROMPT_MARKERS = (
    "CONTROL_V4_RUNTIME_TICK",
    "CONTROL_V4_RUNTIME_EVENT",
    "market-predictions/control-engine",
    "issue **#106**",
    "MUST NOT depend on direct Scheduled access to private",
    "integration_enabled=false",
    "candidate-less `BUILD` cannot be executed safely from carrier V1 alone; submit `YIELD`",
    "**Transport history is evidence, never recovery state.**",
    "Every Scheduled invocation starts from current authoritative state, not previous transport history",
    "Post exactly one fresh `CONTROL_V4_RUNTIME_TICK`",
    "`command_comment_id` exactly equals that command-comment id",
    "do not scan prior invocations to reconstruct transport state",
    "`WORK` with `acquired_now=true`",
    "`WORK` with `acquired_now=false`",
    "Do not replay the command and do not reconstruct prior transport",
    "The next normal Scheduled invocation starts again with one fresh TICK",
    "must be no more than **660 seconds old**",
    "no more than **15 seconds old**",
    "within **300 seconds**",
    "The private 5400-second lock lease is fixed and non-renewable",
    "If resumed work (`acquired_now=false`) needs a target effect",
)


def test_current_stateless_transport_markers_are_the_canonical_prompt_contract() -> None:
    assert validator.STATELESS_HANDSHAKE_PROMPT_REQUIRED_MARKERS == EXPECTED_STATELESS_PROMPT_MARKERS
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "09d50ff9f2c797b22f85f88314d562d7306abc53"


@pytest.mark.parametrize("obsolete_hash", sorted(validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS))
def test_all_predecessor_prompt_hashes_are_obsolete_current_trust(obsolete_hash: str) -> None:
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current stateless V4 transport contract",
    ):
        validator._validate_prompt_trust("\n".join(EXPECTED_STATELESS_PROMPT_MARKERS), obsolete_hash)


def test_unknown_prompt_hash_fails_closed_even_with_stateless_markers() -> None:
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust("\n".join(EXPECTED_STATELESS_PROMPT_MARKERS), "f" * 40)
