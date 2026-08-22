import json

from control_engine.assurance_capsule import build_capsule

CANDIDATE = "a" * 40
BASE = "b" * 40
OBSERVED = "2026-08-22T12:00:00Z"


def inputs(*, moved=False, wrong_worker=False):
    queue = {
        "version": "1.0",
        "principal_manual_relay_count": 0,
        "tasks": [
            {
                "task_id": "CANARY-B1",
                "repository": "market-predictions/control-engine",
                "operation": "ASSURANCE",
                "intake_revision": "CANARY-R1",
                "handover_id": "CANARY-H1",
                "candidate_pr": 999,
                "candidate_sha": CANDIDATE,
                "target_branch": "main",
                "instruction": "Review only the harmless canary.",
                "acceptance_criteria": ["exact head", "read only", "one verdict"],
                "principal_manual_relay_count": 0,
                "state": "ASSURANCE_EXECUTING",
                "active_role": "governance_release_assurance",
                "active_worker_instance": "A1" if wrong_worker else "B1",
                "active_run_id": "run-canary",
                "resume_state": "ASSURANCE_QUEUED",
                "claim_started_at": "2026-08-22T11:55:00Z",
                "claim_expires_at": "2026-08-22T12:10:00Z",
            },
            {"task_id": "UNRELATED", "instruction": "PRIVATE_NOISE_" + "x" * 20000},
        ],
    }
    pr = {
        "number": 999,
        "state": "open",
        "draft": True,
        "merged": False,
        "body": "IMPLEMENTATION_NARRATIVE_" + "y" * 20000,
        "head": {"sha": ("c" * 40 if moved else CANDIDATE)},
        "base": {"ref": "main", "sha": BASE},
    }
    workflows = {
        "workflow_runs": [
            {
                "id": 1,
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "head_sha": CANDIDATE,
                "event": "pull_request",
                "path": ".github/workflows/ci.yml",
                "raw_noise": "z" * 20000,
            }
        ]
    }
    diff = ("diff --git a/canary b/canary\n+" + "d" * 30000).encode()
    return dict(
        queue_raw=json.dumps(queue).encode(),
        task_id="CANARY-B1",
        pr_raw=json.dumps(pr).encode(),
        workflow_runs_raw=json.dumps(workflows).encode(),
        changed_files_raw=b"fixtures/work-b1-canary.txt\n",
        diff_raw=diff,
        observed_at=OBSERVED,
    )


def test_capsule_is_compact_exact_and_verdict_free():
    capsule = build_capsule(**inputs())
    rendered = json.dumps(capsule)
    assert capsule["protocol_id"] == "CONTROL_ASSURANCE_EVIDENCE_CAPSULE_V1"
    assert capsule["task"]["candidate_sha"] == CANDIDATE
    assert capsule["claim"]["start_proven"] is True
    assert capsule["deterministic_contradictions"] == []
    assert capsule["authority"]["semantic_verdict_present"] is False
    assert "verdict" not in capsule
    assert "PRIVATE_NOISE_" not in rendered
    assert "IMPLEMENTATION_NARRATIVE_" not in rendered
    assert "raw_noise" not in rendered
    assert capsule["diff"]["content_embedded"] is False
    assert capsule["evidence_metrics"]["observed_byte_reduction_percent"] >= 70.0


def test_moved_head_fails_closed():
    capsule = build_capsule(**inputs(moved=True))
    assert "PR_HEAD_MOVED" in capsule["deterministic_contradictions"]


def test_wrong_worker_never_proves_start():
    capsule = build_capsule(**inputs(wrong_worker=True))
    assert capsule["claim"]["start_proven"] is False
    assert "ASSURANCE_START_NOT_PROVEN" in capsule["deterministic_contradictions"]


def test_same_inputs_are_deterministic():
    payload = inputs()
    assert build_capsule(**payload) == build_capsule(**payload)
