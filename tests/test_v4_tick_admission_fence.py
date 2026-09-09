import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.control_v4_runtime_carrier as carrier_module


WORKFLOW = Path('.github/workflows/control-v4-runtime-carrier.yml')
CARRIER = Path('scripts/control_v4_runtime_carrier.py')
RUN_ID = 'v4:6a9a7e0b18b08191876c134d83cfbba2:f7beb2a3571eae1f:' + ('a' * 32)
OTHER_RUN_ID = 'v4:6a9a7e0b18b08191876c134d83cfbba2:f7beb2a3571eae1f:' + ('b' * 32)


def _workflow_section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _tick_command(run_id: str = RUN_ID) -> dict[str, object]:
    return {'kind': 'TICK', 'run_id': run_id, 'yielded_task_tokens': []}


def _event_body(run_id: str, event: str = 'YIELD') -> str:
    return 'CONTROL_V4_RUNTIME_EVENT ' + json.dumps(
        {
            'run_id': run_id,
            'task_token': 'c' * 64,
            'event': event,
            'repository': 'market-predictions/control-engine',
            'action': 'BUILD',
        },
        separators=(',', ':'),
    )


def _tick_body(run_id: str) -> str:
    return 'CONTROL_V4_RUNTIME_TICK ' + json.dumps(
        {'run_id': run_id},
        separators=(',', ':'),
    )


def _install_supersession_fixture(monkeypatch, comments: list[dict[str, object]]) -> None:
    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_ID', '100')
    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_CREATED_AT', '2026-09-08T07:00:00Z')
    monkeypatch.setattr(carrier_module, '_public_command_headers', lambda: {})

    def fake_request_json(url, *, headers=None, method='GET', payload=None, allow_404=False):
        assert method == 'GET'
        assert payload is None
        assert '/repos/market-predictions/control-engine/issues/106/comments?' in url
        assert 'per_page=100&sort=created&direction=asc' in url
        return comments

    monkeypatch.setattr(carrier_module, '_request_json', fake_request_json)


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
    assert '6a9a7e0b18b08191876c134d83cfbba2:f7beb2a3571eae1f' in admission
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


def test_supersession_and_freshness_are_revalidated_after_private_snapshot_before_tick_transition() -> None:
    text = CARRIER.read_text(encoding='utf-8')
    main = text.split('def main() -> int:', 1)[1]
    assert 'state = _load_current()' in main
    assert '_assert_tick_not_superseded(command)' in main
    assert 'now = datetime.now(timezone.utc)' in main
    assert '_assert_tick_fresh(now=now)' in main
    assert '_state, result = _tick(command, state, now=now)' in main
    assert main.index('state = _load_current()') < main.index('_assert_tick_not_superseded(command)')
    assert main.index('_assert_tick_not_superseded(command)') < main.index('_assert_tick_fresh(now=now)')
    assert main.index('_assert_tick_fresh(now=now)') < main.index('_state, result = _tick(command, state, now=now)')


def test_transition_freshness_uses_same_immutable_comment_time_and_exact_120_second_bound(monkeypatch) -> None:
    now = datetime(2026, 9, 8, 7, 2, 0, tzinfo=timezone.utc)
    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_ID', '100')
    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_CREATED_AT', '2026-09-08T07:00:00Z')
    carrier_module._assert_tick_fresh(now=now)

    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_CREATED_AT', '2026-09-08T06:59:59.999999Z')
    with pytest.raises(carrier_module.StaleEventError, match='TICK command stale at transition'):
        carrier_module._assert_tick_fresh(now=now)

    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_CREATED_AT', '2026-09-08T07:02:00.000001Z')
    with pytest.raises(carrier_module.StaleEventError, match='TICK command stale at transition'):
        carrier_module._assert_tick_fresh(now=now)


def test_transition_freshness_is_not_anchored_to_process_start_time() -> None:
    text = CARRIER.read_text(encoding='utf-8')
    main = text.split('def main() -> int:', 1)[1]
    before_load = main.split('state = _load_current()', 1)[0]
    assert 'datetime.now(timezone.utc)' not in before_load
    assert main.index('_assert_tick_not_superseded(command)') < main.index('now = datetime.now(timezone.utc)')


def test_supersession_uses_immutable_comment_identity_without_new_runtime_state() -> None:
    text = CARRIER.read_text(encoding='utf-8')
    section = text.split('def _tick_command_identity', 1)[1].split('def _update_refs_exact', 1)[0]
    assert 'CONTROL_V4_PUBLIC_COMMAND_ID' in section
    assert 'CONTROL_V4_PUBLIC_COMMAND_CREATED_AT' in section
    assert 'TICK_MAX_AGE_SECONDS = 120' in text
    assert 'age_seconds = (current - created_at).total_seconds()' in section
    assert '0 <= age_seconds <= TICK_MAX_AGE_SECONDS' in section
    assert f'issues/{{PUBLIC_COMMAND_ISSUE}}/comments' in section
    assert 'per_page=100&sort=created&direction=asc' in section
    assert 'len(comments) >= 100' in section
    assert 'user.get("login") != PUBLIC_COMMAND_ACTOR' in section
    assert 'other.get("run_id") != command.get("run_id")' in section
    assert 'other_created > created_at or (other_created == created_at and other_id > command_id)' in section
    assert 'TICK command superseded by later same-run command' in section
    for forbidden in ('cursor', 'retry ledger', 'transport_state', 'last_tick_id', 'last_command_id'):
        assert forbidden not in section.lower()


def test_later_trusted_same_run_release_behaviorally_supersedes_earlier_tick(monkeypatch) -> None:
    _install_supersession_fixture(
        monkeypatch,
        [
            {
                'id': 101,
                'created_at': '2026-09-08T07:00:01Z',
                'body': _event_body(RUN_ID, 'YIELD'),
                'user': {'login': 'market-predictions'},
            }
        ],
    )

    with pytest.raises(
        carrier_module.StaleEventError,
        match='TICK command superseded by later same-run command',
    ):
        carrier_module._assert_tick_not_superseded(_tick_command())


def test_fresh_same_run_tick_after_progress_event_is_not_superseded(monkeypatch) -> None:
    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_ID', '102')
    monkeypatch.setenv('CONTROL_V4_PUBLIC_COMMAND_CREATED_AT', '2026-09-08T07:00:02Z')
    monkeypatch.setattr(carrier_module, '_public_command_headers', lambda: {})

    def fake_request_json(url, *, headers=None, method='GET', payload=None, allow_404=False):
        assert method == 'GET'
        assert payload is None
        return [
            {
                'id': 101,
                'created_at': '2026-09-08T07:00:01Z',
                'body': _event_body(RUN_ID, 'INTERNAL_REPAIR'),
                'user': {'login': 'market-predictions'},
            }
        ]

    monkeypatch.setattr(carrier_module, '_request_json', fake_request_json)
    carrier_module._assert_tick_not_superseded(_tick_command())


def test_supersession_ignores_foreign_actor_other_run_and_earlier_identity(monkeypatch) -> None:
    _install_supersession_fixture(
        monkeypatch,
        [
            {
                'id': 101,
                'created_at': '2026-09-08T07:00:02Z',
                'body': _event_body(RUN_ID, 'YIELD'),
                'user': {'login': 'someone-else'},
            },
            {
                'id': 102,
                'created_at': '2026-09-08T07:00:03Z',
                'body': _tick_body(OTHER_RUN_ID),
                'user': {'login': 'market-predictions'},
            },
            {
                'id': 99,
                'created_at': '2026-09-08T07:00:00Z',
                'body': _tick_body(RUN_ID),
                'user': {'login': 'market-predictions'},
            },
        ],
    )

    carrier_module._assert_tick_not_superseded(_tick_command())


def test_same_timestamp_higher_comment_id_behaviorally_supersedes_tick(monkeypatch) -> None:
    _install_supersession_fixture(
        monkeypatch,
        [
            {
                'id': 101,
                'created_at': '2026-09-08T07:00:00Z',
                'body': _tick_body(RUN_ID),
                'user': {'login': 'market-predictions'},
            }
        ],
    )

    with pytest.raises(carrier_module.StaleEventError):
        carrier_module._assert_tick_not_superseded(_tick_command())


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
