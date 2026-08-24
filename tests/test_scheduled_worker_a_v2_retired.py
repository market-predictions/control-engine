from pathlib import Path


def test_scheduled_worker_a_v2_is_not_a_semantic_a_executor():
    workflow = Path('.github/workflows/scheduled-worker-a-v2.yml').read_text(encoding='utf-8')

    assert 'schedule:' not in workflow
    assert "cron:" not in workflow
    assert 'CONTROL_CLOUDFLARE_API_TOKEN' not in workflow
    assert 'CONTROL_CLOUDFLARE_ACCOUNT_ID' not in workflow
    assert 'inference_worker.py' not in workflow
    assert 'scheduled_worker_a_v2_retry_guard.sh' not in workflow
    assert 'Reconcile, claim and execute one model-driven A1 task' not in workflow
    assert 'WORKER_A_SEMANTIC_RUNTIME=CHATGPT_CHAT_ONLY' in workflow
    assert 'GITHUB_ACTIONS_A_IMPLEMENTATION_INFERENCE=false' in workflow
    assert 'PROVIDER_A_IMPLEMENTATION_INFERENCE=false' in workflow
