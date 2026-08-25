from __future__ import annotations

from pathlib import Path
import re
import sys


def apply(root: Path) -> None:
    wf = root / ".github/workflows/canonical-b1-dual-executor-v1.yml"
    tests = root / "tests/test_canonical_b1_dual_executor_v1.py"

    text = wf.read_text(encoding="utf-8")
    old = "  CONTROL_CI_WORKFLOW_ID: 337765381\n"
    if text.count(old) != 1:
        raise SystemExit("global workflow id mismatch")
    text = text.replace(old, "")

    old = (
        '          GH_TOKEN="$CONTROL_TOKEN" gh api "repos/${TARGET_REPOSITORY}/actions/runs/${ci_run_id}" > "$RUNNER_TEMP/required-ci.json"\n'
        '          jq -e --arg sha "$TARGET_CANDIDATE_SHA" --argjson workflow_id "$CONTROL_CI_WORKFLOW_ID" --argjson run_id "$ci_run_id" \'\n'
    )
    new = (
        '          GH_TOKEN="$CONTROL_TOKEN" gh api "repos/${TARGET_REPOSITORY}/actions/runs/${ci_run_id}" > "$RUNNER_TEMP/required-ci.json"\n'
        '          ci_workflow_id="$(jq -r \'.workflow_id // empty\' "$RUNNER_TEMP/required-ci.json")"\n'
        '          [[ "$ci_workflow_id" =~ ^[0-9]+$ ]]\n'
        '          jq -e --arg sha "$TARGET_CANDIDATE_SHA" --argjson workflow_id "$ci_workflow_id" --argjson run_id "$ci_run_id" \'\n'
    )
    if text.count(old) != 1:
        raise SystemExit("pre-semantic CI block mismatch")
    text = text.replace(old, new)

    old = "          printf 'ci_run_id=%s\\n' \"$ci_run_id\" >> \"$GITHUB_OUTPUT\"\n"
    if text.count(old) != 1:
        raise SystemExit("CI output mismatch")
    text = text.replace(old, old + "          printf 'ci_workflow_id=%s\\n' \"$ci_workflow_id\" >> \"$GITHUB_OUTPUT\"\n")

    old = "          REQUIRED_CI_RUN_ID: ${{ steps.evidence.outputs.ci_run_id }}\n"
    if text.count(old) != 1:
        raise SystemExit("terminal env mismatch")
    text = text.replace(old, old + "          REQUIRED_CI_WORKFLOW_ID: ${{ steps.evidence.outputs.ci_workflow_id }}\n")

    old = '            jq -e --arg sha "$TARGET_CANDIDATE_SHA" --argjson workflow_id "$CONTROL_CI_WORKFLOW_ID" --argjson run_id "$REQUIRED_CI_RUN_ID" \'\n'
    new = '            jq -e --arg sha "$TARGET_CANDIDATE_SHA" --argjson workflow_id "$REQUIRED_CI_WORKFLOW_ID" --argjson run_id "$REQUIRED_CI_RUN_ID" \'\n'
    if text.count(old) != 1:
        raise SystemExit("terminal CI block mismatch")
    text = text.replace(old, new)
    wf.write_text(text, encoding="utf-8")

    text = tests.read_text(encoding="utf-8")
    old_token = "        '--argjson workflow_id \"$CONTROL_CI_WORKFLOW_ID\"',\n"
    if text.count(old_token) != 2:
        raise SystemExit("old workflow-id tokens mismatch")
    text = text.replace(old_token, "        '--argjson workflow_id \"$ci_workflow_id\"',\n", 1)
    text = text.replace(old_token, "        '--argjson workflow_id \"$REQUIRED_CI_WORKFLOW_ID\"',\n", 1)

    old = "        'printf \\'ci_run_id=%s\\\\n\\' \"$ci_run_id\" >> \"$GITHUB_OUTPUT\"',\n"
    if text.count(old) != 1:
        raise SystemExit("CI output test token mismatch")
    text = text.replace(old, old + "        'printf \\'ci_workflow_id=%s\\\\n\\' \"$ci_workflow_id\" >> \"$GITHUB_OUTPUT\"',\n")

    old = "        'REQUIRED_CI_RUN_ID: ${{ steps.evidence.outputs.ci_run_id }}',\n"
    if text.count(old) != 1:
        raise SystemExit("terminal env test token mismatch")
    text = text.replace(old, old + "        'REQUIRED_CI_WORKFLOW_ID: ${{ steps.evidence.outputs.ci_workflow_id }}',\n")

    pattern = re.compile(
        r"def test_workflow_ci_binding_uses_immutable_workflow_id_not_display_name\(\):\n.*?(?=\ndef test_start_proven_rejects_wrong_worker_and_expired_lease\(\):)",
        re.S,
    )
    lines = [
        "def test_workflow_ci_binding_is_repository_scoped_and_immutable_through_completion():",
        '    text = WORKFLOW.read_text(encoding="utf-8")',
        '    assert "CONTROL_CI_WORKFLOW_ID: 337765381" not in text',
        '    evidence = text.split("- name: Collect exact evidence and execute deterministic route", 1)[1]',
        '    evidence = evidence.split("- name: Revalidate exact claim and persist terminal result", 1)[0]',
        "    assert 'repos/${TARGET_REPOSITORY}/actions/runs/${ci_run_id}' in evidence",
        "    assert 'ci_workflow_id=' in evidence",
        "    assert '.workflow_id // empty' in evidence",
        "    assert '[[ \"$ci_workflow_id\" =~ ^[0-9]+$ ]]' in evidence",
        "    assert '--argjson workflow_id \"$ci_workflow_id\"' in evidence",
        "    assert 'ci_workflow_id=%s' in evidence",
        "    assert text.count('.workflow_id == $workflow_id') >= 2",
        "    assert text.count('.id == $run_id') >= 2",
        "    assert '.name == \"Control Engine CI\"' not in text",
        "    assert 'REQUIRED_CI_RUN_ID: ${{ steps.evidence.outputs.ci_run_id }}' in text",
        "    assert 'REQUIRED_CI_WORKFLOW_ID: ${{ steps.evidence.outputs.ci_workflow_id }}' in text",
        '    terminal = text.split("- name: Revalidate exact claim and persist terminal result", 1)[1]',
        "    assert '--argjson workflow_id \"$REQUIRED_CI_WORKFLOW_ID\"' in terminal",
        "",
        "",
    ]
    text, count = pattern.subn("\n".join(lines), text, count=1)
    if count != 1:
        raise SystemExit("workflow-id regression function not found")
    tests.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: g8_r18_apply_v1.py <repo-root>")
    apply(Path(sys.argv[1]))
