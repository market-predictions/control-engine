from pathlib import Path

from control_engine.v4_runtime_protocol import CANONICAL_RUNNER_PROMPT_BLOB_SHA
import scripts.validate_private_control_v4 as private_v4


GENERATION = "965d03fc71359d0e"
PROMPT_SHA = "2cc54e0fbf21b93609d3c4e093bcdacfb566fcb0"
PREDECESSOR_PROMPT_SHA = "e100b7655dd1596f0562820e55a8da2a3358a6a8"


def test_holder_closeout_generation_and_hash_are_single_current_trust_identity():
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text(encoding="utf-8")
    validator = Path("scripts/validate_private_control_v4.py").read_text(encoding="utf-8")

    assert CANONICAL_RUNNER_PROMPT_BLOB_SHA == PROMPT_SHA
    assert private_v4.REVIEWED_RUNNER_PROMPT_BLOB_SHA == PROMPT_SHA
    assert PREDECESSOR_PROMPT_SHA in private_v4.OBSOLETE_RUNNER_PROMPT_BLOB_SHAS
    assert f":{GENERATION}:[0-9a-f]{{32}}$" in workflow
    assert f"runner_command_generation={GENERATION}" in private_v4.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS
    assert f"v4:6a9a7e0b18b08191876c134d83cfbba2:{GENERATION}:<32-lowercase-hex-random>" in private_v4.COMMAND_BINDING_PROMPT_REQUIRED_MARKERS
    assert "9510d79361e01a74" not in workflow
    assert "9510d79361e01a74" not in validator


def test_reviewed_private_prompt_must_encode_complete_holder_closeout_obligation():
    required = set(private_v4.HOLDER_CLOSEOUT_PROMPT_REQUIRED_MARKERS)

    assert "HOLDER CLOSEOUT OBLIGATION" in required
    assert "### Holder closeout after WORK" in required
    assert "If an EVENT returns `WORK`, the holder remains live" in required
    assert "Candidate drift in a REPAIR WORK capsule is not a terminal or fail-closed reason to silently stop." in required
    assert "Send exactly one `CANDIDATE_READY` EVENT using the exact `live_candidate` fields" in required
    assert "send exactly one `YIELD` EVENT while the current holder remains valid" in required
    assert "before any normal invocation exit after obtaining `WORK`" in required
    assert "A missing or ambiguous EVENT result remains exceptional fail-closed transport ambiguity" in required
    assert "never infer private holder state from public history" in required


def test_closeout_contract_reuses_existing_events_instead_of_new_runtime_state():
    protocol = Path("control_engine/v4_runtime_protocol.py").read_text(encoding="utf-8")
    carrier = Path("scripts/control_v4_runtime_carrier.py").read_text(encoding="utf-8")

    assert '"CANDIDATE_READY"' in protocol
    assert '"YIELD"' in protocol
    assert "candidate_ready_v4" in carrier
    assert "yield_holder_v4" in carrier
    assert "lease renewal" not in protocol.lower()
    assert "recovery ledger" not in protocol.lower()
    assert "cancellation protocol" not in protocol.lower()


def test_multiline_wire_fix_remains_intact_during_generation_rotation():
    protocol = Path("control_engine/v4_runtime_protocol.py").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text(encoding="utf-8")

    assert 'TICK_NEWLINE_PREFIX = "CONTROL_V4_RUNTIME_TICK\\n"' in protocol
    assert 'EVENT_NEWLINE_PREFIX = "CONTROL_V4_RUNTIME_EVENT\\n"' in protocol
    assert "parse_public_command(raw_command)" in workflow
