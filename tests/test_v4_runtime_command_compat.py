from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


RUN_ID = "sched11-20260906T152720Z-8b7c91"
TOKEN = "3b583f6ae60b5dc738836ededf4c687e7e2d633b744761173085bd02ddc3e969"
CANDIDATE = {
    "candidate_head_branch": "r2/32-executable-assurance-kernel",
    "candidate_pr_number": 48,
    "candidate_sha": "8ee4f1b9cdfa315cc8886d35bbf8d61eb444bdf2",
    "expected_base_branch": "main",
    "expected_base_sha": "acdc5d5bae018b64aa082ad68c3e94de955e91a3",
}
EVENT_PREFIX = "CONTROL_V4_RUNTIME_EVENT "
WORKFLOW = Path(".github/workflows/control-v4-runtime-carrier.yml")


def nested_review_unavailable(**extra: object) -> str:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "REVIEW_UNAVAILABLE",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate": CANDIDATE,
    }
    payload.update(extra)
    return EVENT_PREFIX + json.dumps(payload, separators=(",", ":"))


def workflow_normalizer_source() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    step = text.split("Normalize observed V4 Runner compatibility envelope", 1)[1].split(
        "Execute bounded typed V4 runtime carrier", 1
    )[0]
    source = step.split("python - <<'PY'\n", 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(source)


def run_workflow_normalizer(command: str, tmp_path: Path) -> str:
    env_file = tmp_path / "github-env"
    env = dict(os.environ)
    env["CONTROL_V4_PUBLIC_COMMAND"] = command
    env["GITHUB_ENV"] = str(env_file)
    subprocess.run(
        [sys.executable, "-c", workflow_normalizer_source()],
        check=True,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "CONTROL_V4_PUBLIC_COMMAND<<__CONTROL_V4_COMMAND__"
    assert lines[-1] == "__CONTROL_V4_COMMAND__"
    return "\n".join(lines[1:-1])


def test_observed_review_unavailable_envelope_normalizes_to_existing_holder_schema(tmp_path: Path) -> None:
    normalized = run_workflow_normalizer(nested_review_unavailable(), tmp_path)
    assert normalized.startswith(EVENT_PREFIX)
    payload = json.loads(normalized[len(EVENT_PREFIX):])
    assert payload == {
        "event": "REVIEW_UNAVAILABLE",
        "holder_candidate_sha": CANDIDATE["candidate_sha"],
        "holder_expected_base_branch": CANDIDATE["expected_base_branch"],
        "holder_expected_base_sha": CANDIDATE["expected_base_sha"],
        "run_id": RUN_ID,
        "task_token": TOKEN,
    }


def test_exact_flat_protocol_event_is_unchanged(tmp_path: Path) -> None:
    command = EVENT_PREFIX + json.dumps({
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "REVIEW_UNAVAILABLE",
        "holder_candidate_sha": CANDIDATE["candidate_sha"],
        "holder_expected_base_branch": CANDIDATE["expected_base_branch"],
        "holder_expected_base_sha": CANDIDATE["expected_base_sha"],
    }, separators=(",", ":"))
    assert run_workflow_normalizer(command, tmp_path) == command


def test_extra_nested_field_remains_fail_closed_for_carrier(tmp_path: Path) -> None:
    command = nested_review_unavailable(unexpected="value")
    assert run_workflow_normalizer(command, tmp_path) == command


def test_other_event_is_not_normalized(tmp_path: Path) -> None:
    payload = {
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "EXTERNAL_PASS",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate": CANDIDATE,
    }
    command = EVENT_PREFIX + json.dumps(payload, separators=(",", ":"))
    assert run_workflow_normalizer(command, tmp_path) == command


def test_malformed_or_incomplete_candidate_is_not_normalized(tmp_path: Path) -> None:
    candidate = dict(CANDIDATE)
    candidate.pop("expected_base_sha")
    payload = {
        "run_id": RUN_ID,
        "task_token": TOKEN,
        "event": "REVIEW_UNAVAILABLE",
        "repository": "solidprivacy-nl/solidsecurity",
        "candidate": candidate,
    }
    command = EVENT_PREFIX + json.dumps(payload, separators=(",", ":"))
    assert run_workflow_normalizer(command, tmp_path) == command


def test_runtime_workflow_preserves_existing_carrier_entrypoint_and_surface() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    normalize_name = "Normalize observed V4 Runner compatibility envelope"
    carrier_name = "Execute bounded typed V4 runtime carrier"
    assert text.index(normalize_name) < text.index(carrier_name)
    carrier_step = text.split(carrier_name, 1)[1].split("Publish public-safe carrier result", 1)[0]
    assert "run: python scripts/control_v4_runtime_carrier.py" in carrier_step
    assert not Path("scripts/control_v4_runtime_command_compat.py").exists()
