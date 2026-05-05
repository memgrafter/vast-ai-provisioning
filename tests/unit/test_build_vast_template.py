import importlib.util
import json
import shlex
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_vast_template", ROOT / "scripts" / "build_vast_template.py")
build_vast_template = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_vast_template)


class BuildVastTemplateTests(unittest.TestCase):
    def setUp(self):
        self.template = json.loads((ROOT / "config" / "templates" / "vllm-r2-base.public.json").read_text())
        self.model = json.loads((ROOT / "config" / "models" / "qwen3.5-9b-awq.json").read_text())

    def parse_env(self, env_string):
        tokens = shlex.split(env_string)
        env = {}
        ports = []
        i = 0
        while i < len(tokens):
            if tokens[i] == "-e":
                key, value = tokens[i + 1].split("=", 1)
                env[key] = value
                i += 2
            elif tokens[i] == "-p":
                ports.append(tokens[i + 1])
                i += 2
            else:
                i += 1
        return env, ports

    def test_builds_current_public_safe_template_from_local_specs(self):
        payload = build_vast_template.build_template(self.template, self.model)
        env, ports = self.parse_env(payload["env"])

        self.assertEqual(payload["image"], "vastai/vllm")
        self.assertEqual(payload["tag"], "v0.20.0-cuda-13.0")
        self.assertEqual(payload["model_profile"], "qwen3.5-9b-awq")
        self.assertIn("8000:8000", ports)
        self.assertEqual(env["R2_PREFIX"], "cyankiwi/Qwen3.5-9B-AWQ-4bit")
        self.assertEqual(env["MODEL_DIR"], "/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit")
        self.assertEqual(env["VLLM_MODEL"], "/workspace/models/cyankiwi/Qwen3.5-9B-AWQ-4bit")
        self.assertEqual(env["SERVED_MODEL_NAME"], "qwen3.5-9b-awq")
        self.assertEqual(env["VLLM_MAX_MODEL_LEN"], "8192")
        self.assertEqual(env["VLLM_HOST"], "127.0.0.1")
        self.assertEqual(env["VLLM_PORT"], "18000")
        self.assertEqual(env["VLLM_ARGS"], "")
        self.assertEqual(env["AUTH_EXCLUDE"], "8000")
        self.assertEqual(env["R2_BUCKET"], "<your-r2-bucket>")
        self.assertEqual(env["R2_ENDPOINT"], "https://<account-id>.r2.cloudflarestorage.com")

    def test_rejects_secret_env_names(self):
        self.template["env_map"]["AWS_ACCESS_KEY_ID"] = "not-a-real-value"
        with self.assertRaises(ValueError):
            build_vast_template.build_template(self.template, self.model)

    def test_payload_contains_no_obvious_secret_or_pii_values(self):
        payload = build_vast_template.build_template(self.template, self.model)
        text = json.dumps(payload, sort_keys=True)
        forbidden = [
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "VLLM_API_KEY=",
            "HF_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
        ]
        for value in forbidden:
            self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
