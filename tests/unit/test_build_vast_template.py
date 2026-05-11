import base64
import importlib.util
import json
import shlex
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_vast_template", ROOT / "scripts" / "build_vast_template.py")
build_vast_template = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build_vast_template)


class BuildVastTemplateTests(unittest.TestCase):
    def setUp(self):
        self.template = {
            "name": "fixture-template",
            "image": "vastai/vllm",
            "tag": "fixture-tag",
            "env_map": {
                "R2_BUCKET": "<your-r2-bucket>",
                "R2_ENDPOINT": "https://<account-id>.r2.cloudflarestorage.com",
                "VLLM_ARGS": "",
                "AUTH_EXCLUDE": "8000",
                "PROVISIONING_SCRIPT": "https://example.invalid/provision.sh",
            },
            "ports": {"8000": "8000"},
            "extra_filters": {},
        }
        self.model = {
            "name": "fixture-model",
            "r2_prefix": "org/model",
            "model_dir": "/workspace/models/org/model",
            "served_model_name": "fixture-served-name",
            "vllm": {
                "dtype": "half",
                "max_model_len": 4096,
                "gpu_memory_utilization": 0.82,
                "trust_remote_code": True,
                "host": "127.0.0.1",
                "port": 18000,
                "download_dir": "/workspace/models",
                "extra_args": ["--enforce-eager"],
                "force_quantization": None,
            },
        }

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

    def test_builds_template_from_local_specs(self):
        payload = build_vast_template.build_template(self.template, self.model)
        env, ports = self.parse_env(payload["env"])

        self.assertEqual(payload["image"], "vastai/vllm")
        self.assertEqual(payload["model_profile"], "fixture-model")
        self.assertIn("8000:8000", ports)
        self.assertEqual(env["R2_PREFIX"], "org/model")
        self.assertEqual(env["MODEL_DIR"], "/workspace/models/org/model")
        self.assertEqual(env["VLLM_MODEL"], "/workspace/models/org/model")
        self.assertEqual(env["SERVED_MODEL_NAME"], "fixture-served-name")
        self.assertEqual(env["VLLM_MAX_MODEL_LEN"], "4096")
        self.assertEqual(env["VLLM_GPU_MEMORY_UTILIZATION"], "0.82")
        self.assertEqual(env["VLLM_KV_CACHE_DTYPE"], "")
        self.assertEqual(env["VLLM_EXTRA_ARGS"], "--enforce-eager")
        self.assertEqual(env["VLLM_ARGS"], "")
        self.assertEqual(env["AUTH_EXCLUDE"], "8000")

    def test_current_profile_contract_is_wired_into_template(self):
        template = json.loads((ROOT / "config" / "templates" / "vllm-r2-base.public.json").read_text())
        model = json.loads((ROOT / "config" / "models" / "qwen3.5-9b-awq.json").read_text())
        payload = build_vast_template.build_template(template, model)
        env, _ = self.parse_env(payload["env"])
        self.assertEqual(payload["model_profile"], model["name"])
        self.assertEqual(env["R2_PREFIX"], model["r2_prefix"])
        self.assertEqual(env["MODEL_DIR"], model["model_dir"])
        self.assertEqual(env["SERVED_MODEL_NAME"], model["served_model_name"])
        self.assertEqual(env["VLLM_MAX_MODEL_LEN"], str(model["vllm"]["max_model_len"]))

    def test_model_max_num_seqs_maps_to_dedicated_env(self):
        model = json.loads(json.dumps(self.model))
        model["vllm"]["max_num_seqs"] = 512
        payload = build_vast_template.build_template(self.template, model)
        env, _ = self.parse_env(payload["env"])
        self.assertEqual(env["VLLM_MAX_NUM_SEQS"], "512")

    def test_speculative_config_maps_to_safe_base64_env(self):
        model = json.loads(json.dumps(self.model))
        model["vllm"]["speculative_config"] = {"method": "qwen3_next_mtp", "num_speculative_tokens": 2}
        payload = build_vast_template.build_template(self.template, model)
        env, _ = self.parse_env(payload["env"])
        decoded = json.loads(base64.b64decode(env["VLLM_SPECULATIVE_CONFIG_B64"]).decode())
        self.assertEqual(decoded, {"method": "qwen3_next_mtp", "num_speculative_tokens": 2})
        self.assertNotIn("qwen3_next_mtp", payload["env"])

    def test_kv_cache_dtype_maps_to_dedicated_env(self):
        model = json.loads(json.dumps(self.model))
        model["vllm"]["kv_cache_dtype"] = "fp8"
        payload = build_vast_template.build_template(self.template, model)
        env, _ = self.parse_env(payload["env"])
        self.assertEqual(env["VLLM_KV_CACHE_DTYPE"], "fp8")

    def test_model_max_model_len_is_required(self):
        model = json.loads(json.dumps(self.model))
        del model["vllm"]["max_model_len"]
        with self.assertRaisesRegex(ValueError, "max_model_len is required"):
            build_vast_template.build_template(self.template, model)

    def test_rejects_secret_env_names(self):
        self.template["env_map"]["AWS_ACCESS_KEY_ID"] = "not-a-real-value"
        with self.assertRaises(ValueError):
            build_vast_template.build_template(self.template, self.model)

    def test_private_overlay_can_supply_non_secret_private_values(self):
        overlay = {
            "env_map": {
                "R2_BUCKET": "private-bucket-placeholder",
                "R2_ENDPOINT": "https://private-account.example.invalid",
            }
        }
        merged = build_vast_template.deep_merge(self.template, overlay)
        payload = build_vast_template.build_template(merged, self.model)
        env, _ = self.parse_env(payload["env"])
        self.assertEqual(env["R2_BUCKET"], "private-bucket-placeholder")
        self.assertEqual(env["R2_ENDPOINT"], "https://private-account.example.invalid")

    def test_update_manifest_records_rendered_template(self):
        payload = build_vast_template.build_template(self.template, self.model)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "rendered.json"
            args = Namespace(
                template_spec=Path("config/templates/fixture.json"),
                model_profile=Path("config/models/fixture.json"),
                private_overlay=Path("config/private/fixture.json"),
            )
            build_vast_template.update_manifest(out, args, payload)
            manifest = json.loads((out.parent / "manifest.json").read_text())
            entry = manifest["templates"]["rendered.json"]
            self.assertEqual(entry["file"], "rendered.json")
            self.assertEqual(entry["model_profile_name"], "fixture-model")
            self.assertEqual(entry["template_name"], "fixture-template")

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
