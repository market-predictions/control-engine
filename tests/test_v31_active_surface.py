from pathlib import Path


def test_only_ci_and_v31_kernel_remain_active_workflows():
    names = sorted(p.name for p in Path('.github/workflows').glob('*.yml'))
    assert names == ['ci.yml', 'control-kernel-v3-1.yml']


def test_kernel_is_only_runtime_mutating_workflow():
    workflows = {p.name: p.read_text(encoding='utf-8') for p in Path('.github/workflows').glob('*.yml')}
    assert 'control-runtime-state' not in workflows['ci.yml']
    kernel = workflows['control-kernel-v3-1.yml']
    assert 'control-runtime-mutation' in kernel
    assert 'CONTROL_RUNTIME_WRITER=CONTROL_KERNEL' in kernel
    assert 'CONTROL_PROVIDER_FALLBACK=false' in kernel
    assert 'CONTROL_A2=false' in kernel


def test_no_legacy_runtime_workflow_names_or_provider_markers():
    forbidden = {
        'canonical-b1-dual-executor-v1.yml',
        'scheduled-worker-a-v2.yml',
        'scheduled-worker-b-v2.yml',
        'worker-b-wake-bridge-v1.yml',
        'cloudflare-b1-shadow-v1.yml',
        'cloudflare-assurance-preflight-v1.yml',
        'groq-standby-preflight-v1.yml',
        'private-control-deterministic-validation-v1.yml',
        'private-reconcile-readonly-probe.yml',
    }
    names = {p.name for p in Path('.github/workflows').glob('*.yml')}
    assert names.isdisjoint(forbidden)
