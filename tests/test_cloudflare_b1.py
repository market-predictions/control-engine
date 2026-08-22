import http.client
import json
import ssl

import pytest

from control_engine.cloudflare_b1 import (
    CONTROL_ENGINE_REPOSITORY,
    MAX_BOUNDED_EVIDENCE_BYTES,
    MAX_CONTRACT_BYTES,
    MAX_DIFF_BYTES,
    MAX_PACK_BYTES,
    MODEL_ID,
    SemanticBudgetMeasurement,
    CloudflareB1Error,
    CloudflareB1ExecutionUnavailable,
    build_messages,
    build_semantic_pack,
    classify_execution_surface,
    lineage_id,
    measure_semantic_budget,
    parse_verdict_response,
)

CANDIDATE = "a" * 40


def capsule():
    return {
        "authority": {"semantic_verdict_present": False},
        "task": {"candidate_sha": CANDIDATE},
        "claim": {"start_proven": True},
        "deterministic_contradictions": [],
    }


def budget(*, diff=100, contract=100, evidence=100, pack=1000):
    return SemanticBudgetMeasurement(
        diff_bytes=diff,
        contract_bytes=contract,
        evidence_bytes=evidence,
        pack_bytes=pack,
    )


def chat_payload(content: str, *, finish_reason: str = "stop") -> dict:
    return {"choices": [{"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}]}


def valid_pass_json():
    return json.dumps(
        {"candidate_sha": CANDIDATE, "verdict": "PASS", "summary": "All criteria supported.", "findings": []}
    )


def test_ordinary_small_change_is_cloudflare_eligible():
    decision = classify_execution_surface(
        repository="market-predictions/example",
        changed_files=["src/widget.py", "tests/test_widget.py"],
        budget=budget(diff=12000, pack=15000),
    )
    assert decision.cloudflare_eligible is True
    assert decision.reasons == ()


@pytest.mark.parametrize(
    "path",
    [
        "control_engine/cloudflare_b1.py",
        "control_engine/codex_b1.py",
        "control_engine/scheduled_worker_a.py",
        "control_engine/assurance_capsule.py",
        "control_engine/timeline.py",
        "scripts/project_integration_executor.py",
        "scripts/codex_b1_canary.py",
        ".github/workflows/codex-b1-deep-handshake-v1.yml",
        "docs/B1_DUAL_EXECUTOR_V1.md",
    ],
)
def test_control_engine_source_or_authority_contract_path_requires_deep_review(path):
    decision = classify_execution_surface(
        repository=CONTROL_ENGINE_REPOSITORY,
        changed_files=[path],
        budget=budget(),
    )
    assert decision.work_required is True
    assert decision.reasons == (f"CONTROL_AUTHORITY_PATH:{path}",)


@pytest.mark.parametrize(
    "measurement,reason",
    [
        (budget(diff=MAX_DIFF_BYTES + 1), "DIFF_BUDGET_EXCEEDED"),
        (budget(contract=MAX_CONTRACT_BYTES + 1), "CONTRACT_BUDGET_EXCEEDED"),
        (budget(evidence=MAX_BOUNDED_EVIDENCE_BYTES + 1), "BOUNDED_EVIDENCE_BUDGET_EXCEEDED"),
        (budget(pack=MAX_PACK_BYTES + 1), "SEMANTIC_PACK_BUDGET_EXCEEDED"),
    ],
)
def test_every_semantic_pack_budget_overflow_requires_deep_review(measurement, reason):
    decision = classify_execution_surface(
        repository="market-predictions/example",
        changed_files=["src/widget.py"],
        budget=measurement,
    )
    assert decision.work_required is True
    assert decision.reasons == (reason,)


def test_custom_diff_limit_cannot_exceed_builder_hard_limit():
    decision = classify_execution_surface(
        repository="market-predictions/example",
        changed_files=["src/big.py"],
        budget=budget(diff=MAX_DIFF_BYTES + 1),
        max_diff_bytes=MAX_DIFF_BYTES * 2,
    )
    assert decision.reasons == ("DIFF_BUDGET_EXCEEDED",)


def test_exact_budget_measurement_matches_built_pack_bytes():
    kwargs = dict(
        task_id="T1",
        handover_id="H1",
        candidate_sha=CANDIDATE,
        assurance_contract="One verdict.",
        acceptance_criteria=["criterion"],
        capsule=capsule(),
        diff="+safe",
        bounded_evidence={"ci": "success"},
    )
    measured = measure_semantic_budget(**kwargs)
    pack = build_semantic_pack(**kwargs)
    serialized = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert measured.diff_bytes == len(b"+safe")
    assert measured.contract_bytes == len(b"One verdict.")
    assert measured.pack_bytes == len(serialized)


def test_semantic_pack_requires_start_proven_and_clean_b0():
    bad = capsule()
    bad["claim"]["start_proven"] = False
    with pytest.raises(CloudflareB1Error, match="START_PROVEN"):
        build_semantic_pack(
            task_id="T1",
            handover_id="H1",
            candidate_sha=CANDIDATE,
            assurance_contract="One verdict.",
            acceptance_criteria=["criterion"],
            capsule=bad,
            diff="+safe",
            bounded_evidence={},
        )


def test_messages_are_two_message_no_tool_protocol():
    pack = build_semantic_pack(
        task_id="T1",
        handover_id="H1",
        candidate_sha=CANDIDATE,
        assurance_contract="One verdict.",
        acceptance_criteria=["criterion"],
        capsule=capsule(),
        diff="+safe",
        bounded_evidence={"ci": "success"},
    )
    messages = build_messages(pack)
    assert len(messages) == 2
    assert [item["role"] for item in messages] == ["system", "user"]
    assert all(set(item) == {"role", "content"} for item in messages)
    assert MODEL_ID == "@cf/openai/gpt-oss-120b"


def test_strict_exact_verdict_accepts_pass():
    assert parse_verdict_response(chat_payload(valid_pass_json()), candidate_sha=CANDIDATE)["verdict"] == "PASS"


def test_single_json_fence_is_deterministically_normalized():
    fenced = f"```json\n{valid_pass_json()}\n```"
    assert parse_verdict_response(chat_payload(fenced), candidate_sha=CANDIDATE)["verdict"] == "PASS"


@pytest.mark.parametrize(
    "response,code",
    [
        ("Result:\n" + valid_pass_json(), "EXECUTION_UNAVAILABLE_CLOUDFLARE_NON_JSON"),
        (json.dumps({"candidate_sha": CANDIDATE, "verdict": "PASS", "summary": "ok", "findings": [], "confidence": 1}), "EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_KEYS"),
        (json.dumps({"candidate_sha": "b" * 40, "verdict": "PASS", "summary": "ok", "findings": []}), "EXECUTION_UNAVAILABLE_CLOUDFLARE_CANDIDATE_MISMATCH"),
        (json.dumps({"candidate_sha": CANDIDATE, "verdict": "PASS", "summary": "ok", "findings": ["No issues"]}), "EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_FINDINGS"),
        (json.dumps({"candidate_sha": CANDIDATE, "verdict": "FAIL", "summary": "bad", "findings": []}), "EXECUTION_UNAVAILABLE_CLOUDFLARE_VERDICT_FINDINGS"),
    ],
)
def test_malformed_or_mismatched_output_is_execution_failure_not_semantic_verdict(response, code):
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        parse_verdict_response(chat_payload(response), candidate_sha=CANDIDATE)
    assert caught.value.code == code


def test_length_finish_reason_is_execution_failure():
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        parse_verdict_response(chat_payload(valid_pass_json(), finish_reason="length"), candidate_sha=CANDIDATE)
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_OUTPUT_TRUNCATED"


def test_lineage_key_is_exact_and_candidate_sensitive():
    first = lineage_id(task_id="T1", handover_id="H1", candidate_sha=CANDIDATE)
    assert first == lineage_id(task_id="T1", handover_id="H1", candidate_sha=CANDIDATE)
    assert first != lineage_id(task_id="T1", handover_id="H1", candidate_sha="b" * 40)


def test_workers_ai_transport_is_exactly_one_request_and_bounded(monkeypatch):
    from control_engine import cloudflare_b1

    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit):
            assert limit == 1_000_001
            return json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}]}).encode()

    def fake_urlopen(request, timeout):
        body = json.loads(request.data)
        calls.append((request.full_url, timeout, body))
        return FakeResponse()

    monkeypatch.setattr(cloudflare_b1.urllib.request, "urlopen", fake_urlopen)
    result = cloudflare_b1.run_workers_ai_once(
        account_id="account_1",
        api_token="secret-token",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )
    assert "choices" in result
    assert len(calls) == 1
    url, timeout, body = calls[0]
    assert url.endswith("/ai/v1/chat/completions")
    assert timeout == 90
    assert body == {
        "model": "@cf/openai/gpt-oss-120b",
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "temperature": 0,
        "seed": 199001,
        "max_tokens": 512,
    }


def test_remote_disconnect_is_execution_unavailable(monkeypatch):
    from control_engine import cloudflare_b1

    def disconnect(*_args, **_kwargs):
        raise http.client.RemoteDisconnected("remote closed connection")

    monkeypatch.setattr(cloudflare_b1.urllib.request, "urlopen", disconnect)
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        cloudflare_b1.run_workers_ai_once(
            account_id="account_1",
            api_token="secret-token",
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        )
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_TRANSPORT"


def test_incomplete_read_is_execution_unavailable(monkeypatch):
    from control_engine import cloudflare_b1

    class PartialResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _limit):
            raise http.client.IncompleteRead(b"partial", 100)

    monkeypatch.setattr(cloudflare_b1.urllib.request, "urlopen", lambda *_args, **_kwargs: PartialResponse())
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        cloudflare_b1.run_workers_ai_once(
            account_id="account_1",
            api_token="secret-token",
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        )
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_TRANSPORT"


def test_tls_eof_is_execution_unavailable(monkeypatch):
    from control_engine import cloudflare_b1

    def tls_eof(*_args, **_kwargs):
        raise ssl.SSLEOFError(8, "EOF occurred in violation of protocol")

    monkeypatch.setattr(cloudflare_b1.urllib.request, "urlopen", tls_eof)
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        cloudflare_b1.run_workers_ai_once(
            account_id="account_1",
            api_token="secret-token",
            messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        )
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_TRANSPORT"
