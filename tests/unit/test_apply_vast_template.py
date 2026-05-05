import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("apply_vast_template", ROOT / "scripts" / "apply_vast_template.py")
apply_vast_template = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apply_vast_template)


class ApplyVastTemplateTests(unittest.TestCase):
    def test_update_kwargs_strips_local_and_remote_metadata(self):
        payload = {
            "id": 1,
            "hash_id": "abc",
            "created_at": "now",
            "model_profile": "qwen3.5-9b-awq",
            "name": "template",
            "image": "vastai/vllm",
            "tag": "v0.20.0-cuda-13.0",
            "env": "-e A=B",
            "deleted_at": None,
        }
        kwargs = apply_vast_template.update_kwargs(payload)
        self.assertEqual(kwargs, {
            "name": "template",
            "image": "vastai/vllm",
            "tag": "v0.20.0-cuda-13.0",
            "env": "-e A=B",
        })


if __name__ == "__main__":
    unittest.main()
