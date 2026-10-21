"""Whole-bank evaluator metrics, raw-before-score and Judge failure behavior."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from eval.skill_eval.evaluator import LibraryEvaluator,CROSSVID_TASKS
from mvagent.skills.bank import SkillBank
from mvagent.utils.io import write_json
from skill_evolution.infra.banks import freeze_bank


class EvaluatorTest(unittest.TestCase):
    def setup_fixture(self, folder):
        root=Path(folder); records={}; members=[]
        for task in sorted(CROSSVID_TASKS):
            for i,split in enumerate(('train','train','cal','eval')):
                sid=f'crossvid:{task}:{i}'
                weight=3 if task=='CCQA' and i==0 else 1
                records[sid]=SimpleNamespace(dataset='crossvid',native_task=task,task_population=100,
                    sample_weight=weight,judge_question='Question?',reference_answer='Reference',
                    sample=SimpleNamespace(ground_truth=['point']*weight))
                members.append({'sample_id':sid,'split':split,'group_id':sid})
        write_json(root/'split.json',{'version':2,'dataset':'synthetic','seed':0,'samples':members})
        write_json(root/'execution.json',{})
        runtime={'agents':{'global_agent':{},'video_agent':{}}}
        with patch('eval.skill_eval.evaluator.load_multibench_records',return_value=records), \
             patch('eval.skill_eval.evaluator.LocalJudge',return_value=SimpleNamespace(identity={'model':'test'})):
            evaluator=LibraryEvaluator(output=root,runtime=runtime,execution=root/'execution.json',
                split_path=root/'split.json',dataset_root=root,endpoints=['unused'],identity='test')
        return root,evaluator,freeze_bank(SkillBank(()),root/'banks')

    @staticmethod
    def native_run(command,**kwargs):
        directory=Path(command[command.index('--output')+1])
        ids=json.loads(Path(command[command.index('--sample-ids-file')+1]).read_text())
        for sid in ids:
            ccqa=sid.startswith('crossvid:CCQA:')
            write_json(directory/'records/crossvid'/sid/'result.json',
                       {'sample_id':sid,'status':'ok','prediction':'prediction','result':{},'events':[],
                        'scoring_status':'deferred' if ccqa else 'ok',
                        'score':None if ccqa else float(sid.endswith(':0'))})

    def test_official_macro_point_weights_cache_and_raw_preservation(self):
        with tempfile.TemporaryDirectory() as folder:
            root,evaluator,bank=self.setup_fixture(folder)
            def judge(_,cache,task,attempts):
                return {'status':'ok','score':task['point_count'] if task['id'].endswith(':0') else 2*task['point_count']}
            with patch('eval.skill_eval.evaluator.subprocess.run',side_effect=self.native_run) as run, \
                 patch('eval.skill_eval.evaluator._score_one',side_effect=judge) as score:
                result=evaluator(bank,'train')
                self.assertAlmostEqual(result.score,(9*0.5+5/8)/10)
                self.assertEqual(result.samples,20)
                native=root/'evaluations'/bank.sha256/'train/rollouts/records/crossvid/crossvid:CCQA:0/result.json'
                self.assertIsNone(json.loads(native.read_text())['score'])
                self.assertEqual(evaluator(bank,'train').score,result.score)
                self.assertEqual(run.call_count,1); self.assertEqual(score.call_count,2)
                native.write_text('{}')
                with self.assertRaises(ValueError): evaluator(bank,'train')

    def test_judge_error_leaves_raw_and_does_not_write_zero_score(self):
        with tempfile.TemporaryDirectory() as folder:
            root,evaluator,bank=self.setup_fixture(folder)
            with patch('eval.skill_eval.evaluator.subprocess.run',side_effect=self.native_run), \
                 patch('eval.skill_eval.evaluator._score_one',return_value={'status':'error','error':'unavailable'}):
                with self.assertRaisesRegex(RuntimeError,'Judge failed'): evaluator(bank,'cal')
            directory=root/'evaluations'/bank.sha256/'cal'
            self.assertTrue((directory/'rollouts/records/crossvid/crossvid:CCQA:2/result.json').exists())
            self.assertFalse((directory/'evaluation.json').exists())


if __name__=='__main__': unittest.main()
