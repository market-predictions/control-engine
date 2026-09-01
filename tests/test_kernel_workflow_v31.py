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


def test_kernel_fails_closed_on_wrong_private_runtime_authority_without_paid_branch_protection_dependency():
    value = text()
    assert 'Validate canonical private runtime authority' in value
    assert "repository.get('full_name') != 'market-predictions/control-plane'" in value
    assert "repository.get('private') is not True" in value
    assert "branches/control-runtime-state" in value
    assert "branch.get('name') != 'control-runtime-state'" in value
    assert 'CONTROL_RUNTIME_AUTHORITY=FAIL_CLOSED_REPOSITORY' in value
    assert 'CONTROL_RUNTIME_AUTHORITY=FAIL_CLOSED_BRANCH' in value
    assert "branch.get('protected')" not in value
    assert 'CONTROL_RUNTIME_PROTECTION_REQUIRED=false' in value
    assert 'CONTROL_RUNTIME_WRITE_GUARD=CAS_SCOPE_VALIDATION' in value
    guard = value.index('Validate canonical private runtime authority')
    for later in (
        'Execute deterministic TICK',
        'Execute authenticated CLAIM',
        'Execute authenticated atomic RECORD',
        'Execute authenticated RELEASE',
    ):
        assert guard < value.index(later)


def test_runtime_and_target_capabilities_are_separate_repository_scoped_and_least_privilege():
    value = text()
    assert 'repositories: control-plane' in value
    assert 'Create exact target-repository capability' in value
    assert 'repositories: ${{ steps.plan.outputs.repo }}' in value
    assert 'owner: ${{ steps.plan.outputs.owner }}' in value
    target = value.split('Create exact target-repository capability', 1)[1].split('Reconcile active native Codex B1 evidence', 1)[0]
    assert 'permission-contents: write' in target
    assert 'permission-issues: write' in target
    assert 'permission-pull-requests: read' in target
    assert 'permission-checks: read' in target
    assert 'permission-statuses: write' in target
    assert 'permission-pull-requests: write' not in target


def test_workflow_dispatch_semantic_role_remains_authenticated_and_not_user_supplied():
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


def test_a1_issue_comment_is_transport_only_and_actor_bound():
    value = text()
    assert 'issue_comment:' in value
    assert 'types: [created]' in value
    assert "github.event.issue.number == 100" in value
    assert "github.event.comment.user.login == vars.CONTROL_A1_GITHUB_ACTOR" in value
    assert "startsWith(github.event.comment.body, 'CONTROL_V3_1_A1_COMMAND_V1')" in value
    assert 'parse_a1_command' in value
    assert 'python scripts/control_kernel_v31.py claim --role implementation_operations --worker A1' in value
    assert 'python scripts/control_kernel_v31.py record --role implementation_operations --worker A1' in value
    assert 'python scripts/control_kernel_v31.py release --role implementation_operations --worker A1' in value
    assert 'CONTROL_A1_COMMENT=TRANSPORT_ONLY' in value


def test_a1_transport_cannot_supply_b1_role_worker_or_verdict():
    value = text()
    transport = value.split('Execute A1 transport CLAIM', 1)[1].split('Start kernel-owned native Codex B1 run', 1)[0]
    assert '--role governance_release_assurance' not in transport
    assert '--worker B1' not in transport
    assert 'verdict' not in transport.lower()
    assert 'CONTROL_A1_SUPPLIED_B1_VERDICT=false' in value


def test_codex_b1_binding_stays_inside_existing_kernel_workflow():
    value = text()
    assert 'python scripts/control_codex_v31.py plan-start' in value
    assert 'python scripts/control_codex_v31.py plan-active' in value
    assert 'python scripts/control_codex_v31.py start' in value
    assert 'python scripts/control_codex_v31.py reconcile' in value
    assert 'CONTROL_B1_SEMANTIC_EXECUTOR=TRUSTED_CODEX_GITHUB_REVIEW' in value
    assert len(list(Path('.github/workflows').glob('*.yml'))) == 3


def test_tick_plans_and_executes_one_exact_task_identity():
    value = text()
    assert 'CONTROL_KERNEL_TARGET_TASK_ID=' in value
    assert 'CONTROL_TARGET_TASK_ID:' in value
    assert '[ -n "$task_id" ]' in value
    assert '[ -z "$task_id" ]' in value


def test_public_kernel_has_no_semantic_provider_credentials_or_a2():
    value = text()
    for forbidden in ('CLOUDFLARE_API_TOKEN', 'GROQ_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY'):
        assert forbidden not in value
    assert 'CONTROL_PROVIDER_FALLBACK=false' in value
    assert 'CONTROL_A2=false' in value


def test_schedule_only_runs_deterministic_tick_plus_bounded_codex_reconciliation_and_never_preclaims_a1():
    value = text()
    assert "cron: '*/15 * * * *'" in value
    assert "github.event_name == 'schedule' || inputs.command == 'TICK'" in value
    assert 'python scripts/control_kernel_v31.py tick' in value
    assert 'Reconcile active native Codex B1 evidence' in value
    scheduled_section = value.split('Plan exact target-repository capability', 1)[1].split('Execute authenticated CLAIM', 1)[0]
    assert 'claim --role implementation_operations --worker A1' not in scheduled_section


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
