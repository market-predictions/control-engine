from __future__ import annotations

import pytest

from control_engine.v4_runtime_protocol import (
    CANONICAL_RUNNER_PROMPT_BLOB_SHA,
    RuntimeProtocolError,
    validate_runtime_binding,
)

RUNNER_CONFIG_BLOB_SHA = "a" * 40
PREDECESSOR_PROMPT_BLOB_SHAS = (
    "4bc8ce5a73e1238427b1ce999be5cd5a6378988c",
    "804c8570141934c5a0b5fa86583c867995ce51f4",
    "fe269bf84744629eca133937854ee284239cbcc9",
    "f9d3b1f1158aa0c84b486120f22b5173417f54e7",
    "0a536651ad3096e2c6de44e6dd25d0cea14ec8e1",
    "f354539a6493bce9269d77fe085300ac4a0c9fa6",
    "74e265ad8d2e84a11e6097feb2e2e27ff5d1b64c",
    "97bb8a66d2cd6a55c8c81e0b48542e32b9586e6c",
    "ab005b25b74c3a79ddff2266d90af60e25ddbb77",
    "f984584f7680428db5ecedf414d0bdd518245f1c",
    "04e7dbb577e1dbe630a1422d7b38dff2fd337e3c",
    "e100b7655dd1596f0562820e55a8da2a3358a6a8",
    "2cc54e0fbf21b93609d3c4e093bcdacfb566fcb0",
    "3e577ae37c46d39b07e8b1bb9a19d59d4bddd242",
    "419afc91bc4b1f3fa7f1d624d713077452a3d7ee",
    "2d686b2271a9ff5cde931109d7a8078c8a2154d5",
    "fe3179cb9dd595999c45a0f9233ef5dc397d9fa0",
    "6cd83f6c687ae2b8cf437add85c798bfb95f28f3",
)
PROMPT_TEXT = "\n".join(
    (
        "document_id=CONTROL_RUNNER_V4_PROMPT",
        "status=ACTIVE_BOUND",
        "architecture=CONTROL_AUTONOMY_ARCHITECTURE_V4",
        "source_of_truth=GITHUB",
        "principal_manual_relay_target=0",
    )
)


def _binding(prompt_blob_sha: str):
    authority = {
        "protocol_id": "CONTROL_RUNTIME_AUTHORITY_V4",
        "control_runtime_enabled": True,
        "integration_enabled": False,
        "runner_config_path": "control/CONTROL_RUNNER_V4.json",
        "runner_config_blob_sha": RUNNER_CONFIG_BLOB_SHA,
        "principal_manual_relay_count": 0,
    }
    runner_config = {
        "protocol_id": "CONTROL_RUNNER_V4",
        "runner_id": "CONTROL_V4_RUNNER",
        "execution_surface": "CHATGPT_SCHEDULED",
        "automation_object_binding_status": "BOUND",
        "principal_manual_relay_count": 0,
        "prompt_path": "control/CONTROL_RUNNER_V4_PROMPT.md",
        "prompt_blob_sha": prompt_blob_sha,
    }
    return validate_runtime_binding(
        authority,
        runner_config,
        PROMPT_TEXT,
        runner_config_blob_sha=RUNNER_CONFIG_BLOB_SHA,
        prompt_blob_sha=prompt_blob_sha,
    )


def test_runtime_binding_accepts_only_current_generation_runner_prompt() -> None:
    assert CANONICAL_RUNNER_PROMPT_BLOB_SHA == "4033ae0034711634d8a63efacf6c5cc2b7c90570"
    assert _binding(CANONICAL_RUNNER_PROMPT_BLOB_SHA) == (True, False)


@pytest.mark.parametrize("prompt_blob_sha", PREDECESSOR_PROMPT_BLOB_SHAS)
def test_runtime_binding_rejects_every_predecessor_prompt(prompt_blob_sha: str) -> None:
    with pytest.raises(RuntimeProtocolError, match="runner prompt wire contract is not current"):
        _binding(prompt_blob_sha)
