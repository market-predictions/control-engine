from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "control-v4-authority-adoption.yml"
BASE = "a" * 40
CANDIDATE = "b" * 40
CONFIRM = "ADOPT_REVIEWED_PRIVATE_MAIN"


def _request_parser() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "      - name: Resolve exact authority adoption request\n"
    start = text.index(marker)
    heredoc = "          python3 - <<'PY'\n"
    code_start = text.index(heredoc, start) + len(heredoc)
    code_end = text.index("\n          PY", code_start)
    return textwrap.dedent(text[code_start:code_end])


def _run_parser(tmp_path: Path, **env_values: str) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update(
        {
            "GITHUB_OUTPUT": str(output),
            "EVENT_NAME": "",
            "DISPATCH_MODE": "",
            "DISPATCH_EXPECTED_BASE_SHA": "",
            "DISPATCH_CANDIDATE_SHA": "",
            "DISPATCH_CONFIRM_ADOPT": "",
            "COMMENT_BODY": "",
        }
    )
    env.update(env_values)
    result = subprocess.run(
        [sys.executable, "-c", _request_parser()],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    values: dict[str, str] = {}
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            key, value = line.split("=", 1)
            values[key] = value
    return result, values


def test_issue_comment_transport_is_owner_only_existing_issue_and_not_pr_comment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "  issue_comment:\n    types: [created]" in text
    assert "github.actor == 'market-predictions'" in text
    assert "github.triggering_actor == 'market-predictions'" in text
    assert "github.event_name == 'issue_comment'" in text
    assert "github.event.action == 'created'" in text
    assert "github.event.issue.number == 106" in text
    assert "github.event.issue.pull_request == null" in text
    assert "schedule:" not in text
    assert "pull_request:" not in text


def test_rerun_principal_gate_requires_owner_as_original_and_triggering_actor_before_capability() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    gate = text.split("    runs-on: ubuntu-latest", 1)[0]
    actor = "github.actor == 'market-predictions'"
    triggering_actor = "github.triggering_actor == 'market-predictions'"
    assert actor in gate
    assert triggering_actor in gate
    capability = text.index("      - name: Create exact private authority capability")
    assert text.index(actor) < capability
    assert text.index(triggering_actor) < capability


def test_exact_issue_comment_adopt_command_normalizes_before_token_creation(tmp_path: Path) -> None:
    result, values = _run_parser(
        tmp_path,
        EVENT_NAME="issue_comment",
        COMMENT_BODY=f"CONTROL_PRIVATE_V4_ADOPT {BASE} {CANDIDATE} {CONFIRM}",
    )
    assert result.returncode == 0, result.stderr
    assert values == {
        "mode": "ADOPT",
        "expected_base_sha": BASE,
        "candidate_sha": CANDIDATE,
        "confirm_adopt": CONFIRM,
    }

    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("- name: Resolve exact authority adoption request") < text.index(
        "- name: Create exact private authority capability"
    )


@pytest.mark.parametrize(
    "body",
    [
        f"CONTROL_PRIVATE_V4_PROBE {BASE} {CANDIDATE} {CONFIRM}",
        f"CONTROL_PRIVATE_V4_ADOPT {BASE.upper()} {CANDIDATE} {CONFIRM}",
        f"CONTROL_PRIVATE_V4_ADOPT {BASE} {BASE} {CONFIRM}",
        f"CONTROL_PRIVATE_V4_ADOPT {BASE} {CANDIDATE} WRONG_CONFIRMATION",
        f"CONTROL_PRIVATE_V4_ADOPT {BASE} {CANDIDATE} {CONFIRM} EXTRA",
    ],
)
def test_issue_comment_transport_rejects_any_non_exact_command(tmp_path: Path, body: str) -> None:
    result, values = _run_parser(tmp_path, EVENT_NAME="issue_comment", COMMENT_BODY=body)
    assert result.returncode != 0
    assert values == {}


def test_workflow_dispatch_still_supports_probe_and_same_normalized_adopt(tmp_path: Path) -> None:
    probe, probe_values = _run_parser(
        tmp_path,
        EVENT_NAME="workflow_dispatch",
        DISPATCH_MODE="PROBE",
        DISPATCH_EXPECTED_BASE_SHA=BASE,
        DISPATCH_CANDIDATE_SHA=CANDIDATE,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe_values["mode"] == "PROBE"
    assert probe_values["expected_base_sha"] == BASE
    assert probe_values["candidate_sha"] == CANDIDATE

    adopt, adopt_values = _run_parser(
        tmp_path,
        EVENT_NAME="workflow_dispatch",
        DISPATCH_MODE="ADOPT",
        DISPATCH_EXPECTED_BASE_SHA=BASE,
        DISPATCH_CANDIDATE_SHA=CANDIDATE,
        DISPATCH_CONFIRM_ADOPT=CONFIRM,
    )
    assert adopt.returncode == 0, adopt.stderr
    assert adopt_values == {
        "mode": "ADOPT",
        "expected_base_sha": BASE,
        "candidate_sha": CANDIDATE,
        "confirm_adopt": CONFIRM,
    }


def test_comment_transport_feeds_unchanged_exact_old_sha_adoption_primitive() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "MODE: ${{ steps.request.outputs.mode }}" in text
    assert "EXPECTED_BASE_SHA: ${{ steps.request.outputs.expected_base_sha }}" in text
    assert "CANDIDATE_SHA: ${{ steps.request.outputs.candidate_sha }}" in text
    assert "CONFIRM_ADOPT: ${{ steps.request.outputs.confirm_adopt }}" in text
    assert "'beforeOid': before_oid" in text
    assert "'afterOid': after_oid" in text
    assert "'force': False" in text
    assert "live_main != EXPECTED_BASE" in text
    assert "merge_base != EXPECTED_BASE" in text
    assert "before_oid=EXPECTED_BASE" in text
    assert "after_oid=CANDIDATE" in text
    assert "if adopted != CANDIDATE" in text
    assert "CONTROL_V4_AUTHORITY_ADOPTION=PASS" in text
    assert "permission-contents: write" in text
    assert "permissions:\n  contents: read" in text
