import unittest
from pathlib import Path


class ProvisioningScriptStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path("provision_vast_vllm_from_r2.sh").read_text()

    def test_shell_safety_and_required_envs(self):
        self.assertIn("set -euo pipefail", self.text)
        for name in [
            "R2_BUCKET",
            "R2_PREFIX",
            "R2_ENDPOINT",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "MODEL_DIR",
        ]:
            self.assertIn(f": \"${{{name}:?missing {name}}}\"", self.text)

    def test_writes_vllm_args_file_with_current_working_contract(self):
        self.assertIn("cat > /etc/vllm-args.conf", self.text)
        for snippet in [
            "--served-model-name qwen3.5-9b-awq",
            "--max-model-len 8192",
            "--host 127.0.0.1",
            "--port 18000",
            "--api-key ${VLLM_API_KEY}",
        ]:
            self.assertIn(snippet, self.text)

    def test_does_not_force_stale_awq_quantization(self):
        self.assertNotIn("--quantization awq", self.text)

    def test_uses_rclone_optimized_download_path(self):
        self.assertIn("R2_TRANSFER_TOOL=\"${R2_TRANSFER_TOOL:-rclone}\"", self.text)
        self.assertIn("rclone copy", self.text)
        self.assertIn("--transfers", self.text)
        self.assertIn("--multi-thread-streams", self.text)

    def test_no_obvious_secret_echoes(self):
        forbidden = [
            "echo $AWS_ACCESS_KEY_ID",
            "echo ${AWS_ACCESS_KEY_ID}",
            "echo $AWS_SECRET_ACCESS_KEY",
            "echo ${AWS_SECRET_ACCESS_KEY}",
            "echo $VLLM_API_KEY",
            "echo ${VLLM_API_KEY}",
        ]
        for snippet in forbidden:
            self.assertNotIn(snippet, self.text)


if __name__ == "__main__":
    unittest.main()
