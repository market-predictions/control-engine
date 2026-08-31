import base64
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from control_engine import minimal_core as core
from scripts import private_minimal_core_materialize as materialize


def _encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _assurance_spec() -> dict:
    return {
        "task_id": "SOLIDSECURITY-24-CUMULATIVE-ASSURE",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate_sha": "9" * 40,
        "priority": 10,
        "instruction": "Review the exact cumulative candidate blind-first.",
        "acceptance_criteria": ["Exact candidate is reviewed", "No authority expansion"],
    }


def test_decode_and_build_assurance_root_is_exact_and_one_step():
    spec = materialize._decode_spec(_encode(_assurance_spec()))
    task = materialize._root_from_spec(spec, "2026-08-31T06:00:00Z")

    assert task["lifecycle_model"] == core.PROTOCOL_ID
    assert task["operation"] == "ASSURANCE"
    assert task["role"] == core.ROLE_B
    assert task["status"] == core.STATUS_QUEUED
    assert task["claim"] is None
    assert task["principal_manual_relay_count"] == 0
    assert set(task["successor_by_outcome"]) == {"PASS", "FAIL"}
    assert task["successor_by_outcome"]["PASS"] == {
        "task_id": "SOLIDSECURITY-24-CUMULATIVE-ASSURE--INTEGRATE",
        "operation": "PROJECT_INTEGRATION",
        "role": core.ROLE_A,
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate_sha": "9" * 40,
    }
    assert task["successor_by_outcome"]["FAIL"] == {
        "task_id": "SOLIDSECURITY-24-CUMULATIVE-ASSURE--REPAIR",
        "operation": "REPAIR",
        "role": core.ROLE_A,
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate_sha": "9" * 40,
    }
    core.validate({"version": "1.0", "principal_manual_relay_count": 0, "tasks": [task]})


def test_same_spec_identity_ignores_lifecycle_state_but_detects_spec_drift():
    spec = _assurance_spec()
    original = materialize._root_from_spec(spec, "2026-08-31T06:00:00Z")
    replay = materialize._root_from_spec(spec, "2026-08-31T07:00:00Z")

    original["status"] = core.STATUS_EXECUTING
    original["claim"] = {
        "run_id": "run-1",
        "role": core.ROLE_B,
        "worker_instance": core.INSTANCE_B1,
        "backend": "canonical-minimal-core/b1",
        "started_at": "2026-08-31T06:05:00Z",
        "expires_at": "2026-08-31T07:35:00Z",
    }
    original["attempt_count"] = 1

    assert materialize._identity_projection(original) == materialize._identity_projection(replay)

    drifted = materialize._root_from_spec({**spec, "candidate_sha": "8" * 40}, "2026-08-31T07:00:00Z")
    assert materialize._identity_projection(original) != materialize._identity_projection(drifted)


def test_materializer_replay_does_not_reconcile_or_mutate_existing_lifecycle(tmp_path, monkeypatch):
    spec = _assurance_spec()
    existing = materialize._root_from_spec(spec, "2026-08-31T06:00:00Z")
    existing["status"] = core.STATUS_EXECUTING
    existing["claim"] = {
        "run_id": "run-expired",
        "role": core.ROLE_B,
        "worker_instance": core.INSTANCE_B1,
        "backend": "canonical-minimal-core/b1",
        "started_at": "2026-08-31T06:05:00Z",
        "expires_at": "2026-08-31T06:35:00Z",
    }
    existing["attempt_count"] = 1
    queue = {"version": "1.0", "principal_manual_relay_count": 0, "tasks": [existing]}
    queue_path = tmp_path / materialize.bridge.QUEUE_REL
    queue_path.parent.mkdir(parents=True)
    materialize.bridge._write(queue_path, queue)
    before = json.loads(json.dumps(queue))

    monkeypatch.setattr(materialize.bridge, "_assert_cutover_safe", lambda *_args: None)

    def forbidden_reconcile(*_args, **_kwargs):
        raise AssertionError("materialization replay must not reconcile lifecycle state")

    monkeypatch.setattr(materialize.bridge, "_reconcile_file", forbidden_reconcile)

    def fake_with_cas(_token, mutate, *, message):
        assert message.startswith("runtime: materialize Minimal Core assurance root")
        captured = mutate(tmp_path)
        return captured, materialize.bridge._load(queue_path), 1

    monkeypatch.setattr(materialize.bridge, "_with_cas", fake_with_cas)

    assert materialize.command_materialize("token", _encode(spec)) == 0
    assert materialize.bridge._load(queue_path) == before


def test_materializer_rejects_any_authority_or_mission_field_injection():
    for field, value in (
        ("role", core.ROLE_A),
        ("operation", "IMPLEMENTATION"),
        ("mission_id", "SOLIDSECURITY"),
        ("successor_by_outcome", {}),
        ("principal_manual_relay_count", 1),
    ):
        with pytest.raises(RuntimeError, match="unsupported fields"):
            materialize._decode_spec(_encode({**_assurance_spec(), field: value}))


def test_materializer_requires_exact_candidate_repository_and_nonempty_acceptance():
    with pytest.raises(RuntimeError, match="exact candidate SHA"):
        materialize._root_from_spec(
            {**_assurance_spec(), "candidate_sha": "short"},
            "2026-08-31T06:00:00Z",
        )

    with pytest.raises(RuntimeError, match="owner/name"):
        materialize._root_from_spec(
            {**_assurance_spec(), "repository": "solidprivacy-nl/solidsecurity/extra"},
            "2026-08-31T06:00:00Z",
        )

    with pytest.raises(RuntimeError, match="non-empty list"):
        materialize._root_from_spec(
            {**_assurance_spec(), "acceptance_criteria": []},
            "2026-08-31T06:00:00Z",
        )


def test_materializer_script_entrypoint_bootstraps_repository_root():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "scripts/private_minimal_core_materialize.py", "--help"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Materialize one exact-candidate Minimal Core assurance root" in completed.stdout


def test_workflow_exposes_only_owner_gated_materialize_prefix():
    workflow = Path(".github/workflows/scheduled-worker-a-v2.yml").read_text(encoding="utf-8")
    assert "github.event.comment.user.login == 'market-predictions'" in workflow
    assert "startsWith(github.event.comment.body, 'CONTROL_CORE_MATERIALIZE_V1 ')" in workflow
    assert "private_minimal_core_materialize.py --spec-b64" in workflow
    assert "GITHUB_ACTIONS_SEMANTIC_ASSURANCE=false" in workflow
    assert "SECOND_QUEUE=false" in workflow
