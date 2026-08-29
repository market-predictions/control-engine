from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.validate_retired_control_workflows import RetiredWorkflowError, validate_retired_workflow

ROOT = Path(__file__).resolve().parents[1]
CARRIER = ROOT / ".github" / "workflows" / "private-control-deterministic-validation-v1.yml"
ACTUATOR = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"

VALID_RETIRED_STUB = """name: Example retired workflow [RETIRED]

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  retired:
    runs-on: ubuntu-latest
    steps:
      - name: Reject retired runtime
        shell: bash
        run: |
          set -euo pipefail
          echo '::error::RETIRED_FOR_CONTROL_MINIMAL_CORE_V1'
          echo 'Use current Control runtime.'
          exit 1
"""


class PrivateControlCiCarrierV1Tests(unittest.TestCase):
    def test_carrier_is_private_read_only_exact_candidate_bound_and_credential_bounded(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        top_permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]

        self.assertIn("market-predictions/control-plane.git", text)
        self.assertIn("permission-contents: 'read'", text)
        self.assertNotIn("permission-contents: 'write'", text)
        self.assertIn("contents: read", top_permissions)
        self.assertNotIn("contents: write", top_permissions)
        self.assertNotIn("actions: write", top_permissions)
        self.assertNotIn("pull-requests: write", top_permissions)
        self.assertIn("[[ \"$CANDIDATE_SHA\" =~ ^[0-9a-f]{40}$ ]]", text)
        self.assertIn("git -C \"$repo\" checkout --detach --quiet FETCH_HEAD", text)
        self.assertIn("test \"$(git -C \"$repo\" rev-parse HEAD)\" = \"$CANDIDATE_SHA\"", text)
        self.assertIn("unset CONTROL_GITHUB_READ_TOKEN auth_header", text)
        self.assertLess(text.index("unset CONTROL_GITHUB_READ_TOKEN auth_header"), text.index("python -m py_compile"))

    def test_carrier_runs_current_minimal_core_validation_profile_not_retired_runtime_tests(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        self.assertIn("tools/control_minimal_mission_feed_v1.py", text)
        self.assertIn("tools/mission_contract_v1.py", text)
        self.assertIn("test -f tests/test_mission_contract_v1.py", text)
        self.assertIn("test -f tests/test_control_minimal_mission_feed_v1.py", text)
        self.assertIn("test_mission_contract_v1.py", text)
        self.assertIn("test_control_minimal_mission_feed_v1.py", text)
        self.assertIn("profile=CONTROL_MINIMAL_CORE_V1", text)
        self.assertIn("runtime_model=CONTROL_MINIMAL_CORE_V1", text)
        self.assertIn("mandatory_convergence_cleanup=true", text)
        self.assertIn(":20  GitHub deterministic reconcile -> Feed queue", text)
        self.assertIn(":30  ChatGPT A1", text)
        self.assertIn(":35  ChatGPT A2", text)
        self.assertIn(":55  ChatGPT B1", text)

        for retired_test in (
            "test_control_queue_v1.py",
            "test_control_orchestration_v1.py",
            "test_control_stale_queue_inertness_v1.py",
        ):
            self.assertNotIn(retired_test, text)

    def test_carrier_captured_validation_subprocess_is_fail_fast(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        capture_start = text.index("set +e")
        inner_fail_fast = text.index("set -euo pipefail", capture_start + len("set +e"))
        first_private_check = text.index("python -m py_compile", capture_start)
        capture_end = text.index(') >"$log" 2>&1', capture_start)

        self.assertLess(capture_start, inner_fail_fast)
        self.assertLess(inner_fail_fast, first_private_check)
        self.assertLess(first_private_check, capture_end)
        self.assertIn("rc=$?", text[capture_end:])
        self.assertIn('if [ "$rc" -ne 0 ]; then', text[capture_end:])

    def test_carrier_keeps_private_validation_output_bounded_and_ephemeral(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        self.assertIn(") >\"$log\" 2>&1", text)
        self.assertNotIn("cat \"$log\"", text)
        self.assertNotIn("upload-artifact", text)
        self.assertIn("private-validation.log", text)
        self.assertIn("trap 'rm -rf \"$root\"' EXIT", text)
        self.assertIn("CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=FAIL profile=CONTROL_MINIMAL_CORE_V1 candidate_sha=$CANDIDATE_SHA", text)
        self.assertIn("CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=PASS profile=CONTROL_MINIMAL_CORE_V1 candidate_sha=$CANDIDATE_SHA", text)

    def test_carrier_uses_trusted_structural_retirement_validator(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        self.assertIn('$GITHUB_WORKSPACE/scripts/validate_retired_control_workflows.py', text)
        for path in (
            ".github/workflows/control-manual-run-delivery.yml",
            ".github/workflows/control-zero-relay-dispatch.yml",
            ".github/workflows/control-zero-relay-implementation.yml",
            ".github/workflows/control-zero-relay-assurance.yml",
            ".github/workflows/control-zero-relay-provider-preflight.yml",
        ):
            self.assertIn(path, text)
        self.assertNotIn("grep -Fq '[RETIRED]'", text)
        self.assertNotIn("! grep -Fq 'contents: write'", text)
        self.assertNotIn("! grep -Fq 'actions: write'", text)

    def test_retirement_validator_rejects_write_all_extra_jobs_steps_and_commands(self) -> None:
        mutations = {
            "write-all": VALID_RETIRED_STUB.replace("permissions:\n  contents: read", "permissions: write-all"),
            "extra-job": VALID_RETIRED_STUB + "\n  active:\n    runs-on: ubuntu-latest\n    steps:\n      - name: Active\n        run: echo active\n",
            "extra-step": VALID_RETIRED_STUB.replace("          exit 1", "          exit 1\n      - name: Active\n        shell: bash\n        run: echo active"),
            "dangerous-command": VALID_RETIRED_STUB.replace("          echo 'Use current Control runtime.'", "          python dangerous.py"),
            "uses-step": VALID_RETIRED_STUB.replace("        shell: bash", "        uses: actions/checkout@v4\n        shell: bash"),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = root / "valid.yml"
            valid.write_text(VALID_RETIRED_STUB, encoding="utf-8")
            validate_retired_workflow(valid)
            for name, payload in mutations.items():
                path = root / f"{name}.yml"
                path.write_text(payload, encoding="utf-8")
                with self.subTest(name=name):
                    with self.assertRaises(RetiredWorkflowError):
                        validate_retired_workflow(path)

    def test_carrier_has_connector_compatible_trusted_comment_launch(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        self.assertIn("issue_comment:", text)
        self.assertIn("types: [created]", text)
        self.assertIn("github.event.comment.user.login == 'market-predictions'", text)
        self.assertIn("startsWith(github.event.comment.body, 'CONTROL_PRIVATE_VALIDATE_V1 ')", text)
        self.assertIn('candidate_sha="${COMMENT_BODY#CONTROL_PRIVATE_VALIDATE_V1 }"', text)
        self.assertIn('[[ "$candidate_sha" =~ ^[0-9a-f]{40}$ ]]', text)
        self.assertIn("INPUT_CANDIDATE_SHA: ${{ inputs.candidate_sha }}", text)
        self.assertNotIn("schedule:", text)
        self.assertNotIn("cron:", text)
        self.assertNotIn("gh workflow run", text)

    def test_launch_path_does_not_expand_minimal_core_or_legacy_b1_authority(self) -> None:
        carrier = CARRIER.read_text(encoding="utf-8")
        actuator = ACTUATOR.read_text(encoding="utf-8")
        self.assertNotIn("canonical-b1-dual-executor-v1.yml", carrier)
        self.assertNotIn("PUBLIC_CONTROL_CI_RUN_ID", carrier)
        self.assertNotIn("PUBLIC_CONTROL_CI_EXECUTOR_SHA", carrier)
        self.assertNotIn("CONTROL_PRIVATE_VALIDATE_V1", actuator)
        self.assertNotIn("permission-actions: 'write'", actuator)
        self.assertNotIn("gh workflow run", actuator)
        self.assertIn("GITHUB_ACTIONS_SEMANTIC_ASSURANCE=false", actuator)
        self.assertIn("GITHUB_ACTIONS_WORKER_SCHEDULER=false", actuator)


if __name__ == "__main__":
    unittest.main()
