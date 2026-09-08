from __future__ import annotations

import json

import pytest

import scripts.control_v4_runtime_carrier as carrier


RUN_ID = "v4:6a9a7e0b18b08191876c134d83cfbba2:7c4e91b2d5a83f60:" + ("a" * 32)


def _tick_body() -> str:
    return "CONTROL_V4_RUNTIME_TICK " + json.dumps({"run_id": RUN_ID}, separators=(",", ":"))


def _event_body() -> str:
    return "CONTROL_V4_RUNTIME_EVENT " + json.dumps(
        {
            "run_id": RUN_ID,
            "task_token": "b" * 64,
            "event": "YIELD",
            "repository": "market-predictions/control-engine",
            "action": "BUILD",
        },
        separators=(",", ":"),
    )


def _invoke_update_refs(monkeypatch, *, body: str, created_at: str, events: list[str]) -> None:
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND", body)
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND_ID", "123")
    monkeypatch.setenv("CONTROL_V4_PUBLIC_COMMAND_CREATED_AT", created_at)
    monkeypatch.setenv("CONTROL_PLANE_TOKEN", "test-token")

    def fake_request_json(url, *, headers=None, method="GET", payload=None, allow_404=False):
        assert url == carrier.GRAPHQL
        assert method == "POST"
        assert allow_404 is False
        assert isinstance(payload, dict)
        events.append("cas")
        return {"data": {"updateRefs": {"clientMutationId": "test"}}}

    monkeypatch.setattr(carrier, "_request_json", fake_request_json)
    carrier._update_refs_exact(
        repository_node_id="R_test",
        main_oid="1" * 40,
        runtime_before_oid="2" * 40,
        runtime_after_oid="3" * 40,
        client_id="test-cas-freshness",
    )


def test_tick_freshness_is_rechecked_immediately_before_durable_ref_cas(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(carrier, "_assert_tick_fresh", lambda *, now: events.append("freshness"))

    _invoke_update_refs(
        monkeypatch,
        body=_tick_body(),
        created_at="2026-09-08T17:43:00Z",
        events=events,
    )

    assert events == ["freshness", "cas"]


def test_stale_tick_cannot_reach_durable_ref_cas(monkeypatch) -> None:
    events: list[str] = []

    with pytest.raises(carrier.StaleEventError, match="TICK command stale at transition"):
        _invoke_update_refs(
            monkeypatch,
            body=_tick_body(),
            created_at="2000-01-01T00:00:00Z",
            events=events,
        )

    assert events == []


def test_event_ref_cas_is_not_subject_to_tick_age_fence(monkeypatch) -> None:
    events: list[str] = []

    def unexpected_tick_check(*, now):
        raise AssertionError("EVENT ref CAS must not execute the TICK freshness guard")

    monkeypatch.setattr(carrier, "_assert_tick_fresh", unexpected_tick_check)
    _invoke_update_refs(
        monkeypatch,
        body=_event_body(),
        created_at="2000-01-01T00:00:00Z",
        events=events,
    )

    assert events == ["cas"]


def test_ref_cas_guard_is_centralized_before_graphql_mutation() -> None:
    source = open(carrier.__file__, encoding="utf-8").read()
    section = source.split("def _update_refs_exact", 1)[1].split("def _serialize_queue", 1)[0]
    assert "_assert_current_tick_fresh_at_ref_cas()" in section
    assert section.index("_assert_current_tick_fresh_at_ref_cas()") < section.index("result = _request_json(")
