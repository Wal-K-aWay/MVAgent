"""MVAgent fixed-profile configuration and per-question replica leasing."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import time
import unittest

from models.vlm.local.sync_server import PROFILE

ROOT = Path(__file__).resolve().parents[1]


class ModelPoolTest(unittest.TestCase):
    def test_actor_profile_and_question_lease(self):
        from contextvars import copy_context
        from models.execution import execution_scope
        from models.pool import ModelPool, Replica, PoolUnavailable
        from models.vlm.local.service import VLLMServiceManager
        from mvagent.configs import MVAgentConfig
        import yaml
        paths = [*sorted((ROOT / 'configs/inference').glob('modal_qwen35_*_no_skill.yaml')),
                 ROOT / 'eval/agent_eval/config.yaml', ROOT / 'eval/agent_eval/config_qwen3_5_9b.yaml']
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


if __name__ == '__main__':
    unittest.main()
