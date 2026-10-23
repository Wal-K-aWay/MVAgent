"""Frozen coordinator resume and secret-reference boundaries, without model calls."""
from argparse import Namespace
from pathlib import Path
import json,tempfile,unittest
from eval.skill_eval.run import _prepare


def args(output, **updates):
    value=dict(output=output,resume=False,config=None,optimizer_config=None,runtime_config=None,
               execution_config=None,split_manifest=None,dataset_root=None,judge_endpoints=None)
    value.update(updates)
    return Namespace(**value)


class SnapshotTest(unittest.TestCase):
    def test_freeze_resume_and_reject_source_or_config_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'execution.json').write_text('{}'); (root/'split.json').write_text('{}')
            output,manifest=_prepare(args(root/'run',execution_config=root/'execution.json',
                                          split_manifest=root/'split.json',judge_endpoints='http://unused/v1'))
            self.assertEqual(_prepare(args(output,resume=True))[1],manifest)
            self.assertTrue((output/'frozen/eval/skill_eval/run.py').exists())
            with self.assertRaises(ValueError): _prepare(args(output,resume=True,config=root/'new.json'))
            config=output/'configs/search.json'; original=config.read_bytes(); config.write_text('{}')
            with self.assertRaisesRegex(ValueError,'configuration changed'): _prepare(args(output,resume=True))
            config.write_bytes(original)
            source=output/'frozen/src/skill_evolution/configs/evolution.py'
            source.write_text(source.read_text()+'\n# changed\n')
            with self.assertRaisesRegex(ValueError,'Frozen source changed'): _prepare(args(output,resume=True))

    def test_literal_optimizer_secret_is_rejected_before_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); secret='sk-not-a-real-secret'
            (root/'optimizer.json').write_text(json.dumps({'model_type':'api_llm','provider':'deepseek',
                'model_name':'deepseek-flash','api_key':secret,'max_retries':1}))
            (root/'execution.json').write_text('{}'); (root/'split.json').write_text('{}')
            with self.assertRaises(ValueError): _prepare(args(root/'run',optimizer_config=root/'optimizer.json',
                execution_config=root/'execution.json',split_manifest=root/'split.json',judge_endpoints='http://unused/v1'))
            for file in (root/'run').rglob('*'):
                if file.is_file(): self.assertNotIn(secret,file.read_text())


if __name__=='__main__': unittest.main()
