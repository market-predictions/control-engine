import pytest

from control_engine.cloudflare_b1 import CloudflareB1ExecutionUnavailable, parse_verdict_response

CANDIDATE = "a" * 40


def _run_with_bytes(monkeypatch, raw: bytes):
    from control_engine import cloudflare_b1

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit):
            assert limit == 1_000_001
            return raw

    monkeypatch.setattr(cloudflare_b1.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    return cloudflare_b1.run_workers_ai_once(
        account_id="account_1",
        api_token="secret-token",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
    )


def test_outer_provider_json_integer_digit_limit_is_unparseable(monkeypatch):
    raw = b'{"overflow":' + (b"9" * 5000) + b"}"
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        _run_with_bytes(monkeypatch, raw)
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_UNPARSEABLE"


def test_outer_provider_json_recursion_failure_is_unparseable(monkeypatch):
    from control_engine import cloudflare_b1

    def recursion_failure(*_args, **_kwargs):
        raise RecursionError("synthetic parser recursion limit")

    monkeypatch.setattr(cloudflare_b1.json, "loads", recursion_failure)
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        _run_with_bytes(monkeypatch, b"{}")
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_RESPONSE_UNPARSEABLE"


def test_inner_semantic_json_parser_limit_is_non_json():
    content = (
        '{"candidate_sha":"' + CANDIDATE + '","verdict":"PASS","summary":"ok","findings":[],"overflow":'
        + ("9" * 5000)
        + "}"
    )
    payload = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}
    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        parse_verdict_response(payload, candidate_sha=CANDIDATE)
    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_NON_JSON"
