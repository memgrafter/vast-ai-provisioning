import unittest
from pathlib import Path


class TransferScriptStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Path("transfer_model_to_R2.sh").read_text()

    def test_requires_model_profile(self):
        self.assertIn("--model-profile", self.text)
        self.assertIn("ERROR: --model-profile is required", self.text)

    def test_reads_model_and_r2_prefix_from_profile(self):
        self.assertIn('profile["hf_model_id"]', self.text)
        self.assertIn('profile["r2_prefix"]', self.text)
        self.assertIn('profile_hf_model_id="$(printf', self.text)
        self.assertIn('profile_r2_prefix="$(printf', self.text)

    def test_keeps_secret_env_file_for_credentials_only(self):
        self.assertIn("source env.modeltransfer", self.text)
        self.assertIn("$R2_BUCKET", self.text)
        self.assertIn("$R2_ENDPOINT", self.text)
        self.assertNotIn("HF_REPO_ID=", self.text)
        self.assertNotIn("HF_FILENAME", self.text)


if __name__ == "__main__":
    unittest.main()
