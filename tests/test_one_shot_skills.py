"""Generation boundary checks; no model calls or benchmark data."""
import json
from pathlib import Path
import tempfile
import unittest

from mvagent.configs.model_config import ApiVLMConfig
from skill_evolution.one_shot import generate, make_bank


class FakeClient:
    api_key = "unit-test-secret"
    cfg = ApiVLMConfig(api_key="BIGMODEL_API_KEY")

    def chat(self, messages, **kwargs):
        return '{"skills": [{"when_to_use": "A visible criterion is given.", "strategy": "Check the stated criterion."}]}'


class OneShotTests(unittest.TestCase):
    def test_limits_and_role(self):
        value = json.loads(FakeClient().chat([]))
        bank = make_bank(value, "video", 8, offset=3)
        self.assertEqual(bank.cards[0].id, "4")
        self.assertEqual(bank.cards[0].role, "video")
        self.assertEqual(len(bank.eligible(role="video", stage="initial")), 1)
        self.assertNotIn("when_to_use", bank.render(["4"]))
        value["skills"][0]["strategy"] = "word " * 1201
        with self.assertRaises(ValueError):
            make_bank(value, "video", 8)

    def test_invalid_output_is_saved_and_not_retried(self):
        import yaml
        runtime = yaml.safe_load(Path("configs/skill_evolution/runtime/dynamic_35b_embedding.yaml").read_text())
        client = FakeClient()
        calls = []

        def invalid(*args, **kwargs):
            calls.append(1)
            return "invalid JSON"

        client.chat = invalid
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with self.assertRaises(RuntimeError):
                generate(client, runtime, ["global"], output, 8)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads((output / "global/response.json").read_text())["raw_response"], "invalid JSON")
            self.assertFalse((output / "bank.json").exists())
            with self.assertRaises(FileExistsError):
                generate(client, runtime, ["global"], output, 8)


if __name__ == "__main__":
    unittest.main()
