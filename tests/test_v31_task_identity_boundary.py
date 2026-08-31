from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest

from control_engine import kernel_v31 as k
from control_engine import migration_v31 as migration


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "control_kernel_v31.py"
spec = importlib.util.spec_from_file_location("control_kernel_v31_identity_test", SCRIPT)
bridge = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(bridge)

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)


def test_kernel_task_identity_components_are_unambiguous():
    assert k.deterministic_root_id("M", "r1", "G-1") == "MISSION--M--r1--G-1"
    assert k.deterministic_root_id("MISSION_A", "2026-08-31-r1", "GAP_10") == "MISSION--MISSION_A--2026-08-31-r1--GAP_10"

    for bad in ("M--1", "-M", "M-", "r--1", "-r", "r-", "G--1", "-G", "G-", "space id", "slash/id"):
        with pytest.raises(k.KernelError, match="task identity component is invalid"):
            k._identity_component(bad)


def test_runtime_authority_reader_reuses_kernel_identity_contract():
    for bad in ("M--1", "-M", "M-", "-r", "r-", "-G", "G-"):
        with pytest.raises(bridge.BridgeError, match="boundary ambiguity"):
            bridge._task_identity_component(bad, label="identity")


def test_migration_fact_with_boundary_ambiguous_identity_fails_closed_before_feed():
    queue = {
        "version": "3.1",
        "principal_manual_relay_count": 0,
        "migration_facts": [
            {
                "protocol_id": migration.MIGRATION_PROTOCOL_ID,
                "fact": migration.MIGRATION_FACT,
                "mission_id": "M-",
                "mission_revision": "r1",
                "gap_id": "G1",
                "repository": "o/r",
                "source_task_id": "legacy-task",
                "source_result_ref": "control/worker-results/legacy.json",
                "imported_at": "2026-08-31T08:00:00Z",
                "principal_manual_relay_count": 0,
            }
        ],
        "tasks": [],
    }
    with pytest.raises(k.KernelError, match="task identity component is invalid"):
        migration.feed(queue, missions=[], now=NOW)
