"""Generation boundary checks; no model calls or benchmark data."""
import json
from pathlib import Path
import tempfile
import unittest

from mvagent.utils.io import file_fingerprint
from models.execution import emit_event
from mvagent.configs.model_config import ApiVLMConfig
from mvagent.skills.bank import SkillBank
from skill_evolution.generation.generator import generate, make_bank


class FakeClient:
    api_key = "unit-test-secret"
    cfg = ApiVLMConfig(api_key="BIGMODEL_API_KEY")

    def chat(self, messages, **kwargs):
        return '{"skills": [{"when_to_use": "A visible criterion is given.", "strategy": "Check the stated criterion."}]}'


class OneShotTests(unittest.TestCase):
    def setUp(self):
        import yaml
        self.runtime = yaml.safe_load(Path("configs/inference/modal_qwen35_35b_a3b_no_skill.yaml").read_text())

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
        client = FakeClient()
        calls = []

        def invalid(*args, **kwargs):
            calls.append(1)
            return "invalid JSON"

        client.chat = invalid
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with self.assertRaises(RuntimeError):
                generate(client, self.runtime, ["global"], output, 8)
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads((output / "global/response.json").read_text())["raw_response"], "invalid JSON")
            self.assertFalse((output / "bank.json").exists())
            with self.assertRaises(FileExistsError):
                generate(client, self.runtime, ["global"], output, 8)

    def test_both_roles_produce_a_loadable_bank_and_frozen_source(self):
        client = FakeClient()
        client.cfg.api_key = client.api_key
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            summary = generate(client, self.runtime, ["global", "video"], output, 8)
            bank = SkillBank.load(path=str(output / "bank.json"), sha256=summary["bank_sha256"])
            self.assertEqual([(c.id, c.role) for c in bank.cards], [("1", "global"), ("2", "video")])
            self.assertFalse(summary["quality_evaluated"])
            manifest = json.loads((output / "source_manifest.json").read_text())
            for name, digest in manifest["files"].items():
                self.assertEqual(file_fingerprint(output / "source" / name), digest)
            self.assertNotIn(client.api_key, (output / "generation_config.json").read_text())

    def test_truncated_response_is_preserved_but_never_published(self):
        client = FakeClient()
        raw = client.chat([])

        def truncated(*args, **kwargs):
            emit_event("model_response", finish_reason="length")
            return raw

        client.chat = truncated
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            with self.assertRaises(RuntimeError):
                generate(client, self.runtime, ["global"], output, 8)
            self.assertEqual(json.loads((output / "global/response.json").read_text())["raw_response"], raw)
            self.assertFalse((output / "bank.json").exists())


if __name__ == "__main__":
    unittest.main()
