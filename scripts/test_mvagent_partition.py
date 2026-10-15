"""CPU checks for process adoption and complete-only merging of model groups."""
from contextlib import contextmanager
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_mvagent_partition import process_alive, validate_adoption
from watch_full_mvagent import execution_ready, merge_completed


class AllocationTest(unittest.IsolatedAsyncioTestCase):
    async def test_pending_allocation_does_not_start_a_duplicate_job(self):
        class Task:
            async def aio(self, **kwargs):
                await asyncio.sleep(.05)
                return 'task-id'
        class Sandbox:
            _get_task_id = Task()
        self.assertFalse(await execution_ready(Sandbox(), timeout=.001))
        self.assertTrue(await execution_ready(Sandbox(), timeout=.2))


class Volume:
    def __init__(self, files):
        self.files, self.writes = files, {}

    def read_file(self, name):
        yield json.dumps(self.files[name]).encode()

    @contextmanager
    def batch_upload(self, force=False):
        assert force
        yield self

    def put_file(self, stream, name):
        self.writes[name] = stream.read()


class PartitionTest(unittest.TestCase):
    def test_adopt_only_the_assigned_live_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root/'eval/agent_eval/run.py'
            script.parent.mkdir(parents=True)
            script.write_text('import time\ntime.sleep(30)\n')
            process = subprocess.Popen([sys.executable, str(script), '--output', str(root/'27B')], start_new_session=True)
            try:
                validate_adoption(process.pid, root, '27B')
                with self.assertRaises(AssertionError):
                    validate_adoption(process.pid, root, '35B-A3B')
            finally:
                process.terminate(); process.wait()
            self.assertFalse(process_alive(process.pid))

    def test_merge_requires_complete_unique_model_owners(self):
        plan = dict(groups=[dict(tag='primary', models=['9B', '27B']),
                            dict(tag='secondary', models=['35B-A3B'])], output='devbox/combined')
        files = {'plan.json': plan}
        for group in plan['groups']:
            files[f"devbox/{group['tag']}/progress.json"] = dict(phase='completed', model_scope=group['models'],
                models={m: dict(scoring_done=True) for m in group['models']},
                comparisons={m: dict(cvbench=dict(complete=True, paired=997, e2e_score=.5, agent_score=.6, delta=.1)) for m in group['models']})
        volume = Volume(files)
        files['devbox/secondary/progress.json']['phase'] = 'scoring'
        self.assertFalse(merge_completed(volume, 'plan.json'))
        self.assertFalse(volume.writes)
        files['devbox/secondary/progress.json']['phase'] = 'completed'
        self.assertTrue(merge_completed(volume, 'plan.json'))
        merged = json.loads(volume.writes['devbox/combined/progress.json'])
        self.assertEqual(set(merged['models']), {'9B', '27B', '35B-A3B'})
        self.assertEqual(merged['sources']['35B-A3B'], 'devbox/secondary/35B-A3B')
        plan['groups'][1]['models'].append('27B')
        with self.assertRaises(AssertionError):
            merge_completed(volume, 'plan.json')


if __name__ == '__main__':
    unittest.main()
