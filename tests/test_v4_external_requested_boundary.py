from copy import deepcopy
from datetime import datetime, timezone
import json

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import parse_public_command, safe_work_capsule


NOW = datetime(2026, 9, 9, 0, 30, tzinfo=timezone.utc)
SHA = "a" * 40
BASE = "b" * 40
RUN_ID = "external-request-boundary"


def test_external_requested_is_atomic_wait_boundary(monkeypatch) -> None:
    candidate = {
        "candidate_sha": SHA,
        "candidate_pr_number": 120,
        "candidate_head_branch": "candidate",
        "expected_base_branch": "main",
        "expected_base_sha": BASE,
    }
    task = {
        "task_id": "MISSION--M--2026-09-09-r1--G1",
        "mission_id": "M",
        "mission_revision": "2026-09-09-r1",
        "mission_contract_blob_sha": "c" * 40,
        "repository_authority_blob_sha": "d" * 40,
        "gap_id": "G1",
        "repository": "example/repo",
        "acceptance": ["private"],
        "integration_policy": "HOLD_AFTER_PASS",
        "review_policy": "EXTERNAL",
        "convergence_required": False,
        "status": "ACTIVE",
        "phase": "REVIEW",
        "candidate": candidate,
        "last_review": {
            "candidate_sha": SHA,
            "expected_base_branch": "main",
            "expected_base_sha": BASE,
            "verdict": "PASS",
            "reviewed_at": "2026-09-09T00:00:00Z",
        },
        "external_review": None,
        "blocker": None,
        "created_at": "2026-09-09T00:00:00Z",
        "updated_at": "2026-09-09T00:00:00Z",
    }
    queue = {
        "version": "4.0",
        "principal_manual_relay_count": 0,
        "execution_lock": {
            "run_id": RUN_ID,
            "task_id": task["task_id"],
            "started_at": "2026-09-09T00:00:00Z",
            "expires_at": "2026-09-09T01:30:00Z",
        },
        "migration_facts": [],
        "tasks": [task],
    }
    work = safe_work_capsule(queue, task_id=task["task_id"], run_id=RUN_ID)
    command = parse_public_command(
        "CONTROL_V4_RUNTIME_EVENT " + json.dumps(
            {
                "run_id": RUN_ID,
                "task_token": work["task_token"],
                "event": "EXTERNAL_REQUESTED",
                "repository": work["repository"],
                "action": work["action"],
                "candidate": work["candidate"],
                "request_ref": "https://github.com/example/repo/pull/120#issuecomment-1",
            },
            separators=(",", ":"),
        )
    )
    writes = []

    def fake_write(state, next_queue, *, reason):
        writes.append((deepcopy(next_queue), reason))
        return {**state, "queue": deepcopy(next_queue)}

    monkeypatch.setattr(carrier, "_target_pr_candidate", lambda repository, pr_number: deepcopy(candidate))
    monkeypatch.setattr(carrier, "_write_queue_exact", fake_write)
    state = {"queue": deepcopy(queue), "runtime_enabled": True, "integration_enabled": False}

    _, result = carrier._event(command, state, now=NOW)

    assert len(writes) == 1
    assert writes[0][1] == "external-requested"
    assert writes[0][0]["execution_lock"] is None
    assert writes[0][0]["tasks"][0]["external_review"]["status"] == "PENDING"
    assert result["result"] == "YIELDED"
    assert "action" not in result
