import pytest

from scripts import validate_private_control_v4 as validator


EXPECTED_STATELESS_TRANSPORT_MARKERS = (
    "CONTROL_V4_RUNTIME_TICK",
    "CONTROL_V4_RUNTIME_EVENT",
    "market-predictions/control-engine",
    "issue **#106**",
    "MUST NOT depend on direct Scheduled access to private",
    "integration_enabled=false",
    "candidate-less `BUILD` cannot be executed safely from carrier V1 alone; submit `YIELD`",
    "The schedule is a wake-up mechanism, not runtime state.",
    "never reconstruct Control liveness, holder state or recovery state from public comment history",
    "Then create one new unique `run_id` for this invocation in the exact generation-bound format and an empty invocation-local `yielded_task_tokens` set.",
    "Immediately post one fresh initial `CONTROL_V4_RUNTIME_TICK`",
    "Do **not** scan issue #106 history first and do not replay an older TICK or EVENT.",
    "`NO_WORK` or `BUSY` ends this invocation without mutation.",
    "carrier expired-lock recovery are the only cross-invocation holder-recovery mechanism",
    "Do not replay the command and do not derive recovery state from issue history.",
    "The next normal Scheduled invocation starts with a fresh TICK",
)


def test_current_state_first_transport_markers_are_the_canonical_prompt_contract():
    assert validator.STATELESS_TRANSPORT_PROMPT_REQUIRED_MARKERS == EXPECTED_STATELESS_TRANSPORT_MARKERS
    assert validator.REVIEWED_RUNNER_PROMPT_BLOB_SHA == "2cc54e0fbf21b93609d3c4e093bcdacfb566fcb0"


def test_command_binding_markers_cover_generation_object_and_exact_comment_correlation():
    markers = validator.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS
    assert "runner_command_generation=965d03fc71359d0e" in markers
    assert "6a9a7e0b18b08191876c134d83cfbba2" in markers
    assert any("command_comment_id" in marker for marker in markers)
    assert "no later same-`run_id` Control command" in markers
    assert any("previously unused" in marker for marker in markers)
    assert any("transition time" in marker for marker in markers)
    assert "persists no transport cursor or ledger" in markers


def test_live_tick_responsibility_markers_close_abandoned_fresh_tick_window():
    markers = validator.LIVE_TICK_RESPONSIBILITY_PROMPT_REQUIRED_MARKERS
    assert "### Live-TICK responsibility window" in markers
    assert any("do not classify its result as missing" in marker for marker in markers)
    assert any("created_at` has passed 120 seconds" in marker for marker in markers)
    assert "Control V4 runtime command <command_comment_id>" in markers
    assert "status `completed`" in markers
    assert any("final exact-command result read" in marker for marker in markers)
    assert "The age check alone is never sufficient" in markers
    assert any("Never post a replacement TICK" in marker for marker in markers)
    assert any("carrier-run ledger or runtime state" in marker for marker in markers)


def test_holder_closeout_markers_are_part_of_current_prompt_trust():
    markers = validator.HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS
    assert "HOLDER CLOSEOUT OBLIGATION" in markers
    assert "### Holder closeout after WORK" in markers
    assert any("EVENT returns `WORK`" in marker for marker in markers)
    assert any("CANDIDATE_READY" in marker for marker in markers)
    assert any("YIELD" in marker for marker in markers)
    assert any("normal invocation exit" in marker for marker in markers)
    assert any("missing or ambiguous EVENT" in marker for marker in markers)


@pytest.mark.parametrize("obsolete_hash", sorted(validator.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS))
def test_predecessor_prompt_hashes_are_obsolete_current_trust(obsolete_hash):
    with pytest.raises(
        validator.ValidationError,
        match="obsolete Runner prompt is not trusted by the current stateless transport contract",
    ):
        validator._validate_prompt_trust("\n".join(EXPECTED_STATELESS_TRANSPORT_MARKERS), obsolete_hash)


def test_unknown_prompt_hash_fails_closed_even_with_current_markers():
    with pytest.raises(
        validator.ValidationError,
        match="Runner prompt blob differs from exact trusted reviewed V4 prompt contract",
    ):
        validator._validate_prompt_trust("\n".join(EXPECTED_STATELESS_TRANSPORT_MARKERS), "f" * 40)
