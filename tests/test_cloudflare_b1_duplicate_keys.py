import pytest

from control_engine.cloudflare_b1 import CloudflareB1ExecutionUnavailable, parse_verdict_response

CANDIDATE = "a" * 40


def _chat_payload(content: str) -> dict:
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


def test_duplicate_semantic_verdict_keys_cannot_overwrite_fail_or_candidate_mismatch():
    malformed = (
        '{'
        f'"candidate_sha":"{"b" * 40}",'
        f'"candidate_sha":"{CANDIDATE}",'
        '"verdict":"FAIL",'
        '"verdict":"PASS",'
        '"summary":"duplicate keys must fail closed",'
        '"findings":["proven violation"],'
        '"findings":[]'
        '}'
    )

    with pytest.raises(CloudflareB1ExecutionUnavailable) as caught:
        parse_verdict_response(_chat_payload(malformed), candidate_sha=CANDIDATE)

    assert caught.value.code == "EXECUTION_UNAVAILABLE_CLOUDFLARE_NON_JSON"
