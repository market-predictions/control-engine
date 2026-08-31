from pathlib import Path

import pytest

from scripts import validate_private_control_v31 as validator

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_private_control_v31.py"


def test_private_json_rejects_duplicate_object_keys():
    with pytest.raises(validator.ValidationError, match="invalid or ambiguous"):
        validator.strict_json('{"integration_enabled":false,"integration_enabled":true}')


def test_schema_validation_error_never_echoes_private_value():
    secret = "PRIVATE_CONTROL_VALUE_DO_NOT_LOG"
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"mode": {"enum": ["SAFE"]}},
        "required": ["mode"],
    }
    with pytest.raises(validator.ValidationError) as caught:
        validator.validate_instance({"mode": secret}, schema)
    assert secret not in str(caught.value)
    assert str(caught.value) == "instance violates trusted schema"


def test_public_failure_handler_emits_fixed_markers_only():
    source = VALIDATOR.read_text(encoding="utf-8")
    assert 'except ValidationError:' in source
    assert 'CONTROL_PRIVATE_V3_1_STATIC_VALIDATION=FAIL"' in source
    assert 'CONTROL_PRIVATE_V3_1_STATIC_VALIDATION=FAIL_INTERNAL"' in source
    assert 'str(exc)' not in source
    assert 'exc.message' not in source
