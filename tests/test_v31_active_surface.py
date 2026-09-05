from pathlib import Path


def workflows() -> dict[str, str]:
    return {p.name: p.read_text(encoding='utf-8') for p in Path('.github/workflows').glob('*.yml')}


def test_current_surface_is_passive_v4_with_bounded_rollback_validation_support():
    names = sorted(workflows())
    assert names == [
        'ci.yml',
        'control-v4-authority-adoption.yml',
        'private-control-v3-1-validation.yml',
    ]
    assert not Path('scripts/control_kernel_v31.py').exists()
    assert not Path('docs/PUBLIC_PRIVATE_BOUNDARY_V3_1.md').exists()
    assert Path('scripts/validate_private_control_v31.py').is_file()
    assert Path('control_engine/kernel_v31.py').is_file()
    assert Path('control_engine/migration_v31.py').is_file()


def test_no_reachable_semantic_runtime_writer_remains_after_v31_writer_retirement():
    current = workflows()
    assert 'control-kernel-v3-1.yml' not in current
    assert 'control-runtime-state' not in current['ci.yml']

    validator = current['private-control-v3-1-validation.yml']
    assert 'control-runtime-state' not in validator
    assert 'permission-contents: write' not in validator
    assert 'CONTROL_PRIVATE_RUNTIME_MUTATION=false' in validator

    carrier = current['control-v4-authority-adoption.yml']
    assert 'control-runtime-state' not in carrier
    assert 'DISPATCH_QUEUE.json' not in carrier
    assert 'cron:' not in carrier
    assert 'CLAIM' not in carrier
    assert 'RECORD' not in carrier
    assert 'RELEASE' not in carrier


def test_v4_authority_carrier_is_manual_principal_main_only_and_least_privilege():
    carrier = workflows()['control-v4-authority-adoption.yml']
    assert 'workflow_dispatch:' in carrier
    assert '\n  schedule:' not in carrier
    assert 'issue_comment:' not in carrier
    assert 'pull_request_target:' not in carrier
    assert "github.repository == 'market-predictions/control-engine'" in carrier
    assert "github.ref == 'refs/heads/main'" in carrier
    assert "github.actor == 'market-predictions'" in carrier
    assert 'permissions:\n  contents: read' in carrier

    capability = carrier.split('Create exact private authority capability', 1)[1].split(
        'Prove or perform exact-old-SHA authority adoption', 1
    )[0]
    assert 'actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1' in capability
    assert 'owner: market-predictions' in capability
    assert 'repositories: control-plane' in capability
    assert 'permission-contents: write' in capability
    assert 'permission-actions: write' not in capability
    assert 'permission-administration: write' not in capability
    assert 'permission-pull-requests: write' not in capability


def test_v4_authority_carrier_uses_exact_old_sha_graphql_and_disposable_probe():
    carrier = workflows()['control-v4-authority-adoption.yml']
    assert "'https://api.github.com/graphql'" in carrier
    assert 'mutation UpdateRefs($input: UpdateRefsInput!)' in carrier
    assert 'updateRefs(input: $input)' in carrier
    assert "'beforeOid': before_oid" in carrier
    assert "'afterOid': after_oid" in carrier
    assert "'force': False" in carrier
    assert "MAIN_REF = 'refs/heads/main'" in carrier
    assert "ZERO_OID = '0' * 40" in carrier
    assert "live_main != EXPECTED_BASE" in carrier
    assert "merge_base != EXPECTED_BASE" in carrier
    assert "comparison.get('behind_by') != 0" in carrier
    assert "MODE == 'PROBE'" in carrier
    assert 'expect_rejection=True' in carrier
    assert "canary_branch = f'control-v4-authority-canary-{RUN_ID}'" in carrier
    assert 'disposable authority canary cleanup failed' in carrier
    assert 'private main changed during authority probe' in carrier
    assert 'CONTROL_V4_AUTHORITY_UPDATE_REFS_PROBE=PASS' in carrier
    assert 'ADOPT_REVIEWED_PRIVATE_MAIN' in carrier
    assert "MODE == 'ADOPT'" in carrier
    assert 'before_oid=EXPECTED_BASE' in carrier
    assert 'after_oid=CANDIDATE' in carrier
    assert 'mandatory exact authority post-adoption readback failed' in carrier


def test_v4_authority_probe_reconciles_ambiguous_canary_writes_fact_first():
    carrier = workflows()['control-v4-authority-adoption.yml']

    assert 'canary_created = False' not in carrier
    attempted = carrier.index('canary_create_attempted = True')
    create_call = carrier.index("client_id=f'control-v4-canary-create-{RUN_ID}'")
    finally_block = carrier.index('              finally:', create_call)
    reconcile_read = carrier.index('canary = rest_get(canary_path, allow_404=True)', finally_block)
    assert attempted < create_call < finally_block < reconcile_read

    assert "if canary_sha != live_main:" in carrier
    assert 'disposable authority canary entered unexpected state; refusing cleanup' in carrier
    assert 'except Exception as exc:' in carrier
    assert 'delete_error = exc' in carrier
    assert 'remaining = rest_get(canary_path, allow_404=True)' in carrier
    assert "if remaining_sha != live_main:" in carrier
    assert 'disposable authority canary changed during cleanup; refusing delete' in carrier
    assert 'disposable authority canary delete outcome ambiguous and ref remains' in carrier


def test_no_legacy_runtime_workflow_names_or_provider_markers():
    forbidden = {
        'control-kernel-v3-1.yml',
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
    assert set(workflows()).isdisjoint(forbidden)
