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

    def test_writes_vllm_args_file_from_env_driven_contract(self):
        self.assertIn("> /etc/vllm-args.conf", self.text)
        for snippet in [
            "SERVED_MODEL_NAME=",
            "VLLM_DTYPE=",
            "VLLM_MAX_MODEL_LEN=",
            "VLLM_HOST=",
            "VLLM_PORT=",
            "VLLM_DOWNLOAD_DIR=",
            "VLLM_GPU_MEMORY_UTILIZATION=",
            "VLLM_TENSOR_PARALLEL_SIZE=",
            "VLLM_KV_CACHE_DTYPE=",
            "VLLM_TRUST_REMOTE_CODE=",
            "VLLM_FORCE_QUANTIZATION=",
            "VLLM_MAX_NUM_SEQS=",
            "VLLM_SPECULATIVE_CONFIG_B64=",
            "VLLM_EXTRA_ARGS=",
            "--max-num-seqs",
            "--tensor-parallel-size",
            "--kv-cache-dtype",
            "--speculative-config",
            "--api-key ${VLLM_API_KEY}",
        ]:
            self.assertIn(snippet, self.text)

    def test_does_not_hardcode_current_model_or_force_stale_awq_quantization(self):
        self.assertNotIn("--served-model-name qwen3.5-9b-awq", self.text)
        self.assertNotIn("--quantization awq", self.text)

    def test_uses_rclone_optimized_download_path(self):
        self.assertIn("R2_TRANSFER_TOOL=\"${R2_TRANSFER_TOOL:-rclone}\"", self.text)
        self.assertIn("rclone copy", self.text)
        self.assertIn("--transfers", self.text)
        self.assertIn("--multi-thread-streams", self.text)

    def test_speed_test_prefers_static_object_and_logs_range_failures(self):
        self.assertIn("R2_SPEED_TEST_KEY=\"${R2_SPEED_TEST_KEY:-_vast/r2-speed-test.bin}\"", self.text)
        self.assertIn("R2_SPEED_TEST_WARN_ONLY=\"${R2_SPEED_TEST_WARN_ONLY:-false}\"", self.text)
        self.assertIn("continuing because R2_SPEED_TEST_WARN_ONLY=true", self.text)
        self.assertIn("head-object", self.text)
        self.assertIn("falling back to model prefix", self.text)
        self.assertIn("R2 speed test ranged GET failed", self.text)
        self.assertIn("tail -20", self.text)

    def test_emits_structured_gpu_nvlink_topology(self):
        self.assertIn("emit_nvlink_status", self.text)
        self.assertIn("VAST_GPU_NVLINK_JSON ", self.text)
        self.assertIn("gpu_nvlink_summary", self.text)
        self.assertIn("gpu_nvlink_gpu", self.text)
        self.assertIn("gpu_nvlink_link", self.text)
        self.assertIn("nvidia-smi", self.text)
        self.assertIn("topo", self.text)
        self.assertIn("nvlink", self.text)
        self.assertIn("has_nvlink", self.text)
        self.assertIn("sample_id", self.text)

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
