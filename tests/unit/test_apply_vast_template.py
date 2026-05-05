import importlib.util
import json
import tempfile
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
            "image_tag": "v0.20.0-cuda-13.0",
            "env": "-e A=B",
        })

    def test_result_hash_id_accepts_top_level_or_template_hash(self):
        self.assertEqual(apply_vast_template.result_hash_id({"hash_id": "top"}), "top")
        self.assertEqual(apply_vast_template.result_hash_id({"template": {"hash_id": "nested"}}), "nested")
        self.assertIsNone(apply_vast_template.result_hash_id({"template": {}}))

    def test_load_manifest_requires_template_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            template = folder / "rendered.json"
            template.write_text("{}")
            with self.assertRaises(SystemExit):
                apply_vast_template.load_manifest_for_template(template)
            (folder / "manifest.json").write_text(json.dumps({"templates": {"other.json": {}}}))
            with self.assertRaises(SystemExit):
                apply_vast_template.load_manifest_for_template(template)
            (folder / "manifest.json").write_text(json.dumps({"templates": {"rendered.json": {"file": "rendered.json"}}}))
            self.assertEqual(apply_vast_template.load_manifest_for_template(template)["file"], "rendered.json")

    def test_write_launch_profile_hash_updates_template_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "launch.json"
            path.write_text(json.dumps({"name": "profile", "template": {"name": "template"}}))
            apply_vast_template.write_launch_profile_hash(path, "new-hash")
            data = json.loads(path.read_text())
            self.assertEqual(data["template"]["hash_id"], "new-hash")
            self.assertEqual(data["template"]["name"], "template")


if __name__ == "__main__":
    unittest.main()
