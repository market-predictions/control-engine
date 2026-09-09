from pathlib import Path

import pytest

import scripts.control_v4_runtime_carrier as carrier
from control_engine.v4_runtime_protocol import RuntimeProtocolError, parse_public_command


WORKFLOW = Path('.github/workflows/control-v4-runtime-carrier.yml')
SCRIPT = Path('scripts/control_v4_runtime_carrier.py')
PROTOCOL = Path('control_engine/v4_runtime_protocol.py')


def test_runtime_carrier_is_owner_main_issue106_only_with_no_scheduler_or_dispatch_surface() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert '\n  issue_comment:\n    types: [created]' in text
    assert '\n  schedule:' not in text
    assert 'workflow_dispatch:' not in text
    assert 'pull_request_target:' not in text
    assert "github.repository == 'market-predictions/control-engine'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.actor == 'market-predictions'" in text
    assert "github.triggering_actor == 'market-predictions'" in text
    assert 'github.event.issue.number == 106' in text
    assert 'github.event.issue.pull_request == null' in text
    assert "startsWith(github.event.comment.body, 'CONTROL_V4_RUNTIME_TICK')" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_V4_RUNTIME_EVENT')" in text
    assert "startsWith(github.event.comment.body, 'CONTROL_V4_RUNTIME_TICK {')" not in text
    assert "startsWith(github.event.comment.body, 'CONTROL_V4_RUNTIME_EVENT {')" not in text
    assert 'f7beb2a3571eae1f' in text
    assert 'bdabf8391bbd1a6c' not in text


def test_strict_parser_accepts_canonical_multiline_tick_and_event_and_existing_space_framing() -> None:
    run_id = 'v4:6a9a7e0b18b08191876c134d83cfbba2:f7beb2a3571eae1f:0123456789abcdef0123456789abcdef'
    tick_json = '{"run_id":"' + run_id + '","yielded_task_tokens":[]}'
    event_json = (
        '{"run_id":"' + run_id + '","task_token":"' + ('a' * 64)
        + '","event":"YIELD","repository":"market-predictions/control-engine","action":"BUILD"}'
    )

    assert parse_public_command('CONTROL_V4_RUNTIME_TICK\n' + tick_json) == {
        'kind': 'TICK',
        'run_id': run_id,
        'yielded_task_tokens': [],
    }
    assert parse_public_command('CONTROL_V4_RUNTIME_TICK ' + tick_json) == {
        'kind': 'TICK',
        'run_id': run_id,
        'yielded_task_tokens': [],
    }
    event = parse_public_command('CONTROL_V4_RUNTIME_EVENT\n' + event_json)
    assert event['kind'] == 'EVENT'
    assert event['run_id'] == run_id
    assert event['event'] == 'YIELD'
    assert event['task_token'] == 'a' * 64

    with pytest.raises(RuntimeProtocolError):
        parse_public_command('CONTROL_V4_RUNTIME_TICKX ' + tick_json)


def test_runtime_carrier_exposes_raw_comment_to_same_protocol_parser_for_admission_execution_and_supersession() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    admission = text.split('Reject stale or misbound command before private capability', 1)[1].split(
        'Create exact private runtime capability', 1
    )[0]
    carrier_step = text.split('Execute bounded typed V4 runtime carrier', 1)[1].split(
        'Publish public-safe carrier result', 1
    )[0]
    script = SCRIPT.read_text(encoding='utf-8')

    assert 'CONTROL_V4_PUBLIC_COMMAND: ${{ github.event.comment.body }}' in admission
    assert 'parse_public_command(raw_command)' in admission
    assert 'CONTROL_V4_PUBLIC_COMMAND: ${{ github.event.comment.body }}' in carrier_step
    assert 'run: python scripts/control_v4_runtime_carrier.py' in carrier_step
    assert 'other = parse_public_command(other_body)' in script
    assert 'command = parse_public_command(raw_command)' in script
    assert 'control_v4_public_command_normalize' not in text + script


def test_runtime_carrier_installs_same_pinned_schema_dependency_as_ci() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    install = 'python -m pip install --disable-pip-version-check jsonschema==4.25.1'
    assert '- name: Install runtime dependencies' in text
    assert install in text
    assert text.index('- name: Setup Python') < text.index(install)
    assert text.index(install) < text.index('- name: Create exact private runtime capability')


def test_public_workflow_token_cannot_write_repository_contents_and_private_token_is_exactly_scoped() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert 'permissions:\n  contents: read\n  issues: write' in text
    capability = text.split('Create exact private runtime capability', 1)[1].split(
        'Execute bounded typed V4 runtime carrier', 1
    )[0]
    assert 'actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1' in capability
    assert 'owner: market-predictions' in capability
    assert 'repositories: control-plane' in capability
    assert 'permission-contents: write' in capability
    assert 'permission-actions: write' not in capability
    assert 'permission-administration: write' not in capability
    assert 'permission-pull-requests: write' not in capability


def test_private_runtime_write_is_one_file_exact_old_ref_cas_with_atomic_commit_boundary() -> None:
    text = SCRIPT.read_text(encoding='utf-8')
    assert 'QUEUE_PATH = "control/DISPATCH_QUEUE.json"' in text
    assert 'RUNTIME_BRANCH = "control-runtime-state"' in text
    assert 'mutation UpdateRefs($input: UpdateRefsInput!)' in text
    assert '"name": "refs/heads/main"' in text
    assert '"beforeOid": main_oid' in text
    assert '"afterOid": main_oid' in text
    assert '"beforeOid": runtime_before_oid' in text
    assert '"afterOid": runtime_after_oid' in text
    assert '"force": False' in text
    assert 'if _branch_head("main") != state["main_sha"]' in text
    assert 'if _branch_head(RUNTIME_BRANCH) != state["runtime_sha"]' in text
    assert 'if current_blob != state["queue_blob"]' in text
    assert '"base_tree": parent_tree' in text
    assert '"path": QUEUE_PATH' in text
    assert '"parents": [state["runtime_sha"]]' in text

    write = text.split('def _write_queue_exact', 1)[1].split('def _assert_public_target_repository', 1)[0]
    assert '_update_refs_exact(' in write
    assert '_await_git_ref_head' not in write
    assert '_git_ref_head' not in write
    assert 'mandatory private queue readback failed' not in write
    assert 'private authority moved during runtime write' not in write


def test_atomic_main_and_runtime_ref_cas_rejects_authority_interleaving_without_runtime_move(monkeypatch) -> None:
    main_a = "a" * 40
    main_b = "b" * 40
    runtime_a = "c" * 40
    runtime_b = "d" * 40
    runtime_ref = f"refs/heads/{carrier.RUNTIME_BRANCH}"
    refs = {"refs/heads/main": main_b, runtime_ref: runtime_a}

    def fake_request_json(url, *, headers=None, method="GET", payload=None, allow_404=False):
        assert url == carrier.GRAPHQL
        assert method == "POST"
        updates = payload["variables"]["input"]["refUpdates"]
        assert updates == [
            {"name": "refs/heads/main", "beforeOid": main_a, "afterOid": main_a, "force": False},
            {"name": runtime_ref, "beforeOid": runtime_a, "afterOid": runtime_b, "force": False},
        ]
        if any(refs[update["name"]] != update["beforeOid"] for update in updates):
            return {"errors": [{"message": "stale ref"}]}
        next_refs = dict(refs)
        for update in updates:
            next_refs[update["name"]] = update["afterOid"]
        refs.update(next_refs)
        return {"data": {"updateRefs": {"clientMutationId": "test"}}}

    monkeypatch.setattr(carrier, "_private_headers", lambda: {})
    monkeypatch.setattr(carrier, "_request_json", fake_request_json)
    monkeypatch.setattr(carrier, "_assert_current_command_fresh_at_ref_cas", lambda source_queue: None)
    monkeypatch.setenv(
        "CONTROL_V4_PUBLIC_COMMAND",
        'CONTROL_V4_RUNTIME_EVENT {"run_id":"cas-test","task_token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","event":"YIELD","repository":"market-predictions/control-engine","action":"BUILD"}',
    )

    with pytest.raises(carrier.StaleWriteError):
        carrier._update_refs_exact(
            repository_node_id="repo-node",
            main_oid=main_a,
            runtime_before_oid=runtime_a,
            runtime_after_oid=runtime_b,
            client_id="test",
            source_queue={},
        )

    assert refs["refs/heads/main"] == main_b
    assert refs[runtime_ref] == runtime_a


def test_transport_has_no_generic_queue_patch_and_public_result_forbids_private_task_and_authority_fields() -> None:
    workflow = WORKFLOW.read_text(encoding='utf-8')
    script = SCRIPT.read_text(encoding='utf-8')
    protocol = PROTOCOL.read_text(encoding='utf-8')
    combined = workflow + script + protocol
    assert 'CONTROL_V4_RUNTIME_PATCH_QUEUE' not in combined
    assert '"task_id",\n    "gap_id",\n    "mission_id",' in protocol
    assert '"acceptance",' in protocol
    assert '"mission_contract_blob_sha",' in protocol
    assert '"repository_authority_blob_sha",' in protocol
    assert '"task_token": task_token(task, run_id)' in protocol
    assert 'CONTROL_V4_RUNTIME_RESULT' in workflow
    assert 'RESULT_JSON' in workflow


def test_carrier_is_activation_bounded_and_private_targets_fail_closed_before_acquire() -> None:
    script = SCRIPT.read_text(encoding='utf-8')
    assert 'INTEGRATION_ENABLED_REQUIRES_SEPARATE_REVIEWED_CARRIER_EXTENSION' in script
    assert 'carrier V1 requires integration disabled' in script
    assert 'target repository is not publicly readable by carrier V1' in script

    tick = script.split('def _tick', 1)[1].split('def _validate_public_ref_for_task', 1)[0]
    public_check = '_assert_public_target_repository(task["repository"])'
    cas = 'state = _write_queue_exact(state, acquired, reason=reason)'
    assert public_check in tick
    assert cas in tick
    assert tick.index(public_check) < tick.index(cas)
    assert 'unsupported-target-block' not in tick
    assert 'TARGET_REPOSITORY_NOT_PUBLICLY_READABLE_BY_CARRIER_V1' not in tick


def test_candidate_less_build_proves_public_target_before_acquire_and_work_capsule() -> None:
    text = SCRIPT.read_text(encoding='utf-8')
    assert 'def _assert_public_target_repository(repository: str) -> None:' in text
    assert '_assert_public_target_repository(repository)' in text.split('def _target_pr_candidate', 1)[1].split('def _tick', 1)[0]
    tick = text.split('def _tick', 1)[1].split('def _validate_public_ref_for_task', 1)[0]
    public_check = '_assert_public_target_repository(task["repository"])'
    cas = 'state = _write_queue_exact(state, acquired, reason=reason)'
    result_build = 'work_result = safe_work_capsule('
    assert public_check in tick
    assert result_build in tick
    assert cas in tick
    assert tick.index(public_check) < tick.rindex(result_build) < tick.index(cas)
    assert 'return state, work_result' in tick.split(cas, 1)[1]
    assert 'reconcile_review_candidate_drift_v4(' not in tick


def test_carrier_does_not_persist_private_state_in_public_repository() -> None:
    text = SCRIPT.read_text(encoding='utf-8')
    assert 'PRIVATE_REPOSITORY = "market-predictions/control-plane"' in text
    assert 'git/blobs' in text
    assert 'git/trees' in text
    assert 'git/commits' in text
    assert 'control-runtime-state' in text
    assert 'with open(' not in text.replace('with open(output_path', '')
