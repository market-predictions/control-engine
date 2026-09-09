from pathlib import Path

from control_engine.v4_runtime_protocol import CANONICAL_RUNNER_PROMPT_BLOB_SHA
import scripts.validate_private_control_v4 as private_v4


GENERATION = "dcd5dd2495113a68"
PROMPT_SHA = "3e577ae37c46d39b07e8b1bb9a19d59d4bddd242"
PREDECESSOR_PROMPT_SHA = "2cc54e0fbf21b93609d3c4e093bcdacfb566fcb0"


def test_holder_closeout_generation_and_hash_are_single_current_trust_identity():
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text(encoding="utf-8")
    validator = Path("scripts/validate_private_control_v4.py").read_text(encoding="utf-8")

    assert CANONICAL_RUNNER_PROMPT_BLOB_SHA == PROMPT_SHA
    assert private_v4.REVIEWED_RUNNER_PROMPT_BLOB_SHA == PROMPT_SHA
    assert PREDECESSOR_PROMPT_SHA in private_v4.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS
    assert f":{GENERATION}:[0-9a-f]{{32}}$" in workflow
    assert f"runner_command_generation={GENERATION}" in private_v4.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS
    assert f"v4:6a9a7e0b18b08191876c134d83cfbba2:{GENERATION}:<32-lowercase-hex-random>" in private_v4.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS
    assert "965d03fc71359d0e" not in workflow


def test_reviewed_private_prompt_must_encode_atomic_event_holder_boundary():
    required = set(private_v4.HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS)

    assert "HOLDER CLOSEOUT OBLIGATION" in required
    assert "### Holder closeout after WORK — atomic EVENT boundary" in required
    assert "Every accepted semantic EVENT is an **ATOMIC HOLDER BOUNDARY**" in required
    assert "the event transition and release of that exact holder are committed in the same private queue mutation/CAS" in required
    assert "Under the current contract an accepted EVENT must never return `WORK`." in required
    assert "`READY` means the task reached READY with no holder; `YIELDED` means the EVENT transition completed and the holder was atomically released." in required
    assert "No normal invocation is required to retain a private holder across semantic phases." in required
    assert "A missing or ambiguous EVENT result remains exceptional fail-closed transport ambiguity" in required
    assert "never infer private holder state from public history" in required


def test_progress_and_wait_boundaries_are_explicitly_distinguished():
    required = set(private_v4.POST_YIELD_CONTINUATION_PROMPT_REQUIRED_MARKERS)
    assert "### Progress EVENT versus wait EVENT continuation" in required
    assert "Progress EVENTs `CANDIDATE_READY`, `INTERNAL_PASS`, `INTERNAL_REPAIR`, and `EXTERNAL_FINDING`" in required
    assert "**do not** add that task token to `yielded_task_tokens`" in required
    assert "Wait/release EVENTs `YIELD` and `REVIEW_UNAVAILABLE`" in required
    assert "`EXTERNAL_REQUESTED` is also a wait boundary" in required
    assert "A fresh same-run TICK posted after a completed EVENT is later than that EVENT and may reacquire current truth" in required


def test_closeout_contract_reuses_existing_events_instead_of_new_runtime_state():
    protocol = Path("control_engine/v4_runtime_protocol.py").read_text(encoding="utf-8")
    carrier = Path("scripts/control_v4_runtime_carrier.py").read_text(encoding="utf-8")

    assert '"CANDIDATE_READY"' in protocol
    assert '"YIELD"' in protocol
    assert "candidate_ready_v4" in carrier
    assert "yield_holder_v4" in carrier
    assert "_release_event_holder_boundary" in carrier
    assert "lease renewal" not in protocol.lower()
    assert "recovery ledger" not in protocol.lower()
    assert "cancellation protocol" not in protocol.lower()


def test_multiline_wire_fix_remains_intact_during_generation_rotation():
    protocol = Path("control_engine/v4_runtime_protocol.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text(encoding="utf-8")

    assert 'TICK_NEWLINE_PREFIX = "CONTROL_V4_RUNTIME_TICK\\n"' in protocol
    assert 'EVENT_NEWLINE_PREFIX = "CONTROL_V4_RUNTIME_EVENT\\n"' in protocol
    assert "parse_public_command(raw_command)" in workflow
