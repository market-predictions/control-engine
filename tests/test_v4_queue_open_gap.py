from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from test_v4_auto_replenish import bundle, queue, REPO
from scripts import control_v4_queue_open_gap as materialize

NOW = datetime(2026, 10, 14, 8, 30, tzinfo=timezone.utc)


def test_authorized_open_gap_materializes_candidate_less_build():
    q = queue()
    saved = deepcopy(q)
    planned = materialize.plan_one(q, bundle(), now=NOW)
    assert planned is not None
    next_queue, task_id = planned
    assert next_queue["execution_lock"] is None
    assert len(next_queue["tasks"]) == 1
    task = next_queue["tasks"][0]
    assert task["task_id"] == task_id
    assert task["repository"] == REPO
    assert task["status"] == "QUEUED"
    assert task["phase"] == "BUILD"
    assert task["candidate"] is None
    assert task["last_review"] is None
    assert task["acceptance"] == ["bounded acceptance"]
    assert q == saved
    # Repeat ingestion is idempotent; same authorized gap is not duplicated.
    assert materialize.plan_one(next_queue, bundle(), now=NOW) is None


def test_gap_repository_exact_casing_is_preserved():
    b = bundle()
    b.missions[0]["repository"] = REPO.upper()
    planned = materialize.plan_one(queue(), b, now=NOW)
    assert planned is not None
    assert planned[0]["tasks"][0]["repository"] == REPO


def test_locked_queue_never_materializes():
    q = queue()
    q["execution_lock"] = {
        "run_id": "another-holder",
        "task_id": "not-a-task",
        "started_at": "2026-10-14T08:00:00Z",
        "expires_at": "2026-10-14T09:30:00Z",
    }
    # Invalid locks are rejected by canonical schema before planning.
    import pytest
    from control_engine.v4_contracts import V4ValidationError
    with pytest.raises(V4ValidationError):
        materialize.plan_one(q, bundle(), now=NOW)


def test_control_go_queues_before_existing_carrier_claim():
    wf = Path(".github/workflows/control-v4-runtime-carrier.yml").read_text()
    job = wf.split("\n  interactive-control-start:\n", 1)[1]
    assert job.index("Bind one native run to one fresh Control task acquisition") < job.index(
        "python scripts/control_v4_queue_open_gap.py"
    ) < job.index("python scripts/control_v4_runtime_carrier.py")
    assert job.index("Refresh TICK freshness after bounded queue append") > job.index(
        "python scripts/control_v4_queue_open_gap.py"
    )\n    assert job.index("Refresh TICK freshness after bounded queue append") < job.index(
        "python scripts/control_v4_runtime_carrier.py"
    )\n    assert "CONTROL_PLANE_TOKEN: ${{ steps.private-token.outputs.token }}" in job
    script = Path("scripts/control_v4_queue_open_gap.py").read_text()
    assert "carrier._write_queue_exact(" in script
    assert "assert_v4_queue_bound_to_authority(" in script
    assert "eligible_unmaterialized_gaps_v4(" in script
