import pytest

from scripts import control_v4_auto_replenish as auto
from scripts import control_v4_owner_admin as owner_admin
from scripts import control_v4_runtime_carrier as carrier


REPO = "market-predictions/agent"


def _exact_pr(number: int) -> dict:
    return {
        "number": number,
        "body": "Mission: `AGENT_FRAMEWORK` revision `2026-09-10-r2`\nGap: `AGENT-R1-GAP-05`",
        "user": {"login": auto.PRINCIPAL_LOGIN},
        "head": {
            "sha": "c" * 40,
            "ref": "control/agent-gap",
            "repo": {"full_name": REPO, "private": False},
        },
        "base": {"sha": "d" * 40, "ref": "main"},
    }


def _mission_and_gap():
    return (
        {"mission_id": "AGENT_FRAMEWORK", "mission_revision": "2026-09-10-r2"},
        {"gap_id": "AGENT-R1-GAP-05", "repository": REPO},
    )


def test_pre_cas_revalidation_rejects_new_duplicate_exact_claim(monkeypatch):
    mission, gap = _mission_and_gap()
    state = {"queue": {"tasks": []}}
    bundle = object()
    command = {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "activation_key": "activation-key",
        "repository": REPO,
        "candidate_pr_number": 3,
        "candidate_sha": "c" * 40,
        "candidate_head_branch": "control/agent-gap",
        "expected_base_branch": "main",
        "expected_base_sha": "d" * 40,
    }

    monkeypatch.setattr(
        owner_admin,
        "eligible_unmaterialized_gaps_v4",
        lambda *_args: [(mission, gap)],
    )
    monkeypatch.setattr(owner_admin, "activation_key_v4", lambda *_args: "activation-key")

    def fake_get(path):
        if path == f"repos/{REPO}":
            return {"full_name": REPO, "private": False}
        if path.startswith(f"repos/{REPO}/pulls?state=open"):
            return [_exact_pr(3), _exact_pr(4)]
        raise AssertionError(path)

    monkeypatch.setattr(owner_admin, "_public_get", fake_get)

    with pytest.raises(auto.AutoReplenishError, match="multiple exact replenishment candidates"):
        auto._revalidate_candidate_command(state, bundle, command)


def test_exact_pr_reread_rejects_mission_gap_marker_drift(monkeypatch):
    mission, gap = _mission_and_gap()
    listed = _exact_pr(3)
    drifted = _exact_pr(3)
    drifted["body"] = "Mission: `OTHER` revision `2026-09-10-r2`\nGap: `AGENT-R1-GAP-05`"

    def fake_get(path):
        if path == f"repos/{REPO}":
            return {"full_name": REPO, "private": False}
        if path.startswith(f"repos/{REPO}/pulls?state=open"):
            return [listed]
        if path == f"repos/{REPO}/pulls/3":
            return drifted
        raise AssertionError(path)

    monkeypatch.setattr(owner_admin, "_public_get", fake_get)

    with pytest.raises(auto.AutoReplenishError, match="Mission/gap binding drifted"):
        auto._candidate_command(mission, gap, object())


def test_failed_pre_cas_candidate_revalidation_never_writes_or_falls_back_to_no_work(monkeypatch):
    state = {
        "main_sha": "1" * 40,
        "queue": {"tasks": []},
        "runtime_enabled": True,
        "integration_enabled": False,
    }
    bundle = object()
    tick = {"kind": "TICK", "run_id": "v4:test", "yielded_task_tokens": []}
    command = {
        "operation": "ACTIVATE_ROOT_CANDIDATE",
        "activation_key": "activation-key",
        "repository": REPO,
        "candidate_pr_number": 3,
        "candidate_sha": "c" * 40,
        "candidate_head_branch": "control/agent-gap",
        "expected_base_branch": "main",
        "expected_base_sha": "d" * 40,
    }
    work = {
        "protocol": auto.RESULT_PROTOCOL_ID,
        "result": "WORK",
        "run_id": "v4:test",
        "task_token": "f" * 64,
        "repository": REPO,
        "action": "REVIEW_INTERNAL",
    }
    acquired_queue = {"tasks": [{"task_id": "task"}]}
    outputs = []

    monkeypatch.setenv(
        "CONTROL_V4_CARRIER_RESULT",
        '{"protocol":"CONTROL_V4_RUNTIME_RESULT_V1","result":"NO_WORK","run_id":"v4:test"}',
    )
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", "ignored-by-test")
    monkeypatch.setattr(carrier, "_load_current", lambda: state)
    monkeypatch.setattr(carrier, "_load_authority_bundle", lambda _sha: bundle)
    monkeypatch.setattr(auto, "_auto_materialization_policy_enabled", lambda _state: True)
    monkeypatch.setattr(auto, "parse_public_command", lambda _raw: tick)
    monkeypatch.setattr(
        auto,
        "_plan_materialize_and_acquire_one",
        lambda *_args: (acquired_queue, command, work),
    )
    monkeypatch.setattr(carrier, "_assert_tick_not_superseded", lambda _command: None)
    monkeypatch.setattr(carrier, "_assert_tick_fresh", lambda **_kwargs: None)
    monkeypatch.setattr(
        auto,
        "_revalidate_candidate_command",
        lambda *_args: (_ for _ in ()).throw(
            auto.AutoReplenishError("multiple exact replenishment candidates claim the same governed gap")
        ),
    )
    monkeypatch.setattr(
        carrier,
        "_write_queue_exact",
        lambda *_args, **_kwargs: pytest.fail("failed final candidate fence must prevent queue write"),
    )
    monkeypatch.setattr(auto, "_set_output", lambda value: outputs.append(dict(value)))

    assert auto.main() == 1
    assert outputs == [
        {
            "protocol": auto.RESULT_PROTOCOL_ID,
            "result": "ERROR",
            "code": "AUTO_REPLENISH_FAIL_CLOSED",
            "run_id": "v4:test",
        }
    ]
