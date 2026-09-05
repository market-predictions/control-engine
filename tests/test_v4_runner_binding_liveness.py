import pytest

from scripts import validate_private_control_v4 as validator


def test_repaired_runner_prompt_is_exactly_trust_anchored():
    assert validator.REPAIRED_RUNNER_PROMPT_BLOB_SHA == (
        "079edd313503a8e11f733b4b56f3fef669ab2f09"
    )


def test_impossible_in_run_scheduler_identity_self_attestation_is_rejected():
    with pytest.raises(
        validator.ValidationError,
        match="impossible in-run scheduler identity self-attestation",
    ):
        validator.validate_runner_prompt_runtime_binding_semantics(
            "this invocation is the exact reviewed scheduled Runner object/effective capability"
        )


def test_outside_runner_activation_binding_semantics_do_not_require_self_attestation():
    validator.validate_runner_prompt_runtime_binding_semantics(
        "Scheduler object/effective-capability identity is an outside-Runner activation invariant; "
        "normal Runner runtime consumes the reviewed GitHub binding and does not introspect scheduler administration."
    )
