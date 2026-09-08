from pathlib import Path


WORKFLOW = Path('.github/workflows/control-v4-runtime-carrier.yml')


def test_stale_tick_is_rejected_before_private_write_capability() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    admission = text.split('- name: Reject delayed TICK before private capability', 1)[1].split(
        '- name: Create exact private runtime capability', 1
    )[0]
    private_capability = text.split('- name: Create exact private runtime capability', 1)[1].split(
        '- name: Execute bounded typed V4 runtime carrier', 1
    )[0]
    carrier = text.split('- name: Execute bounded typed V4 runtime carrier', 1)[1].split(
        '- name: Publish public-safe carrier result', 1
    )[0]

    assert 'CONTROL_V4_PUBLIC_COMMAND_CREATED_AT: ${{ github.event.comment.created_at }}' in admission
    assert "CONTROL_V4_TICK_MAX_AGE_SECONDS: '120'" in admission
    assert 'command.startswith("CONTROL_V4_RUNTIME_TICK {")' in admission
    assert '0 <= age_seconds <= max_age' in admission
    assert "output.write(f\"admitted={'true' if admitted else 'false'}\\n\")" in admission
    assert "if: ${{ steps.admission.outputs.admitted == 'true' }}" in private_capability
    assert "if: ${{ steps.admission.outputs.admitted == 'true' }}" in carrier
    assert text.index('- name: Reject delayed TICK before private capability') < text.index(
        '- name: Create exact private runtime capability'
    )


def test_tick_admission_fence_uses_event_timestamp_not_issue_history() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    admission = text.split('- name: Reject delayed TICK before private capability', 1)[1].split(
        '- name: Create exact private runtime capability', 1
    )[0]
    assert 'github.event.comment.created_at' in admission
    assert '/issues/106/comments?' not in admission
    assert 'page=' not in admission
    assert 'cursor' not in admission.lower()
    assert 'retry' not in admission.lower()
