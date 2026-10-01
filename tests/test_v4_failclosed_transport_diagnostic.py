from pathlib import Path


WORKFLOW = Path('.github/workflows/control-v4-runtime-carrier.yml')


def test_failclosed_transport_diagnostic_is_post_carrier_read_only_and_bounded() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    diagnostic = text.split(
        '- name: Diagnose anonymous REST budget after safe carrier error', 1
    )[1].split('- name: Auto-materialize governed exact candidate after NO_WORK', 1)[0]

    assert "if: ${{ steps.admission.outputs.admitted == 'true' && steps.carrier.outputs.ok != 'true' }}" in diagnostic
    assert 'https://api.github.com/rate_limit' in diagnostic
    assert 'CONTROL_V4_ANON_RATE_LIMIT=' in diagnostic
    assert 'Authorization' not in diagnostic
    assert 'GH_TOKEN' not in diagnostic
    assert 'CONTROL_PLANE_TOKEN' not in diagnostic
    assert 'CONTROL_ENGINE_TOKEN' not in diagnostic
    assert 'issues/106/comments' not in diagnostic
    assert 'git/blobs' not in diagnostic
    assert 'git/trees' not in diagnostic
    assert 'git/commits' not in diagnostic
    assert 'updateRefs' not in diagnostic
    assert 'CONTROL_V4_RUNTIME_RESULT' not in diagnostic


def test_failclosed_transport_diagnostic_does_not_change_carrier_result_contract() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    carrier_index = text.index('- name: Execute bounded typed V4 runtime carrier')
    diagnostic_index = text.index('- name: Diagnose anonymous REST budget after safe carrier error')
    replenish_index = text.index('- name: Auto-materialize governed exact candidate after NO_WORK')
    publish_index = text.index('- name: Publish public-safe carrier result')
    fail_index = text.index('- name: Fail workflow after safe error publication')

    assert carrier_index < diagnostic_index < replenish_index < publish_index < fail_index
    assert 'RESULT_JSON: ${{ steps.replenishment.outputs.result_json != \'\' && steps.replenishment.outputs.result_json || steps.carrier.outputs.result_json }}' in text
    assert "if: ${{ steps.carrier.outputs.ok != 'true' }}\n        run: exit 1" in text
