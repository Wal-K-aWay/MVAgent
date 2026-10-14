"""Dependency-free contract check; does not load a model or measure GPU cache hits."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sync_server', ROOT / 'src/models/vlm/local/sync_server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class PrefixUsageTest(unittest.TestCase):
    def test_large_video_body_limit(self):
        handler = object.__new__(server.Handler)
        handler.path = '/v1/chat/completions'
        handler.respond = Mock()
        handler.rfile = Mock()
        handler.rfile.read.side_effect = RuntimeError('body read reached')
        # The observed failing request must pass admission without allocating its payload in this test.
        for length in (551523424, 1545373160, 2*1024**3):
            handler.headers = {'Content-Length': str(length)}
            with self.assertRaisesRegex(RuntimeError, 'body read reached'):
                handler.do_POST()
        handler.respond.assert_not_called()
        handler.rfile.reset_mock()
        for length in (0, -1, 2*1024**3 + 1):
            handler.headers = {'Content-Length': str(length)}
            handler.do_POST()
            self.assertEqual(handler.respond.call_args.args[0], 400)
        handler.rfile.read.assert_not_called()

    def test_response_audit_and_persisted_usage(self):
        self.assertEqual(server.PROFILE, 'qwen35-bf16-flashinfer-sync')
        self.assertFalse(server.ENGINE_CONFIG['enable_prefix_caching'])
        engine = object.__new__(server.Engine)
        engine.card = {'id': 'test'}
        engine.worker = {'pid': 1, 'gpu_uuid': 'test'}
        body = dict(model='test', messages=[{'role': 'user', 'content': 'hello'}], max_tokens=8)
        wire = json.dumps(body).encode()
        output = SimpleNamespace(request_id='test', prompt_token_ids=[1, 2, 3],
            outputs=[SimpleNamespace(text='OK', token_ids=[4], finish_reason='stop')])
        def chat(*args, **kwargs):
            engine.forward_calls += 1
            return [output]
        engine.llm = SimpleNamespace(chat=chat)
        with tempfile.TemporaryDirectory() as temporary, patch.dict('sys.modules',
                {'vllm': SimpleNamespace(SamplingParams=lambda **kwargs: kwargs)}):
            engine.log_dir = Path(temporary)
            for count in [0, 2, 3]:
                output.num_cached_tokens = count
                result = engine.complete(body, wire)
                self.assertEqual(result['usage']['prompt_tokens_details']['cached_tokens'], count)
                self.assertEqual(server.token_audit(result, wire)['cache_hit_rate'], count / 3)
            rows = [json.loads(line) for line in (engine.log_dir / 'requests.jsonl').read_text().splitlines()]
            self.assertEqual([r['usage']['prompt_tokens_details']['cached_tokens'] for r in rows], [0, 2, 3])
            self.assertEqual([r['cache_hit_rate'] for r in rows], [0, 2/3, 1])
            result['audit']['cache_hit_rate'] = 0
            with self.assertRaisesRegex(ValueError, 'Cache hit rate'):
                server.token_audit(result, wire)

    def test_missing_and_invalid_counts_fail(self):
        for details in [None, {}, [], {'cached_tokens': None}, {'cached_tokens': -1},
                        {'cached_tokens': 4}, {'cached_tokens': True}, {'cached_tokens': '2'}]:
            with self.subTest(details=details), self.assertRaises(ValueError):
                server.cache_hit_rate(dict(prompt_tokens=3, prompt_tokens_details=details))
        with self.assertRaises(ValueError):
            server.cache_hit_rate(dict(prompt_tokens=0, prompt_tokens_details={'cached_tokens': 0}))


if __name__ == '__main__':
    unittest.main()
