import json
import unittest
from pathlib import Path


class ProfileConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = json.loads(Path("config/models/qwen3.5-9b-awq.json").read_text())
        cls.gpu = json.loads(Path("config/gpu-profiles/qwen-9b-awq-1gpu.json").read_text())
        cls.launch = json.loads(Path("config/launch-profiles/qwen3.5-9b-awq.interruptible.json").read_text())

    def test_launch_profile_references_profile_files(self):
        self.assertTrue(Path(self.launch["model_profile"]).exists())
        self.assertTrue(Path(self.launch["gpu_profile"]).exists())

    def test_current_model_contract_lives_in_model_profile(self):
        self.assertEqual(self.model["hf_model_id"], "cyankiwi/Qwen3.5-9B-AWQ-4bit")
        self.assertEqual(self.model["served_model_name"], "qwen3.5-9b-awq")
        self.assertEqual(self.model["vllm"]["max_model_len"], 8192)
        self.assertEqual(self.model["quantization"], "compressed-tensors")
        self.assertEqual(self.model["vllm"]["force_quantization"], None)

    def test_gpu_ram_policy_is_stored_in_mb_in_gpu_profile(self):
        self.assertEqual(self.gpu["min_gpu_total_ram_mb"], 21000)

    def test_known_machine_lists_are_present_in_launch_profile(self):
        preferred = set(self.launch["selection"]["preferred_machine_ids"])
        greylisted = set(self.launch["selection"]["greylisted_machine_ids"])
        self.assertIn(1569, preferred)
        self.assertIn(68063, preferred)
        self.assertIn(8357, greylisted)

    def test_download_size_estimate_lives_in_model_profile(self):
        self.assertIn("expected_model_download_tb", self.model)
        self.assertGreater(self.model["expected_model_download_tb"], 0)


if __name__ == "__main__":
    unittest.main()
