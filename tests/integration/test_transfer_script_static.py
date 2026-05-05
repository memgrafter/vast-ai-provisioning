import unittest
from pathlib import Path


class TransferScriptStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path("transfer_model_to_R2.sh").read_text()

    def test_model_profile_is_required_active_interface(self):
        self.assertIn("--model-profile", self.text)
        self.assertIn("ERROR: --model-profile is required", self.text)
        self.assertNotIn("HF_REPO_ID=", self.text)
        self.assertNotIn("HF_FILENAME", self.text)

    def test_model_identity_is_read_from_profile_json(self):
        self.assertIn('profile["hf_model_id"]', self.text)
        self.assertIn('profile["r2_prefix"]', self.text)

    def test_env_file_is_for_credentials_and_private_destination(self):
        self.assertIn("source env.modeltransfer", self.text)
        self.assertIn("$R2_BUCKET", self.text)
        self.assertIn("$R2_ENDPOINT", self.text)

    def test_transfer_uses_project_root_uv_venv(self):
        self.assertIn("uv venv --python 3 .venv", self.text)
        self.assertIn("uv pip install --python .venv/bin/python", self.text)
        self.assertIn(".venv/bin/hf download", self.text)
        self.assertIn(".venv/bin/aws s3 sync", self.text)
        self.assertNotIn("pip install -U", self.text)


if __name__ == "__main__":
    unittest.main()
