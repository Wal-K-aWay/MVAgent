"""Controlled entry/body factors, actual planner injection, and forced-run isolation."""
from copy import deepcopy
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
import unittest

import test_skill_evaluation as evaluation_fixture
from mvagent.agents.global_agent.agent import GlobalAgent
from mvagent.agents.video_agent.agent import VideoAgent
from mvagent.engine import MVAgentEngine
from mvagent.skills.bank import SkillBank, load_skill
from skill_evolution.configs.manual import (
    BODY_STYLES, ENTRY_STYLES, load_manual, manual_bank,
)
from skill_evolution.infra.banks import (
    freeze_bank, runtime_with_bank, runtime_with_forced_card,
)


ROOT = Path(__file__).resolve().parents[1]


def definitions():
    return [load_manual(ROOT / f'src/skill_evolution/configs/manual_{role}.json')
            for role in ('global', 'video')]


def runtime():
    return {'models': {'actor': {'seed': 0}}, 'agents': {
        'global_agent': {'max_steps': 5, 'skill': {'enabled': False}},
        'video_agent': {'max_steps': 5, 'skill': {
            'enabled': True, 'mode': 'static', 'path': 'existing.md', 'sha256': 'a' * 64}},
    }}


def mixed_bank():
    return SkillBank.from_dict({'schema_version': 3, 'skills': [
        {'meta': {'id': sid, 'role': role, 'stages': ['initial', 'evidence']},
         'when_to_use': f'ROUTING_ONLY_{sid}',
         'strategy': f'Inspect the visible discriminant for method {sid}.'}
        for sid, role in [('1', 'global'), ('2', 'global'), ('3', 'video')]
    ]})


def planner_prompt(role, skill, selected_id, *, answer_only=False):
    """Capture the real planner call after its normal dynamic/static skill branch."""
    requests, selections = [], []

    def decide(prompt, **kwargs):
        if kwargs['schema_name'] == 'skill_selection':
            selections.append(prompt)
            return {'status': 'ok', 'value': {'selected_skill_ids': [selected_id]}}
        requests.append(prompt)
        return {'status': 'ok', 'value': {}}

    shared = dict(decide_json=decide, skill_selection_scope='task',
                  skill_selector_model=None, _skill_selection_cache={})
    if role == 'global':
        agent = SimpleNamespace(**shared, question='Compare the visible features.',
            video_ids=['left', 'right'], video_metadata={}, video_paths={},
            cache_dir=None, visual_model=None, max_videos_per_watch=4,
            decision_skill=skill, memory=SimpleNamespace(
                reports=[], watch_results=[], render_action_history=lambda: '(none)'))
        GlobalAgent._request_decision(agent, answer_only=answer_only)
    else:
        agent = SimpleNamespace(**shared, planning_skill=skill,
            _skill_selection_request=None, _render_decision_feedback=lambda: '',
            duration_sec=20, max_video_frames_per_request=512, max_ranges_per_action=8,
            memory=SimpleNamespace(has_observations=False,
                render_planner_view=lambda **kwargs: '(none)'))
        VideoAgent._call_planner_impl(agent, instruction='Inspect the visible feature.',
                                     request_id='request-1')
    assert len(requests) == 1
    return requests[0], selections


class ManualDiagnosticsTest(unittest.TestCase):
    def test_entry_variants_keep_each_body_identical(self):
        for definition in definitions():
            for body in BODY_STYLES:
                banks = [manual_bank(definition, body=body, entry=entry)
                         for entry in ENTRY_STYLES]
                for index, method in enumerate(definition['methods']):
                    sid = str(index + 1)
                    with self.subTest(role=definition['role'], body=body, method=method['key']):
                        self.assertEqual(len({bank.render([sid]) for bank in banks}), 1)
                        self.assertEqual(len({bank.cards[index].when_to_use for bank in banks}), 3)
                        self.assertEqual(banks[0].cards[index].strategy, method['strategies'][body])
                        self.assertTrue(all(len(bank.eligible(role=definition['role'], stage='initial')) <= 8
                                            for bank in banks))

    def test_id_permutation_changes_labels_without_changing_methods(self):
        for definition in definitions():
            methods = {m['key']: m for m in definition['methods']}
            for order in permutations(methods):
                bank = manual_bank(definition, body='concise', entry='relation', order=order)
                for index, key in enumerate(order):
                    card = bank.cards[index]
                    self.assertEqual(card.id, str(index + 1))
                    self.assertEqual(card.strategy, methods[key]['strategies']['concise'])
                    self.assertEqual(card.when_to_use, methods[key]['applicability']['relation'])
            keys = list(methods)
            for invalid in (keys[:-1], keys + keys[:1], keys[:-1] + ['not-a-method']):
                with self.assertRaises(ValueError):
                    manual_bank(definition, body='concise', entry='relation', order=invalid)

    def test_forced_and_selected_body_reach_identical_actual_planner_prompt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for definition in definitions():
                role = definition['role']
                for body in BODY_STYLES:
                    bank = manual_bank(definition, body=body, entry='contrastive')
                    snapshot = freeze_bank(bank, root / 'banks')
                    natural = runtime_with_bank(runtime(), snapshot)
                    for card in bank.cards:
                        forced = runtime_with_forced_card(natural, snapshot, role=role,
                            card_id=card.id, directory=root / 'strategies')
                        static_config = forced['agents'][f'{role}_agent']['skill']
                        static = load_skill(path=static_config['path'], sha256=static_config['sha256'])
                        loaded_static = MVAgentEngine._load_configured_skill(SimpleNamespace(**static_config))
                        dynamic_config = natural['agents'][f'{role}_agent']['skill']
                        dynamic = MVAgentEngine._load_configured_skill(SimpleNamespace(
                            **dynamic_config, retrieval_top_k=8, embedding=None))
                        self.assertEqual(static, bank.render([card.id]))
                        self.assertEqual(loaded_static, static)
                        for terminal in ((False, True) if role == 'global' else (False,)):
                            with self.subTest(role=role, body=body, card=card.id, terminal=terminal):
                                actual, selected = planner_prompt(role, dynamic, card.id, answer_only=terminal)
                                forced_prompt, forced_selected = planner_prompt(role, static, card.id, answer_only=terminal)
                                self.assertEqual(actual, forced_prompt)
                                self.assertIn(card.strategy, actual)
                                self.assertNotIn(card.when_to_use, actual)
                                self.assertEqual(len(selected), 1)
                                self.assertEqual(forced_selected, [])

    def test_forcing_changes_only_the_requested_role(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = freeze_bank(mixed_bank(), Path(folder) / 'banks')
            base = runtime()
            for role, sid in [('global', '1'), ('video', '3')]:
                for current in (base, runtime_with_bank(base, snapshot)):
                    before = deepcopy(current)
                    forced = runtime_with_forced_card(current, snapshot, role=role,
                        card_id=sid, directory=Path(folder) / 'strategies')
                    other = 'video' if role == 'global' else 'global'
                    self.assertEqual(forced['agents'][f'{other}_agent'], current['agents'][f'{other}_agent'])
                    self.assertEqual(forced['models'], current['models'])
                    self.assertEqual(forced['agents'][f'{role}_agent']['max_steps'], 5)
                    self.assertEqual(forced['agents'][f'{role}_agent']['skill']['mode'], 'static')
                    self.assertEqual(current, before)

    def test_invalid_forced_role_or_id_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot = freeze_bank(mixed_bank(), root / 'banks')
            for role, sid in [('other', '1'), ('global', '3'), ('video', '1'), ('global', 'missing')]:
                with self.subTest(role=role, card=sid), self.assertRaises(ValueError):
                    runtime_with_forced_card(runtime(), snapshot, role=role, card_id=sid,
                                             directory=root / 'strategies')
            self.assertFalse((root / 'strategies').exists())

    def test_evaluator_natural_and_forced_results_do_not_share_cache(self):
        fixture = evaluation_fixture.EvaluatorTest()
        with tempfile.TemporaryDirectory() as folder:
            root, evaluator, _ = fixture.setup_fixture(folder)
            snapshot = freeze_bank(mixed_bank(), root / 'banks')
            configured = []

            def native(command, **kwargs):
                configured.append(json.loads(Path(command[command.index('--config') + 1]).read_text()))
                fixture.native_run(command, **kwargs)

            variants = [None, {'role': 'global', 'card_id': '1'},
                        {'role': 'global', 'card_id': '2'}, {'role': 'video', 'card_id': '3'}]
            with patch('eval.skill_eval.evaluator.subprocess.run', side_effect=native) as run, \
                 patch('eval.skill_eval.evaluator._score_one', return_value={'status': 'ok', 'score': 0}):
                first = [evaluator(snapshot, 'train', forced_card=variant) for variant in variants]
                second = [evaluator(snapshot, 'train', forced_card=variant) for variant in variants]
                self.assertEqual(run.call_count, len(variants))
                self.assertEqual([x.identity for x in first], [x.identity for x in second])
                self.assertEqual(len({x.identity for x in first}), len(variants))
                for index, forced_card in enumerate(variants[1:], 1):
                    other = 'video' if forced_card['role'] == 'global' else 'global'
                    self.assertEqual(configured[index]['agents'][f'{other}_agent'],
                                     configured[0]['agents'][f'{other}_agent'])
                for invalid in ({'role': 'global', 'card_id': '3'}, {'role': 'global'},
                                {'role': 'global', 'card_id': 'missing'}, '1'):
                    with self.assertRaises(ValueError):
                        evaluator(snapshot, 'train', forced_card=invalid)
                self.assertEqual(run.call_count, len(variants))
            artifacts = [json.loads(path.read_text()) for path in (root / 'evaluations').glob('*/train/evaluation.json')]
            self.assertEqual(len(artifacts), len(variants))
            self.assertEqual(sum(a['selection_mode'] == 'natural' for a in artifacts), 1)
            self.assertEqual({a['identity'] for a in artifacts}, {x.identity for x in first})
            self.assertEqual({json.dumps(a['forced_card'], sort_keys=True) for a in artifacts},
                             {json.dumps(v, sort_keys=True) for v in variants})


if __name__ == '__main__':
    unittest.main()
