import unittest

from scripts.monitor_instance_readiness import analyze_logs, build_arg_parser, port_url

IMAGE = "vastai/vllm:v0.22.0-cuda-13.0"


class AnalyzeLogsTests(unittest.TestCase):
    def test_detects_image_cached_and_pull_seen(self):
        logs = f"Status: Image is up to date for {IMAGE}\nPulling from vastai/vllm"
        signals = analyze_logs(logs, IMAGE)
        self.assertTrue(signals.image_cached)
        self.assertTrue(signals.image_pull_seen)

    def test_detects_provisioning_and_r2_lifecycle(self):
        logs = "\n".join([
            "Provisioning instance with manifest",
            "Provisioning model from R2",
            "R2 speed test enabled: minimum 100 MB/s",
            "Syncing s3://bucket/prefix -> /workspace/models/model",
            "Sync started at: 2026-05-05T10:00:00+00:00",
            "Transferred: 1 GiB / 10 GiB, 10%, 150 MiB/s, ETA 1m",
            "R2 sync progress: 1000000000 bytes across 3 files at /workspace/models/model; largest=900000000 model.safetensors",
            "download: file.safetensors",
            "Sync finished at: 2026-05-05T10:02:00+00:00",
            "Synced bytes: 10G",
            "Provisioning complete",
        ])
        signals = analyze_logs(logs, IMAGE)
        self.assertTrue(signals.provisioning_started)
        self.assertTrue(signals.r2_sync_started)
        self.assertTrue(signals.r2_transfer_active)
        self.assertTrue(signals.r2_sync_finished)
        self.assertTrue(signals.provisioning_complete)

    def test_detects_failure_conditions(self):
        logs = "\n".join([
            "ERROR: R2 speed test below threshold: 51.20 MB/s < 100 MB/s",
            "/provisioning.sh: line 7: AWS_ACCESS_KEY_ID: missing AWS_ACCESS_KEY_ID",
            "Quantization method specified in the model config (compressed-tensors) does not match the quantization argument (awq)",
            "ValidationError: 1 validation error for ModelConfig",
            "ImportError: The 'fastokens' package (>= 0.2.0) is required when VLLM_USE_FASTOKENS=1.",
        ])
        signals = analyze_logs(logs, IMAGE)
        self.assertTrue(signals.speed_test_failed)
        self.assertTrue(signals.provisioning_failed)

    def test_warn_only_speed_test_below_threshold_is_not_fatal(self):
        logs = "WARN: R2 speed test below threshold; continuing because R2_SPEED_TEST_WARN_ONLY=true: 85.33 MB/s < 100 MB/s"
        signals = analyze_logs(logs, IMAGE)
        self.assertFalse(signals.speed_test_failed)

    def test_detects_vllm_start_and_api_ready(self):
        logs = "\n".join([
            "vllm serve /workspace/models/model --host 127.0.0.1 --port 18000",
            "Uvicorn running on http://127.0.0.1:18000",
        ])
        signals = analyze_logs(logs, IMAGE)
        self.assertTrue(signals.vllm_started)
        self.assertTrue(signals.api_ready)

    def test_ignores_cloudflare_tunnel_errors_but_keeps_real_errors(self):
        logs = "\n".join([
            "ERR Register tunnel error from server side error=\"Unauthorized: Tunnel not found\" connIndex=0 event=0 ip=198.41.200.53 trycloudflare",
            "ERROR: real provisioning failed",
        ])
        signals = analyze_logs(logs, IMAGE)
        self.assertEqual(signals.errors, ["ERROR: real provisioning failed"])


class ParserTests(unittest.TestCase):
    def test_container_port_defaults_to_vllm_api_mapping(self):
        args = build_arg_parser().parse_args(["123"])
        self.assertEqual(args.container_port, "8000/tcp")

    def test_container_port_can_be_overridden(self):
        args = build_arg_parser().parse_args(["123", "--container-port", "8080/tcp"])
        self.assertEqual(args.container_port, "8080/tcp")


class PortUrlTests(unittest.TestCase):
    def test_builds_external_url_from_mapped_8000_port(self):
        info = {"public_ipaddr": "98.84.180.4", "ports": {"8000/tcp": [{"HostPort": "40476"}]}}
        self.assertEqual(port_url(info), "http://98.84.180.4:40476")

    def test_missing_port_returns_none(self):
        self.assertIsNone(port_url({"public_ipaddr": "98.84.180.4", "ports": {}}))


if __name__ == "__main__":
    unittest.main()
