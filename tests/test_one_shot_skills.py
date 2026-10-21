"""Generation boundary checks; no model calls or benchmark data."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from mvagent.utils.io import file_fingerprint
from models.execution import emit_event
from mvagent.configs.model_config import ApiVLMConfig
from mvagent.configs import MVAgentConfig
from mvagent.agents.global_agent.prompts import GLOBAL_AGENT_SYSTEM_PROMPT
from mvagent.agents.video_agent.prompts import VIDEO_PLANNER_SYSTEM_PROMPT
from mvagent.skills.bank import SkillBank
from skill_evolution.generation.generator import generate, make_bank
from skill_evolution.generation.prompts import build_prompt


class FakeClient:
    api_key = "unit-test-secret"

    def __init__(self):
        self.cfg = ApiVLMConfig(api_key="BIGMODEL_API_KEY")

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

    def test_card_count_is_a_bound_and_extra_fields_are_rejected(self):
        card = json.loads(FakeClient().chat([]))["skills"][0]
        self.assertEqual(len(make_bank({"skills": [card]}, "global", 3).cards), 1)
        self.assertEqual(len(make_bank({"skills": [card] * 3}, "global", 3).cards), 3)
        for cards in [[], [card] * 4, [{**card, "prerequisites": "Unexpected field"}]]:
            with self.assertRaises(ValueError):
                make_bank({"skills": cards}, "global", 3)

    def test_prompt_reuses_actor_instructions_and_reads_current_capacity(self):
        model = self.runtime["agents"]["video_agent"]["observer"]["model_type"]
        self.runtime["models"][model]["max_video_frames_per_request"] = 77
        self.runtime["agents"]["video_agent"]["skill"] = {"path": "existing-bank-must-not-be-input"}
        global_prompt = build_prompt(self.runtime, "global", 3)
        video_prompt = build_prompt(self.runtime, "video", 3)
        self.assertIn(GLOBAL_AGENT_SYSTEM_PROMPT, global_prompt)
        self.assertIn(VIDEO_PLANNER_SYSTEM_PROMPT, video_prompt)
        self.assertIn("share a total limit of 77 frames", global_prompt)
        self.assertIn("Each range has its own limit of 77 frames", video_prompt)
        for prompt in [global_prompt, video_prompt]:
            self.assertNotIn("existing-bank-must-not-be-input", prompt)
            self.assertNotIn("512", prompt)

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
            self.assertFalse((output / "runtime_with_skills.json").exists())
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
            self.assertEqual(summary["max_cards_per_role"], 8)
            deployment = MVAgentConfig.from_yaml(summary["runtime_config"])
            for role in ["global", "video"]:
                reference = getattr(deployment, f"{role}_agent").skill
                self.assertTrue(reference.enabled)
                self.assertEqual(reference.selection_scope, "task")
                self.assertEqual(reference.sha256, summary["bank_sha256"])
                self.assertEqual(reference.path, str(output / "bank.json"))
            manifest = json.loads((output / "source_manifest.json").read_text())
            for name, digest in manifest["files"].items():
                self.assertEqual(file_fingerprint(output / "source" / name), digest)
            self.assertNotIn(client.api_key, (output / "generation_config.json").read_text())

    def test_global_only_deployment_drops_old_video_skills_without_mutating_input(self):
        self.runtime["agents"]["video_agent"]["skill"] = dict(
            enabled=True, mode="dynamic", selection_scope="decision",
            path="old-bank.json", sha256="0" * 64)
        before = deepcopy(self.runtime)
        with tempfile.TemporaryDirectory() as directory:
            summary = generate(FakeClient(), self.runtime, ["global"], Path(directory) / "run", 3)
            deployment = json.loads(Path(summary["runtime_config"]).read_text())
            self.assertEqual(deployment["agents"]["video_agent"]["skill"], {"enabled": False})
            self.assertEqual(deployment["agents"]["global_agent"]["skill"]["selection_scope"], "task")
            for role in ["global", "video"]:
                deployment["agents"][f"{role}_agent"]["skill"] = before["agents"][f"{role}_agent"]["skill"]
            self.assertEqual(deployment, before)
            self.assertEqual(self.runtime, before)

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
