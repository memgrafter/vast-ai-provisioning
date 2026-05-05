import json
import unittest
from pathlib import Path


class LaunchPolicyConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads(Path("config/launch-policy.l40s-prototype.json").read_text())

    def test_required_top_level_keys_exist(self):
        required = {
            "name",
            "purpose",
            "market",
            "template",
            "model",
            "storage",
            "gpu",
            "network",
            "pricing",
            "reliability",
            "spot",
            "selection",
        }
        self.assertLessEqual(required, set(self.policy))

    def test_current_model_contract(self):
        model = self.policy["model"]
        self.assertEqual(model["id"], "cyankiwi/Qwen3.5-9B-AWQ-4bit")
        self.assertEqual(model["served_model_name"], "qwen3.5-9b-awq")
        self.assertEqual(model["max_model_len"], 8192)
        self.assertEqual(model["quantization"], "compressed-tensors")

    def test_gpu_ram_policy_is_stored_in_mb(self):
        self.assertEqual(self.policy["gpu"]["min_gpu_total_ram_mb"], 21000)

    def test_known_machine_lists_are_present(self):
        preferred = set(self.policy["selection"]["preferred_machine_ids"])
        greylisted = set(self.policy["selection"]["greylisted_machine_ids"])
        self.assertIn(1569, preferred)
        self.assertIn(68063, preferred)
        self.assertIn(8357, greylisted)

    def test_download_size_estimate_exists_for_effective_cost(self):
        self.assertIn("expected_model_download_tb", self.policy["selection"])
        self.assertGreater(self.policy["selection"]["expected_model_download_tb"], 0)


if __name__ == "__main__":
    unittest.main()
