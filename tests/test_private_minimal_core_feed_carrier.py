from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "scheduled-worker-a-v2.yml"
SCRIPT = ROOT / "scripts" / "private_minimal_core_feed.py"


class PrivateMinimalCoreFeedCarrierTests(unittest.TestCase):
    def test_existing_actuator_accepts_feed_without_becoming_scheduler(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("github.event.comment.body == 'CONTROL_CORE_FEED_V1'", text)
        self.assertIn("CONTROL_CORE_FEED_V1)\n              python scripts/private_minimal_core_feed.py", text)
        self.assertNotIn("schedule:", text)
        self.assertIn("GITHUB_ACTIONS_WORKER_SCHEDULER=false", text)
        self.assertIn("GITHUB_ACTIONS_SEMANTIC_IMPLEMENTATION=false", text)
        self.assertIn("GITHUB_ACTIONS_SEMANTIC_ASSURANCE=false", text)

    def test_carrier_executes_private_main_policy_against_only_runtime_queue(self):
        text = SCRIPT.read_text(encoding="utf-8")
        compile(text, str(SCRIPT), "exec")
        self.assertIn('MAIN_REF = "main"', text)
        self.assertIn('RUNTIME_REF = integration.CONTROL_RUNTIME_REF', text)
        self.assertIn('PRIVATE_FEED_REL = "tools/control_minimal_mission_feed_v1.py"', text)
        self.assertIn('changed != {QUEUE_REL}', text)
        self.assertIn('core.validate(queue)', text)
        self.assertIn('core.validate(readback)', text)
        self.assertIn('_remote_ref_sha(token, main_dir, MAIN_REF) != observed_main', text)
        self.assertIn('integration._remote_identity(token, runtime_dir) != observed_runtime', text)

    def test_carrier_has_no_semantic_worker_or_provider_path(self):
        text = SCRIPT.read_text(encoding="utf-8").lower()
        self.assertNotIn("openai", text)
        self.assertNotIn("cloudflare", text)
        self.assertNotIn("groq", text)
        self.assertNotIn("assure", text)
        self.assertNotIn("merge_pull", text)


if __name__ == "__main__":
    unittest.main()
