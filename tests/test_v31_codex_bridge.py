from pathlib import Path


SCRIPT = Path('scripts/control_codex_v31.py')


def text():
    return SCRIPT.read_text(encoding='utf-8')


def test_codex_helper_delegates_every_runtime_mutation_to_existing_kernel_writer():
    value = text()
    assert 'kernel.command_claim(' in value
    assert 'kernel.command_record(' in value
    assert 'kernel.command_release(' in value
    assert 'kernel._persist_runtime' not in value
    assert 'git push' not in value
    assert 'control/worker-results/' not in value
    assert 'DISPATCH_QUEUE.json' not in value


def test_codex_start_claims_b1_before_posting_review_request_and_releases_on_transport_failure():
    value = text()
    start = value.split('def command_start', 1)[1].split('def command_reconcile', 1)[0]
    assert start.index('kernel.command_claim(') < start.index('codex_v31.build_request(')
    assert start.index('codex_v31.build_request(') < start.index('"POST"')
    assert 'role=core.ROLE_B' in start
    assert 'worker=core.INSTANCE_B1' in start
    assert 'reason="EXECUTION_UNAVAILABLE"' in start


def test_codex_reconcile_uses_exact_candidate_and_trusted_classifier_before_atomic_record():
    value = text()
    reconcile = value.split('def command_reconcile', 1)[1].split('def build_parser', 1)[0]
    assert '_verify_candidate(target_token, task)' in reconcile
    assert '_request_matches(' in reconcile
    assert 'codex_v31.classify(' in reconcile
    assert reconcile.index('codex_v31.classify(') < reconcile.index('kernel.command_record(')
    assert '"executor": "CODEX_GITHUB_REVIEW"' in reconcile
    assert 'decision.verdict not in {"PASS", "FAIL", "INDETERMINATE"}' in reconcile


def test_codex_helper_has_no_provider_fallback_or_candidate_mutation_path():
    value = text().lower()
    for forbidden in ('cloudflare', 'groq', 'openai_api_key', 'anthropic_api_key', 'provider fallback', 'merge_pull_request'):
        assert forbidden not in value
