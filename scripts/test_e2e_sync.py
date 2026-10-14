"""CPU contract checks for the E2E endpoint, token records and unchanged CLI."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'eval/e2e_eval'
sys.path.insert(0, str(ROOT))
from harness.backends import VLLMBackend, token_audit
from harness.common import sha256_file
from models.vlm.local.sync_server import ENGINE_CONFIG, ENVIRONMENT, PROFILE, VERSIONS, SerialServer, digest, validate_request
from serve import parse_gpus
import httpx


class FakeEngine:
    def __init__(self, gpu):
        self.worker = dict(pid=99, gpu_uuid=gpu, cuda_visible_devices=gpu, gpu_name='test', model_object_id=123)
        self.card = dict(id='test', root='test', max_model_len=131072, weights_manifest={'test': 'fixed'},
            worker=self.worker, execution=dict(profile=PROFILE, config=ENGINE_CONFIG, environment=ENVIRONMENT,
                versions=VERSIONS, source_sha256=sha256_file(ROOT.parents[1] / 'src/models/vlm/local/sync_server.py')))
        self.active = self.peak = self.calls = 0
        self.corrupt = False

    def complete(self, body, wire):
        generation = validate_request(body, 'test')
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls += 1
        time.sleep(.015)
        self.active -= 1
        result = dict(model='test', choices=[dict(message=dict(content='C'), token_ids=[34, 248046], finish_reason='stop')],
            prompt_token_ids=[7, 8, 9], usage=dict(prompt_tokens=3, completion_tokens=2, total_tokens=5,
                prompt_tokens_details=dict(cached_tokens=0)),
            audit=dict(request_sha256=hashlib.sha256(wire).hexdigest(), prompt_token_ids_sha256=digest([7, 8, 9]),
                input_sha256=digest(dict(messages=body['messages'], generation=generation,
                    chat_template_kwargs={'enable_thinking': False})),
                worker={**self.worker, 'forward_calls': 1}, inference_seconds=.015, cache_hit_rate=0.0))
        if self.corrupt:
            result['choices'][0]['token_ids'] = [34]
        return result


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.engines = [FakeEngine('gpu-0'), FakeEngine('gpu-1')]
        self.servers = [SerialServer(('127.0.0.1', 0), engine) for engine in self.engines]
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in self.servers]
        for thread in self.threads:
            thread.start()
        self.endpoints = [f'http://127.0.0.1:{s.server_port}/v1' for s in self.servers]

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join()

    def backend(self, endpoints=None):
        return VLLMBackend(endpoints or self.endpoints, model=None, timeout=3, retries=1, enable_thinking=False)

    def test_complete_contract_and_serial_admission(self):
        backend = self.backend()
        def call(i):
            return backend.complete([{'role': 'user', 'content': f'q{i}'}], max_tokens=128, temperature=0.0, top_p=.95)
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = list(pool.map(call, range(16)))
        self.assertTrue(all(text == 'C' and record['token_ids'] == [34, 248046] for text, record in rows))
        self.assertEqual([e.peak for e in self.engines], [1, 1])
        self.assertEqual(sum(e.calls for e in self.engines), 16)
        self.assertEqual({r['worker']['gpu_uuid'] for _, r in rows}, {'gpu-0', 'gpu-1'})
        self.assertEqual(rows[0][1]['generation']['max_tokens'], 128)

    def test_missing_or_incomplete_token_audit_and_slot_recovery(self):
        backend = self.backend([self.endpoints[0]])
        self.engines[0].corrupt = True
        with self.assertRaisesRegex(ValueError, 'Token IDs'):
            backend.complete([{'role': 'user', 'content': 'q'}], max_tokens=128, temperature=0, top_p=1)
        self.assertEqual(backend._slots.qsize(), 1)
        self.engines[0].corrupt = False
        text, _ = backend.complete([{'role': 'user', 'content': 'q'}], max_tokens=128, temperature=0, top_p=1)
        self.assertEqual(text, 'C')
        body = dict(model='test', messages=[{'role': 'user', 'content': 'q'}], max_tokens=128)
        wire = json.dumps(body).encode()
        good = self.engines[0].complete(body, wire)
        for field in ['prompt_token_ids', 'audit']:
            bad = copy.deepcopy(good)
            bad.pop(field)
            with self.assertRaises((KeyError, ValueError)):
                token_audit(bad, wire)
        with self.assertRaisesRegex(ValueError, 'hashes'):
            token_audit(good, wire+b' ')
        good['choices'][0]['token_ids'] = []
        good['usage'].update(completion_tokens=0, total_tokens=3)
        self.assertEqual(token_audit(good, wire)['token_ids'], [])

    def test_profile_mismatch_and_invalid_request(self):
        self.engines[0].card = copy.deepcopy(self.engines[0].card)
        self.engines[0].card['execution']['config']['max_num_seqs'] = 2
        with self.assertRaisesRegex(RuntimeError, 'execution profile'):
            self.backend()
        body = dict(model='test', messages=[{'role': 'user', 'content': 'q'}], max_tokens=128)
        for wrong in [dict(seed=1), dict(temperature=1), dict(stream=True), dict(max_tokens=0),
                      dict(max_tokens=True), dict(chat_template_kwargs={'enable_thinking': True}), dict(n=2)]:
            response = httpx.post(self.endpoints[0]+'/chat/completions', json={**body, **wrong}, trust_env=False)
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.engines[0].calls, 0)

    def test_per_request_prefix_cache_accounting(self):
        self.assertEqual(PROFILE, 'qwen35-bf16-flashinfer-sync')
        self.assertFalse(ENGINE_CONFIG['enable_prefix_caching'])
        body = dict(model='test', messages=[{'role': 'user', 'content': 'q'}], max_tokens=128)
        wire = json.dumps(body).encode()
        good = self.engines[0].complete(body, wire)
        for cached in [0, 2, 3]:
            good['usage']['prompt_tokens_details']['cached_tokens'] = cached
            good['audit']['cache_hit_rate'] = cached / 3
            self.assertEqual(token_audit(good, wire)['cache_hit_rate'], cached / 3)
        for cached in [None, -1, 4, True, '2']:
            good['usage']['prompt_tokens_details']['cached_tokens'] = cached
            with self.assertRaisesRegex(ValueError, 'cached_tokens'):
                token_audit(good, wire)
        good['usage'].pop('prompt_tokens_details')
        with self.assertRaisesRegex(ValueError, 'cached_tokens'):
            token_audit(good, wire)

    def test_agent_fields_and_prepared_input_binding(self):
        from harness.common import bind_input, read_json
        from models.vlm.local.sync_server import input_digest
        body = dict(model='test', messages=[{'role': 'user', 'content': 'q'}], max_tokens=2048,
                    structured_outputs={'grammar': 'root ::= "OK"'}, media_io_kwargs={'video': {'fps': 1}})
        validate_request(body, 'test')
        changed = copy.deepcopy(body)
        changed['media_io_kwargs']['video']['fps'] = 2
        self.assertNotEqual(input_digest(body), input_digest(changed))
        with self.assertRaises(ValueError):
            validate_request({**body, 'structured_outputs': []}, 'test')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input_audit.json'
            bind_input(path, 'q', 'a')
            bind_input(path, 'q', 'a')
            with self.assertRaisesRegex(ValueError, 'Prepared input changed'):
                bind_input(path, 'q', 'b')
            self.assertEqual(read_json(path)['input_sha256'], {'q': 'a'})

    def test_actor_profile_and_question_lease(self):
        from contextvars import copy_context
        from models.execution import execution_scope
        from models.pool import ModelPool, Replica, PoolUnavailable
        from models.vlm.local.service import VLLMServiceManager
        from mvagent.configs import MVAgentConfig
        import yaml
        paths = [*sorted((ROOT.parents[1] / 'configs/inference').glob('modal_qwen35_*_no_skill.yaml')),
                 ROOT.parent / 'agent_eval/config.yaml', ROOT.parent / 'agent_eval/config_qwen3_5_9b.yaml']
        for path in paths:
            config = MVAgentConfig.from_dict(yaml.safe_load(path.read_text()))
            for _, _, ref in config.model_roles():
                cfg = config.models[ref.model_type].to_runtime_config(ref.model_type, ref)
                self.assertEqual(cfg.execution_profile, PROFILE)
                self.assertEqual((cfg.dtype, cfg.gpu_memory_utilization, cfg.max_model_len), ('bfloat16', .94, 131072))
        ref = next(ref for _, _, ref in config.model_roles())
        cfg = config.models[ref.model_type].to_runtime_config(ref.model_type, ref)
        cfg.gpus, cfg.endpoint = ['GPU-test'], 'http://127.0.0.1:8100/v1'
        command = VLLMServiceManager(cfg, cache_dir='/tmp/test').build_start_command()
        self.assertTrue(command[1].endswith('sync_server.py'))
        cfg.max_model_len = 262144
        with self.assertRaisesRegex(RuntimeError, 'conflict'):
            VLLMServiceManager(cfg, cache_dir='/tmp/test').build_start_command()
        with tempfile.TemporaryDirectory() as tmp:
            pool = ModelPool('test', [Replica('http://127.0.0.1:8100/v1', ('GPU-a',), 1),
                                      Replica('http://127.0.0.1:8101/v1', ('GPU-b',), 1)], 'fixed', root=tmp)
            pool.register()
            with execution_scope(emit=lambda e: None) as scope, pool.acquire(1) as held:
                scope['model_leases'] = {'test': (held, threading.Lock())}
                def call():
                    with pool.acquire(2) as admitted:
                        admitted.sent()
                        time.sleep(.01)
                        admitted.complete()
                        return admitted.endpoint
                with ThreadPoolExecutor(4) as workers:
                    replies = [workers.submit(copy_context().run, call) for _ in range(4)]
                    self.assertEqual([f.result() for f in replies], [held.endpoint] * 4)
                held.complete(unhealthy=True)
                with self.assertRaises(PoolUnavailable):
                    with pool.acquire(1):
                        pass

    def test_gpu_selection(self):
        self.assertEqual(parse_gpus('0-2,4'), [0, 1, 2, 4])
        for value in ['1,1', '0,3-1', '-1']:
            with self.assertRaises(ValueError):
                parse_gpus(value)

    def test_verifier_detects_input_tokens_and_text_changes(self):
        from verify_e2e_sync import compare_rows
        row = dict(status='ok', output='C', request=dict(input_sha256='input',
            prompt_token_ids_sha256='prompt', token_ids=[34, 248046], finish_reason='stop'))
        before = {'cvbench:664': row}
        self.assertEqual(compare_rows(before, copy.deepcopy(before)), [])
        for key, value in [('input_sha256', 'different'), ('token_ids', [35, 248046]), ('finish_reason', 'length')]:
            after = copy.deepcopy(before)
            after['cvbench:664']['request'][key] = value
            self.assertEqual(len(compare_rows(before, after)), 1)
        with self.assertRaises(ValueError):
            compare_rows(before, {})

    def test_existing_cli_and_frozen_source_are_preserved(self):
        spec = importlib.util.spec_from_file_location('e2e_run_test', ROOT / 'run.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch.object(sys, 'argv', ['run.py', 'infer', '--output', '/runs/example', '--endpoints', '8100-8107']):
            args = runner.parse_args()
        self.assertEqual(args.frames, 512)
        self.assertEqual(args.max_side, 448)
        self.assertEqual(len(runner.parse_endpoints(args.endpoints)), 8)
        self.assertIn(ROOT / 'serve.py', runner.source_files())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            runner.freeze_source(output)
            (output / 'manifest.json').write_text('{}')
            (output / 'source/serve.py').unlink()
            with self.assertRaises(SystemExit):
                runner.freeze_source(output)
            self.assertFalse((output / 'source/serve.py').exists())


if __name__ == '__main__':
    unittest.main()
