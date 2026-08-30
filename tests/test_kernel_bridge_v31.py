from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_kernel_v31.py"
spec = importlib.util.spec_from_file_location("control_kernel_v31", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bridge)


def authority(*, policy="AUTO_AFTER_PASS", enabled=True, profile="CONTROL_AUTO_V1", checks=()):
    return {
        "protocol_id": "CONTROL_REPOSITORY_AUTHORITY_V3_1",
        "repository": "o/r",
        "integration_policy": policy,
        "integration_enabled": enabled,
        "control_auto_profile": profile,
        "required_check_runs": list(checks),
        "principal_manual_relay_count": 0,
    }


def task():
    return {
        "repository": "o/r",
        "mission_id": "M1",
        "mission_revision": "r1",
        "gap_id": "G1",
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "2" * 40,
        "integration_policy": "AUTO_AFTER_PASS",
    }


def mission_wrapper():
    return {
        "mission": {
            "mission_id": "M1",
            "mission_revision": "r1",
            "repository": "o/r",
            "gaps": [{"gap_id": "G1", "gap_state": "OPEN"}],
        },
        "mission_contract_blob_sha": "1" * 40,
        "repository_authority_blob_sha": "3" * 40,
    }


def test_live_repository_authority_blob_change_does_not_revoke_semantic_claim_authority():
    # The task keeps its frozen digest. Current repository authority may change to
    # a more restrictive document without forcing re-feed or invalidating intent.
    bridge._assert_live_task_authority(task(), [mission_wrapper()], {"o/r": authority(policy="HOLD_AFTER_PASS", enabled=False, profile="NONE")})


def test_integration_requires_frozen_and_live_auto_authority():
    t = task()
    assert bridge._integration_authorized(t, authority(), authority()) is True
    assert bridge._integration_authorized(t, authority(policy="HOLD_AFTER_PASS"), authority()) is False
    assert bridge._integration_authorized(t, authority(), authority(policy="HOLD_AFTER_PASS")) is False
    assert bridge._integration_authorized(t, authority(enabled=False), authority()) is False
    assert bridge._integration_authorized(t, authority(), authority(enabled=False)) is False
    assert bridge._integration_authorized(t, authority(profile="NONE"), authority()) is False
    assert bridge._integration_authorized(t, authority(), authority(profile="NONE")) is False


def test_live_auto_cannot_expand_task_frozen_hold():
    t = task()
    t["integration_policy"] = "HOLD_AFTER_PASS"
    assert bridge._integration_authorized(t, authority(), authority()) is False


def test_required_checks_are_union_of_frozen_and_live_restrictions():
    frozen = authority(checks=["ci/a", "ci/shared"])
    live = authority(checks=["ci/shared", "ci/b"])
    assert bridge._effective_required_checks(frozen, live) == ["ci/a", "ci/b", "ci/shared"]


def test_required_checks_fail_closed_on_invalid_shape():
    bad = authority()
    bad["required_check_runs"] = "ci/a"
    with pytest.raises(bridge.BridgeError, match="required checks"):
        bridge._effective_required_checks(bad, authority())
