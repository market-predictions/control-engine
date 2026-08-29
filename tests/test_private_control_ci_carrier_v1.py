from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.validate_retired_control_workflows import (
    RetiredWorkflowError,
    validate_control_workflow_inventory,
    validate_read_only_convergence_workflow,
    validate_retired_workflow,
)

ROOT = Path(__file__).resolve().parents[1]
CARRIER = ROOT / ".github" / "workflows" / "private-control-deterministic-validation-v1.yml"
ACTUATOR = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
VALIDATOR = ROOT / "scripts" / "validate_retired_control_workflows.py"

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

VALID_READ_ONLY_CONVERGENCE_WORKFLOW = """name: Safe convergence validation

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          persist-credentials: false
      - name: Check boundary
        run: echo safe
"""


class PrivateControlCiCarrierV1Tests(unittest.TestCase):
    def test_carrier_is_private_read_only_exact_candidate_bound_and_credential_bounded(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        top_permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
        fetch_block = text.split("- name: Fetch exact private candidate", 1)[1].split(
            "- name: Validate exact private Control Minimal Core candidate without source leakage", 1
        )[0]
        validation_block = text.split(
            "- name: Validate exact private Control Minimal Core candidate without source leakage", 1
        )[1]

        self.assertIn("market-predictions/control-plane.git", text)
        self.assertIn("permission-contents: 'read'", text)
        self.assertNotIn("permission-contents: 'write'", text)
        self.assertIn("contents: read", top_permissions)
        self.assertNotIn("contents: write", top_permissions)
        self.assertNotIn("actions: write", top_permissions)
        self.assertNotIn("pull-requests: write", top_permissions)
        self.assertIn("[[ \"$CANDIDATE_SHA\" =~ ^[0-9a-f]{40}$ ]]", text)
        self.assertIn("git -C \"$repo\" checkout --detach --quiet FETCH_HEAD", fetch_block)
        self.assertIn("test \"$(git -C \"$repo\" rev-parse HEAD)\" = \"$CANDIDATE_SHA\"", fetch_block)
        self.assertIn("CONTROL_GITHUB_READ_TOKEN: ${{ steps.app-token.outputs.token }}", fetch_block)
        self.assertNotIn("CONTROL_GITHUB_READ_TOKEN", validation_block)
        self.assertLess(
            text.index("- name: Fetch exact private candidate"),
            text.index("- name: Validate exact private Control Minimal Core candidate without source leakage"),
        )

    def test_carrier_fences_complete_private_workflow_authority_to_trusted_main(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        fetch_block = text.split("- name: Fetch exact private candidate", 1)[1].split(
            "- name: Validate exact private Control Minimal Core candidate without source leakage", 1
        )[0]
        validation_block = text.split(
            "- name: Validate exact private Control Minimal Core candidate without source leakage", 1
        )[1]

        self.assertIn('fetch --quiet --depth=1 origin main', fetch_block)
        self.assertIn('git -C "$repo" update-ref refs/control/trusted-main "$trusted_main_sha"', fetch_block)
        self.assertIn('trusted-main-sha', fetch_block)
        self.assertIn('trusted_main_sha="$(cat "$root/trusted-main-sha")"', validation_block)
        self.assertIn('rev-parse refs/control/trusted-main', validation_block)
        self.assertIn('--repo "$repo" "$trusted_main_sha"', validation_block)
        self.assertIn("Only the explicitly", validation_block)
        self.assertIn("read-only/no-secrets/no-schedule authority envelope", validation_block)
        self.assertLess(
            validation_block.index('--repo "$repo" "$trusted_main_sha"'),
            validation_block.index("python -m unittest discover"),
        )

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
        validation_block = text.split(
            "- name: Validate exact private Control Minimal Core candidate without source leakage", 1
        )[1]
        capture_start = validation_block.index("set +e")
        inner_fail_fast = validation_block.index("set -euo pipefail", capture_start + len("set +e"))
        first_private_check = validation_block.index('$GITHUB_WORKSPACE/scripts/validate_retired_control_workflows.py', capture_start)
        capture_end = validation_block.index(') >"$log" 2>&1', capture_start)

        self.assertLess(capture_start, inner_fail_fast)
        self.assertLess(inner_fail_fast, first_private_check)
        self.assertLess(first_private_check, capture_end)
        self.assertIn("rc=$?", validation_block[capture_end:])
        self.assertIn('if [ "$rc" -ne 0 ]; then', validation_block[capture_end:])

    def test_trusted_source_checks_run_before_sanitized_candidate_tests(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        validation_block = text.split(
            "- name: Validate exact private Control Minimal Core candidate without source leakage", 1
        )[1]
        helper = validation_block.index('$GITHUB_WORKSPACE/scripts/validate_retired_control_workflows.py')
        doctrine = validation_block.index("runtime_model=CONTROL_MINIMAL_CORE_V1")
        first_test = validation_block.index("python -m unittest discover")
        pre_test = validation_block[:first_test]
        self.assertLess(helper, first_test)
        self.assertLess(doctrine, first_test)
        self.assertIn("env -i", validation_block)
        self.assertIn('HOME="$root/test-home"', validation_block)
        self.assertIn('TMPDIR="$root/test-tmp"', validation_block)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", validation_block)
        self.assertNotIn("CONTROL_GITHUB_READ_TOKEN", validation_block)
        self.assertIn('python -I "$GITHUB_WORKSPACE/scripts/validate_retired_control_workflows.py"', pre_test)
        self.assertEqual(pre_test.count("python -I -m json.tool"), 3)
        self.assertIn("python -I -m py_compile", pre_test)
        self.assertNotIn("python -m json.tool", pre_test)
        self.assertNotIn("python -m py_compile", pre_test)

    def test_carrier_keeps_private_validation_output_bounded_and_ephemeral(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        self.assertIn(") >\"$log\" 2>&1", text)
        self.assertNotIn("cat \"$log\"", text)
        self.assertNotIn("upload-artifact", text)
        self.assertIn("private-validation.log", text)
        self.assertIn("trap 'rm -rf \"$root\"' EXIT", text)
        self.assertIn("CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=FAIL profile=CONTROL_MINIMAL_CORE_V1 candidate_sha=$CANDIDATE_SHA", text)
        self.assertIn("CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=PASS profile=CONTROL_MINIMAL_CORE_V1 candidate_sha=$CANDIDATE_SHA", text)

    def test_carrier_uses_trusted_structural_workflow_authority_validator(self) -> None:
        carrier = CARRIER.read_text(encoding="utf-8")
        validator = VALIDATOR.read_text(encoding="utf-8")
        self.assertIn('$GITHUB_WORKSPACE/scripts/validate_retired_control_workflows.py', carrier)
        for path in (
            ".github/workflows/control-manual-run-delivery.yml",
            ".github/workflows/control-zero-relay-dispatch.yml",
            ".github/workflows/control-zero-relay-implementation.yml",
            ".github/workflows/control-zero-relay-assurance.yml",
            ".github/workflows/control-zero-relay-provider-preflight.yml",
        ):
            self.assertIn(path, validator)
        for path in (
            ".github/workflows/audit-control-state-freshness.yml",
            ".github/workflows/control-provider-preflight-bootstrap.yml",
            ".github/workflows/validate-agentic-runtime.yml",
            ".github/workflows/validate-provider-preflight-bootstrap.yml",
            ".github/workflows/validate-terminal-worker-completion.yml",
            ".github/workflows/validate-work-claim-lifecycle-standard.yml",
            ".github/workflows/validate-zero-relay-runtime.yml",
        ):
            self.assertIn(path, validator)
        self.assertIn("workflow filename inventory differs from trusted main", validator)
        self.assertIn("active workflow differs from trusted main", validator)
        self.assertIn("permissions must be exactly contents: read", validator)
        self.assertIn("secrets are forbidden in convergence validation workflow", validator)
        self.assertIn('"-z",', validator)
        self.assertNotIn("grep -Fq '[RETIRED]'", carrier)
        self.assertNotIn("! grep -Fq 'contents: write'", carrier)
        self.assertNotIn("! grep -Fq 'actions: write'", carrier)

    def test_retirement_validator_rejects_authority_and_shell_escape_classes(self) -> None:
        mutations = {
            "write-all": VALID_RETIRED_STUB.replace("permissions:\n  contents: read", "permissions: write-all"),
            "extra-job": VALID_RETIRED_STUB + "\n  active:\n    runs-on: ubuntu-latest\n    steps:\n      - name: Active\n        run: echo active\n",
            "extra-step": VALID_RETIRED_STUB.replace("          exit 1", "          exit 1\n      - name: Active\n        shell: bash\n        run: echo active"),
            "dangerous-command": VALID_RETIRED_STUB.replace("          echo 'Use current Control runtime.'", "          python dangerous.py"),
            "echo-breakout": VALID_RETIRED_STUB.replace("          echo 'Use current Control runtime.'", "          echo 'safe'; python dangerous.py; echo 'still echoed'"),
            "actions-expression": VALID_RETIRED_STUB.replace("          echo 'Use current Control runtime.'", "          echo '${{ github.ref_name }}'"),
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

    def test_read_only_convergence_validator_rejects_authority_expansion(self) -> None:
        mutations = {
            "write-permission": VALID_READ_ONLY_CONVERGENCE_WORKFLOW.replace(
                "contents: read", "contents: write"
            ),
            "secret": VALID_READ_ONLY_CONVERGENCE_WORKFLOW.replace(
                "run: echo safe", "run: echo '${{ secrets.BAD }}'"
            ),
            "schedule": VALID_READ_ONLY_CONVERGENCE_WORKFLOW.replace(
                "  workflow_dispatch:\n", "  workflow_dispatch:\n  schedule:\n    - cron: '17 * * * *'\n"
            ),
            "persisted-checkout": VALID_READ_ONLY_CONVERGENCE_WORKFLOW.replace(
                "persist-credentials: false", "persist-credentials: true"
            ),
            "network-transfer": VALID_READ_ONLY_CONVERGENCE_WORKFLOW.replace(
                "run: echo safe", "run: curl https://example.invalid"
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            valid = root / "valid.yml"
            valid.write_text(VALID_READ_ONLY_CONVERGENCE_WORKFLOW, encoding="utf-8")
            validate_read_only_convergence_workflow(valid)
            for name, payload in mutations.items():
                path = root / f"{name}.yml"
                path.write_text(payload, encoding="utf-8")
                with self.subTest(name=name):
                    with self.assertRaises(RetiredWorkflowError):
                        validate_read_only_convergence_workflow(path)

    def test_workflow_inventory_rejects_non_ascii_extra_rename_and_non_allowlisted_mutation(self) -> None:
        retired_rel = ".github/workflows/retired.yml"
        active_rel = ".github/workflows/active.yml"
        active_text = "name: Active\non: workflow_dispatch\njobs: {}\n"

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Control Test"], check=True)

            retired = repo / retired_rel
            active = repo / active_rel
            retired.parent.mkdir(parents=True)
            retired.write_text(VALID_RETIRED_STUB, encoding="utf-8")
            active.write_text(active_text, encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", ".github/workflows"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "trusted"], check=True)
            trusted_sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()

            validate_control_workflow_inventory(repo, trusted_sha, (retired_rel,), ())

            extra = repo / ".github/workflows/é.yml"
            extra.write_text(active_text, encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", str(extra)], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "non-ascii-extra"], check=True)
            with self.assertRaises(RetiredWorkflowError):
                validate_control_workflow_inventory(repo, trusted_sha, (retired_rel,), ())

            subprocess.run(["git", "-C", str(repo), "reset", "--hard", "-q", trusted_sha], check=True)
            active.write_text(active_text + "permissions: write-all\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", str(active)], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "mutate-active"], check=True)
            with self.assertRaises(RetiredWorkflowError):
                validate_control_workflow_inventory(repo, trusted_sha, (retired_rel,), ())

            subprocess.run(["git", "-C", str(repo), "reset", "--hard", "-q", trusted_sha], check=True)
            renamed_rel = ".github/workflows/renamed.yml"
            subprocess.run(["git", "-C", str(repo), "mv", retired_rel, renamed_rel], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "rename-retired"], check=True)
            with self.assertRaises(RetiredWorkflowError):
                validate_control_workflow_inventory(repo, trusted_sha, (retired_rel,), ())

    def test_workflow_inventory_allows_only_bounded_mutable_validator_change(self) -> None:
        retired_rel = ".github/workflows/retired.yml"
        mutable_rel = ".github/workflows/validate-agentic-runtime.yml"
        immutable_rel = ".github/workflows/active.yml"
        immutable_text = "name: Active\non: workflow_dispatch\njobs: {}\n"

        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Control Test"], check=True)

            retired = repo / retired_rel
            mutable = repo / mutable_rel
            immutable = repo / immutable_rel
            retired.parent.mkdir(parents=True)
            retired.write_text(VALID_RETIRED_STUB, encoding="utf-8")
            mutable.write_text(VALID_READ_ONLY_CONVERGENCE_WORKFLOW, encoding="utf-8")
            immutable.write_text(immutable_text, encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", ".github/workflows"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "trusted"], check=True)
            trusted_sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()

            mutable.write_text(
                VALID_READ_ONLY_CONVERGENCE_WORKFLOW.replace(
                    "name: Safe convergence validation", "name: Updated safe convergence validation"
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "-C", str(repo), "add", str(mutable)], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "safe-mutable-change"], check=True)
            validate_control_workflow_inventory(
                repo,
                trusted_sha,
                (retired_rel,),
                (mutable_rel,),
            )

            immutable.write_text(immutable_text + "# changed\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", str(immutable)], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "unsafe-immutable-change"], check=True)
            with self.assertRaises(RetiredWorkflowError):
                validate_control_workflow_inventory(
                    repo,
                    trusted_sha,
                    (retired_rel,),
                    (mutable_rel,),
                )

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
        self.assertNotIn("CONTROL_PRIVATE_VALIDATE_V1", actuator)
        self.assertNotIn("permission-actions: 'write'", actuator)
        self.assertNotIn("gh workflow run", actuator)
        self.assertIn("GITHUB_ACTIONS_SEMANTIC_ASSURANCE=false", actuator)
        self.assertIn("GITHUB_ACTIONS_WORKER_SCHEDULER=false", actuator)


if __name__ == "__main__":
    unittest.main()
