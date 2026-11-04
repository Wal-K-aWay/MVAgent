"""New-card boundaries and raw-before-rejection; no benchmark cases or model calls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from skill_evolution.infra.card_policy import PORTABILITY_RULES, require_portable_text
from skill_evolution.infra.banks import apply_edit
from skill_evolution.algorithms.one_shot.generator import generate, make_bank
from skill_evolution.algorithms.one_shot.prompts import SYSTEM as GENERATOR_SYSTEM
from skill_evolution.algorithms.rolewise.prompts import SYSTEM as OPTIMIZER_SYSTEM
from mvagent.skills.bank import SkillBank
from mvagent.configs.model_config import ApiVLMConfig


class PortabilityTests(unittest.TestCase):
    def test_benchmark_markers_rejected_in_either_runtime_text_field(self):
        for marker in ('CrossVid', 'cross-vid', 'CVBench', 'cv bench', 'MVU-Eval', 'mvu_eval',
                       'CrossVid_BU', 'CVBench_count', 'MVU_Eval_task'):
            for when, strategy in ((marker, 'Compare visible evidence.'), ('A relation must be compared.', marker)):
                with self.subTest(marker=marker, when=when), self.assertRaises(ValueError):
                    require_portable_text(when, strategy)
        require_portable_text('Compare cross-view evidence.',
                              "Use the current question's label mapping; do not assume synchronized clocks.")

    def test_both_proposal_paths_enforce_the_new_card_boundary(self):
        card = {'when_to_use': 'For CVBench questions.', 'strategy': 'Compare evidence.'}
        with self.assertRaises(ValueError):
            make_bank({'skills': [card]}, 'global', 8)
        empty = SkillBank(())
        edit = {'operation': 'add', 'target_id': '', 'hypothesis': 'A reusable relation is needed.', **card}
        with self.assertRaises(ValueError):
            apply_edit(empty, 'global', edit, 8)
        self.assertEqual(empty.cards, ())
        bank = make_bank({'skills': [{'when_to_use': 'Compare a supplied relation.',
                                     'strategy': 'Gather visible evidence for that relation.'}]}, 'global', 8)
        with self.assertRaises(ValueError):
            apply_edit(bank, 'global', {**edit, 'operation': 'revise', 'target_id': bank.cards[0].id}, 8)
        for system in (GENERATOR_SYSTEM, OPTIMIZER_SYSTEM):
            self.assertIn(PORTABILITY_RULES, system)

    def test_invalid_generated_card_keeps_raw_output_without_retry_or_deployment(self):
        import yaml
        runtime = yaml.safe_load(Path('configs/inference/modal_qwen35_9b_no_skill.yaml').read_text())
        raw = json.dumps({'skills': [{'when_to_use': 'MVU-Eval inputs.', 'strategy': 'Compare evidence.'}]})
        client = Mock(api_key='unit-test-secret', cfg=ApiVLMConfig(api_key='BIGMODEL_API_KEY'))
        client.chat.return_value = raw
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new-run'
            with self.assertRaises(RuntimeError):
                generate(client, runtime, ['global'], output, 8)
            self.assertEqual(client.chat.call_count, 1)
            self.assertEqual(json.loads((output / 'global/response.json').read_text())['raw_response'], raw)
            self.assertFalse(json.loads((output / 'global/validation.json').read_text())['valid'])
            self.assertFalse((output / 'runtime_with_skills.json').exists())


if __name__ == '__main__':
    unittest.main()
