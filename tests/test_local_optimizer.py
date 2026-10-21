"""Local optimizer transport contract; no model service, GPU or network calls."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import yaml
from eval.skill_eval.run import _optimizer_client
from models.execution import execution_scope
from models.pool import Replica, get_pool, install_pools
from models.vlm.api.providers.openai_compatible import OpenAICompatibleProvider
from models.vlm.local.sync_server import validate_request

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'qwen3_5_9b_local'
ENDPOINT = 'http://127.0.0.1:8100/v1'


class LocalOptimizerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(install_pools, {})
        self.root = Path(self.temp.name)
        self.settings = yaml.safe_load((ROOT / 'configs/skill_evolution/local_optimizer.yaml').read_text())
        self.path = self.root / 'optimizer.json'
        self.path.write_text(json.dumps(self.settings))
        self.execution = self.root / 'execution.json'
        self.execution.write_text(json.dumps({'model_pools': {MODEL: {'replicas': [
            {'endpoint': ENDPOINT, 'gpus': [0], 'max_inflight': 1}]}}}))
        self.runtime = yaml.safe_load((ROOT / 'configs/inference/modal_qwen35_9b_no_skill.yaml').read_text())
        self.pool = SimpleNamespace(name=MODEL, replicas=[Replica(ENDPOINT, (0,), 1)],
            cards={ENDPOINT: {'id': MODEL}}, acquire=Mock(side_effect=lambda _: nullcontext(None)))

    def client(self):
        return _optimizer_client(self.path, runtime=self.runtime,
                                 execution_path=self.execution, output=self.root)

    def prepare(self, runtime, execution):
        self.assertIs(runtime, self.runtime)
        self.assertIn(MODEL, execution.model_pools)
        install_pools({MODEL: self.pool})
        return {MODEL: self.pool}, []

    def test_registered_before_client_uses_sync_grammar_seed_and_audit(self):
        events = []
        with patch.dict(os.environ, LOCAL_OPTIMIZER_API_KEY='test-placeholder'), \
             patch('mvagent.batch.prepare_model_pools', side_effect=self.prepare) as prepare, \
             patch('models.vlm.api.providers.openai_compatible._compact_vllm_grammar', return_value='test-grammar'), \
             patch.object(OpenAICompatibleProvider, '_chat', return_value='{}') as transport:
            with self.client() as client, execution_scope(emit=events.append):
                self.assertIs(client.provider.pool, self.pool)
                client.chat([{'role': 'user', 'content': 'Return a JSON object.'}],
                            json_schema={'type': 'object'}, schema_name='optimizer_test')
            prepare.assert_called_once()
            transport.assert_called_once()
        payload = next(event['payload'] for event in events if event['kind'] == 'model_request')
        self.assertEqual(payload['structured_outputs'], {'grammar': 'test-grammar'})
        self.assertNotIn('response_format', payload)
        self.assertEqual((payload['seed'], payload['return_token_ids']), (0, True))
        self.assertEqual(validate_request(payload, MODEL)['max_tokens'], 4096)
        self.assertIsNone(get_pool(MODEL))
        receipt = json.loads((self.root / 'optimizer_pools.json').read_text())
        self.assertEqual(receipt['pools'][MODEL]['cards'], self.pool.cards)
        self.assertNotIn('test-placeholder', json.dumps(receipt))

    def test_reject_model_or_endpoint_mismatch_before_preparing_services(self):
        for change, message in [('model', 'local_vllm'), ('endpoint', 'configured model pool')]:
            with self.subTest(change=change):
                settings = dict(self.settings)
                settings['model_name' if change == 'model' else 'api_base'] = (
                    'unknown_model' if change == 'model' else 'http://127.0.0.1:9999/v1')
                self.path.write_text(json.dumps(settings))
                with patch('mvagent.batch.prepare_model_pools') as prepare, \
                     self.assertRaisesRegex(ValueError, message), self.client():
                    pass
                prepare.assert_not_called()

    def test_reject_unverified_or_unavailable_optimizer_and_clear_registration(self):
        for change, message in [('cards', 'fixed-profile'), ('endpoint', 'service verification')]:
            with self.subTest(change=change):
                self.pool.cards = {} if change == 'cards' else {ENDPOINT: {'id': MODEL}}
                self.pool.replicas = [Replica(ENDPOINT if change == 'cards' else
                                             'http://127.0.0.1:8101/v1', (0,), 1)]
                with patch('mvagent.batch.prepare_model_pools', side_effect=self.prepare), \
                     self.assertRaisesRegex(ValueError, message), self.client():
                    pass
                self.assertIsNone(get_pool(MODEL))

    def test_reject_additional_optimizer_only_pool(self):
        name = 'optimizer_only'
        self.runtime['models'][name] = dict(self.runtime['models'][MODEL])
        self.path.write_text(json.dumps({**self.settings, 'model_name': name}))
        self.execution.write_text(json.dumps({'model_pools': {name: {'replicas': [
            {'endpoint': ENDPOINT, 'gpus': [0], 'max_inflight': 1}]}}}))
        with patch('mvagent.batch.prepare_model_pools') as prepare, \
             self.assertRaisesRegex(ValueError, 'runtime roles'), self.client():
            pass
        prepare.assert_not_called()

    def test_commercial_clients_do_not_prepare_or_clear_pools(self):
        for settings in [yaml.safe_load((ROOT / 'configs/skill_evolution/llm_generation.yaml').read_text()),
                         {**self.settings, 'api_base': 'https://api.example.com/v1'},
                         {**self.settings, 'api_base': 'http://localhost.example.com:8100/v1'}]:
            with self.subTest(provider=settings['provider'], endpoint=settings.get('api_base')):
                self.path.write_text(json.dumps(settings))
                install_pools({'other': self.pool})
                with patch('skill_evolution.configs.models.load_client', return_value='api-client') as load, \
                     patch('mvagent.batch.prepare_model_pools') as prepare:
                    with self.client() as client:
                        self.assertEqual(client, 'api-client')
                    load.assert_called_once_with(self.path)
                    prepare.assert_not_called()
                self.assertIs(get_pool('other'), self.pool)

    def test_clear_registration_when_proposal_body_fails(self):
        with patch.dict(os.environ, LOCAL_OPTIMIZER_API_KEY='test-placeholder'), \
             patch('mvagent.batch.prepare_model_pools', side_effect=self.prepare), \
             self.assertRaisesRegex(RuntimeError, 'proposal failed'):
            with self.client():
                raise RuntimeError('proposal failed')
        self.assertIsNone(get_pool(MODEL))


if __name__ == '__main__':
    unittest.main()
