from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CARRIER = ROOT / ".github" / "workflows" / "private-control-deterministic-validation-v1.yml"
ACTUATOR = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"


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

    def test_minimal_core_actuator_launches_existing_carrier_deterministically(self) -> None:
        text = ACTUATOR.read_text(encoding="utf-8")
        self.assertIn("name: Control Minimal Core lifecycle actuator", text)
        self.assertNotIn("\n  schedule:", text)
        self.assertIn("startsWith(github.event.comment.body, 'CONTROL_PRIVATE_VALIDATE_V1 ')", text)
        self.assertIn("permission-actions: 'write'", text)
        self.assertIn('candidate_sha="${COMMENT_BODY#CONTROL_PRIVATE_VALIDATE_V1 }"', text)
        self.assertIn('[[ "$candidate_sha" =~ ^[0-9a-f]{40}$ ]]', text)
        self.assertIn("gh workflow run \\", text)
        self.assertIn("private-control-deterministic-validation-v1.yml", text)
        self.assertIn('--ref main', text)
        self.assertIn('-f candidate_sha="$candidate_sha"', text)
        self.assertIn("GITHUB_ACTIONS_SEMANTIC_ASSURANCE=false", text)
        self.assertIn("GITHUB_ACTIONS_WORKER_SCHEDULER=false", text)

    def test_launch_path_has_no_retired_legacy_b1_dependency(self) -> None:
        combined = CARRIER.read_text(encoding="utf-8") + ACTUATOR.read_text(encoding="utf-8")
        self.assertNotIn("canonical-b1-dual-executor-v1.yml", combined)
        self.assertNotIn("PUBLIC_CONTROL_CI_RUN_ID", combined)
        self.assertNotIn("PUBLIC_CONTROL_CI_EXECUTOR_SHA", combined)


if __name__ == "__main__":
    unittest.main()
