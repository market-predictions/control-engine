from pathlib import Path


WORKFLOW = Path('.github/workflows/control-v4-runtime-carrier.yml')
CARRIER = Path('scripts/control_v4_runtime_carrier.py')


def _workflow_section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_stale_or_old_generation_command_is_rejected_before_private_write_capability() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    admission = _workflow_section(
        text,
        '- name: Reject stale or misbound command before private capability',
        '- name: Create exact private runtime capability',
    )
    private_capability = _workflow_section(
        text,
        '- name: Create exact private runtime capability',
        '- name: Execute bounded typed V4 runtime carrier',
    )
    carrier = _workflow_section(
        text,
        '- name: Execute bounded typed V4 runtime carrier',
        '- name: Publish public-safe carrier result',
    )

    assert 'CONTROL_V4_PUBLIC_COMMAND_CREATED_AT: ${{ github.event.comment.created_at }}' in admission
    assert "CONTROL_V4_TICK_MAX_AGE_SECONDS: '120'" in admission
    assert 'parse_public_command(raw_command)' in admission
    assert '6a9a7e0b18b08191876c134d83cfbba2:c06686c07f09e444' in admission
    assert 'EXPECTED_RUN_ID.fullmatch(command["run_id"])' in admission
    assert '0 <= age_seconds <= max_age' in admission
    assert "output.write(f\"admitted={'true' if admitted else 'false'}\\n\")" in admission
    assert "if: ${{ steps.admission.outputs.admitted == 'true' }}" in private_capability
    assert "if: ${{ steps.admission.outputs.admitted == 'true' }}" in carrier
    assert text.index('- name: Reject stale or misbound command before private capability') < text.index(
        '- name: Create exact private runtime capability'
    )


def test_pre_capability_fence_does_not_reconstruct_public_history() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    admission = _workflow_section(
        text,
        '- name: Reject stale or misbound command before private capability',
        '- name: Create exact private runtime capability',
    )
    assert 'github.event.comment.created_at' in admission
    assert '/issues/106/comments' not in admission
    assert 'cursor' not in admission.lower()
    assert 'retry' not in admission.lower()
    assert 'yielded_task_tokens' not in admission


def test_supersession_is_revalidated_after_private_state_read_and_before_tick_transition() -> None:
    text = CARRIER.read_text(encoding='utf-8')
    main = text.split('def main() -> int:', 1)[1]
    assert 'state = _load_current()' in main
    assert '_assert_tick_not_superseded(command)' in main
    assert '_state, result = _tick(command, state, now=now)' in main
    assert main.index('state = _load_current()') < main.index('_assert_tick_not_superseded(command)')
    assert main.index('_assert_tick_not_superseded(command)') < main.index('_state, result = _tick(command, state, now=now)')


def test_supersession_uses_immutable_comment_identity_without_new_runtime_state() -> None:
    text = CARRIER.read_text(encoding='utf-8')
    section = text.split('def _assert_tick_not_superseded', 1)[1].split('def _update_refs_exact', 1)[0]
    assert 'CONTROL_V4_PUBLIC_COMMAND_ID' in section
    assert 'CONTROL_V4_PUBLIC_COMMAND_CREATED_AT' in section
    assert f'issues/{{PUBLIC_COMMAND_ISSUE}}/comments' in section
    assert 'per_page=100&sort=created&direction=asc' in section
    assert 'len(comments) >= 100' in section
    assert 'user.get("login") != PUBLIC_COMMAND_ACTOR' in section
    assert 'other.get("run_id") != command.get("run_id")' in section
    assert 'other_created > created_at or (other_created == created_at and other_id > command_id)' in section
    assert 'TICK command superseded by later same-run command' in section
    for forbidden in ('cursor', 'retry ledger', 'transport_state', 'last_tick_id', 'last_command_id'):
        assert forbidden not in section.lower()


def test_workflow_passes_command_identity_to_carrier_and_echoes_it_in_result_envelope() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    carrier = _workflow_section(
        text,
        '- name: Execute bounded typed V4 runtime carrier',
        '- name: Publish public-safe carrier result',
    )
    publisher = _workflow_section(
        text,
        '- name: Publish public-safe carrier result',
        '- name: Fail workflow after safe error publication',
    )
    assert 'CONTROL_ENGINE_TOKEN: ${{ github.token }}' in carrier
    assert 'CONTROL_V4_PUBLIC_COMMAND_ID: ${{ github.event.comment.id }}' in carrier
    assert 'CONTROL_V4_PUBLIC_COMMAND_CREATED_AT: ${{ github.event.comment.created_at }}' in carrier
    assert 'COMMAND_COMMENT_ID: ${{ github.event.comment.id }}' in publisher
    assert 'payload["command_comment_id"] = int(os.environ["COMMAND_COMMENT_ID"])' in publisher
    assert '"command_comment_id" in payload' in publisher
