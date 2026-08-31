from pathlib import Path


WORKFLOW = Path('.github/workflows/control-kernel-v3-1.yml')


def text():
    return WORKFLOW.read_text(encoding='utf-8')


def test_kernel_has_single_serialized_mutation_domain_and_never_cancels_pending_mutations():
    value = text()
    assert 'group: control-runtime-mutation' in value
    assert 'cancel-in-progress: false' in value


def test_kernel_uses_exact_pinned_ephemeral_app_token_after_preflight():
    value = text()
    assert 'bash scripts/github_app_preflight.sh' in value
    assert 'actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1' in value
    assert value.index('bash scripts/github_app_preflight.sh') < value.index('Create exact private-runtime capability')


def test_kernel_fails_closed_before_any_runtime_operation_when_runtime_branch_is_unprotected():
    value = text()
    assert 'Enforce protected canonical runtime branch' in value
    assert "branches/control-runtime-state" in value
    assert "branch.get('protected') is not True" in value
    assert 'CONTROL_RUNTIME_PROTECTION=FAIL_CLOSED_UNPROTECTED' in value
    assert 'CONTROL_RUNTIME_PROTECTION_REQUIRED=true' in value
    protection = value.index('Enforce protected canonical runtime branch')
    for later in (
        'Plan deterministic TICK target capability',
        'Execute deterministic TICK',
        'Execute authenticated CLAIM',
        'Execute authenticated atomic RECORD',
        'Execute authenticated RELEASE',
    ):
        assert protection < value.index(later)


def test_runtime_and_target_capabilities_are_separate_repository_scoped_and_least_privilege():
    value = text()
    assert 'repositories: control-plane' in value
    assert 'Create exact target-repository capability' in value
    assert 'repositories: ${{ steps.plan.outputs.repo }}' in value
    assert 'owner: ${{ steps.plan.outputs.owner }}' in value
    target = value.split('Create exact target-repository capability', 1)[1].split('Execute deterministic TICK', 1)[0]
    assert 'permission-contents: write' in target
    assert 'permission-pull-requests: read' in target
    assert 'permission-checks: read' in target
    assert 'permission-statuses: write' in target
    assert 'permission-pull-requests: write' not in target


def test_semantic_role_uses_rerun_safe_triggering_actor_not_supplied_role_or_original_actor():
    value = text()
    assert 'CONTROL_A1_GITHUB_ACTOR' in value
    assert 'CONTROL_B1_GITHUB_ACTOR' in value
    assert 'TRIGGERING_ACTOR: ${{ github.triggering_actor }}' in value
    assert 'ACTOR: ${{ github.actor }}' not in value
    assert '[ "$A1_ACTOR" != "$B1_ACTOR" ]' in value
    assert "case \"$TRIGGERING_ACTOR\" in" in value
    assert "echo 'role=implementation_operations'" in value
    assert "echo 'role=governance_release_assurance'" in value
    assert 'role:' not in value.split('workflow_dispatch:', 1)[1].split('permissions:', 1)[0]


def test_tick_plans_and_executes_one_exact_task_identity():
    value = text()
    assert 'CONTROL_KERNEL_TARGET_TASK_ID=' in value
    assert 'CONTROL_TARGET_TASK_ID: ${{ steps.plan.outputs.task_id }}' in value
    assert '[ -n "$task_id" ]' in value
    assert '[ -z "$task_id" ]' in value


def test_public_kernel_has_no_semantic_provider_credentials_or_a2():
    value = text()
    for forbidden in ('CLOUDFLARE_API_TOKEN', 'GROQ_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        assert forbidden not in value
    assert 'CONTROL_PROVIDER_FALLBACK=false' in value
    assert 'CONTROL_A2=false' in value


def test_schedule_only_runs_deterministic_tick_and_never_preclaims_semantic_work():
    value = text()
    assert "cron: '*/15 * * * *'" in value
    assert "github.event_name == 'schedule' || inputs.command == 'TICK'" in value
    assert 'python scripts/control_kernel_v31.py tick' in value
    assert 'No scheduler preclaims' not in value


def test_record_payload_enters_only_atomic_kernel_record_path():
    value = text()
    assert 'CONTROL_RESULT_PAYLOAD' in value
    assert 'python scripts/control_kernel_v31.py record' in value
    assert 'control/worker-results/' not in value


def test_no_semantic_project_integration_or_provider_route_is_present():
    value = text()
    assert 'CONTROL_PROJECT_INTEGRATION_SEMANTIC_TASK=false' in value
    assert 'canonical-b1-dual-executor' not in value
    assert 'cloudflare_b1' not in value
    assert 'codex_b1' not in value
    assert 'scheduled_worker_a_v2' not in value
    assert 'scheduled_worker_b_v2' not in value
