from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARRIER = ROOT / ".github" / "workflows" / "private-control-deterministic-validation-v1.yml"
B1 = ROOT / ".github" / "workflows" / "canonical-b1-dual-executor-v1.yml"


class PrivateControlCiCarrierV1Tests(unittest.TestCase):
    def test_carrier_is_private_read_only_and_exact_candidate_bound(self) -> None:
        text = CARRIER.read_text(encoding="utf-8")
        self.assertIn("market-predictions/control-plane.git", text)
        self.assertIn("permission-contents: 'read'", text)
        self.assertNotIn("permission-contents: 'write'", text)
        self.assertIn("[[ \"$CANDIDATE_SHA\" =~ ^[0-9a-f]{40}$ ]]", text)
        self.assertIn("git -C \"$repo\" checkout --detach --quiet FETCH_HEAD", text)
        self.assertIn("test \"$(git -C \"$repo\" rev-parse HEAD)\" = \"$CANDIDATE_SHA\"", text)
        self.assertIn("test_control_queue_v1.py", text)
        self.assertIn("test_control_orchestration_v1.py", text)
        self.assertIn("test_control_stale_queue_inertness_v1.py", text)
        self.assertIn(") >\"$log\" 2>&1", text)
        self.assertNotIn("cat \"$log\"", text)
        self.assertIn("CONTROL_PRIVATE_DETERMINISTIC_VALIDATION=PASS candidate_sha=$CANDIDATE_SHA", text)

    def test_b1_public_carrier_is_explicit_control_plane_only_not_fallback(self) -> None:
        text = B1.read_text(encoding="utf-8")
        self.assertIn("PUBLIC_CONTROL_CI_RUN_ID", text)
        self.assertIn("PUBLIC_CONTROL_CI_EXECUTOR_SHA", text)
        self.assertIn("PUBLIC_CONTROL_CI_WORKFLOW_PATH", text)
        self.assertIn('[ "$repository" = "$CONTROL_PLANE_REPOSITORY" ]', text)
        self.assertIn('[ -z "$designated_ci_run_id" ]', text)
        self.assertIn('[ "$TARGET_REPOSITORY" = "$CONTROL_PLANE_REPOSITORY" ]', text)
        self.assertIn('ci_repository="$GITHUB_REPOSITORY"', text)
        self.assertIn('.event == "workflow_dispatch"', text)
        self.assertIn('.path == $path', text)
        self.assertIn('.display_title == $title', text)
        self.assertIn('.head_sha == $sha', text)
        self.assertIn('.status == "completed"', text)
        self.assertIn('.conclusion == "success"', text)

    def test_native_target_repository_ci_path_remains(self) -> None:
        text = B1.read_text(encoding="utf-8")
        self.assertIn('GH_TOKEN="$CONTROL_TOKEN" gh api "repos/${TARGET_REPOSITORY}/actions/runs/${ci_run_id}"', text)
        self.assertIn('GH_TOKEN="$CONTROL_TOKEN" gh api "repos/${TARGET_REPOSITORY}/actions/runs/${REQUIRED_CI_RUN_ID}"', text)
        self.assertIn('if [ "$REQUIRED_CI_REPOSITORY" = "$TARGET_REPOSITORY" ]; then', text)


if __name__ == "__main__":
    unittest.main()
