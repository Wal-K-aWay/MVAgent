"""Whole-bank evaluator metrics, raw-before-score and Judge failure behavior."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from eval.skill_eval.evaluator import LibraryEvaluator,CROSSVID_TASKS,assignment_groups,evaluation_variant,MANUAL_GLOBAL_MODE
from mvagent.skills.bank import SkillBank
from mvagent.utils.io import hash_json,write_json
from skill_evolution.infra.banks import freeze_bank


class EvaluatorTest(unittest.TestCase):
    def setup_fixture(self, folder):
        root=Path(folder); records={}; members=[]
        (root/'crossvid').mkdir()
        (root/'crossvid/qa.jsonl').write_text('synthetic metadata')
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
        write_json(directory/'run_manifest.json', {'samples':ids, 'status':'completed'})

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
                original_identity=evaluator.identity
                evaluator.identity='different metadata identity'
                with self.assertRaises(ValueError): evaluator(bank,'train')
                evaluator.identity=original_identity
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

    def test_native_resume_invokes_frozen_runner(self):
        with tempfile.TemporaryDirectory() as folder:
            root,evaluator,_=self.setup_fixture(folder)
            directory=root/'group'
            with patch('eval.skill_eval.evaluator.subprocess.run',side_effect=self.native_run) as run:
                evaluator._run_native(directory,evaluator.runtime,evaluator.ids['train'])
                evaluator._run_native(directory,evaluator.runtime,evaluator.ids['train'])
            command=run.call_args.args[0]
            self.assertEqual(command[1],str(directory/'rollouts/eval/agent_eval/run.py'))
            self.assertIn('--resume',command)

    @staticmethod
    def routing_bank(root):
        cards=[{'meta':{'id':sid,'role':role,'stages':['initial','evidence']},
                'when_to_use':'Compare the requested evidence.', 'strategy':f'Inspect evidence for method {sid}.'}
               for sid,role in [('1','global'),('2','global'),('3','video')]]
        return freeze_bank(SkillBank.from_dict({'schema_version':3,'skills':cards}),root/'banks')

    def test_manual_assignment_groups_preserve_video_and_score_whole_partition(self):
        with tempfile.TemporaryDirectory() as folder:
            root,evaluator,_=self.setup_fixture(folder)
            bank=self.routing_bank(root); ids=evaluator.ids['train']
            assignments={sid:(None,'1','2')[i%3] for i,sid in enumerate(ids)}
            calls=[]
            def run(command,**kwargs):
                path=Path(command[command.index('--config')+1]); calls.append((path,json.loads(path.read_text())))
                self.native_run(command,**kwargs)
            with patch('eval.skill_eval.evaluator.subprocess.run',side_effect=run), \
                 patch('eval.skill_eval.evaluator._score_one',side_effect=lambda _,cache,task,attempts:{'status':'ok','score':2*task['point_count']}):
                result=evaluator(bank,'train',global_assignments=assignments)
                self.assertEqual(result.samples,20)
                self.assertAlmostEqual(result.score,.55)
                self.assertEqual(len(calls),3)
                for path,runtime in calls:
                    self.assertEqual(runtime['agents']['video_agent']['skill'], {
                        'enabled':True,'mode':'dynamic','selection_scope':'task','path':str(bank.path),'sha256':bank.sha256})
                    global_skill=runtime['agents']['global_agent']['skill']
                    self.assertEqual(global_skill['enabled'],path.parent.name!='none')
                    if global_skill['enabled']: self.assertEqual(global_skill['mode'],'static')
                variant=evaluation_variant(bank.sha256,global_assignments=assignments)
                directory=root/'evaluations'/variant/'train'
                artifact=json.loads((directory/'evaluation.json').read_text())
                self.assertEqual(artifact['selection_mode'],MANUAL_GLOBAL_MODE)
                self.assertEqual(artifact['global_assignments_sha256'],hash_json(assignments))
                self.assertEqual(len(artifact['group_artifact_sha256']),12)
                self.assertEqual(len(json.loads((directory/'global_assignment_groups.json').read_text())),3)
                for sid in ids:
                    link=directory/'rollouts/records/crossvid'/sid/'result.json'
                    self.assertTrue(link.is_symlink()); self.assertFalse(str(link.readlink()).startswith('/'))
                    self.assertEqual(json.loads(link.read_text())['sample_id'],sid)
                self.assertEqual(evaluator(bank,'train',global_assignments=assignments).score,result.score)
                self.assertEqual(len(calls),3)
                calls[0][0].write_text('{}')
                with self.assertRaisesRegex(ValueError,'group artifact changed'):
                    evaluator(bank,'train',global_assignments=assignments)

    def test_manual_assignment_coverage_role_and_cache_isolation(self):
        with tempfile.TemporaryDirectory() as folder:
            root,evaluator,_=self.setup_fixture(folder)
            bank=self.routing_bank(root); ids=evaluator.ids['train']
            assignments={sid:'1' for sid in ids}
            self.assertEqual(assignment_groups(bank.load(),ids,assignments),{'1':list(ids)})
            for invalid in ({}, {**assignments,'unknown':None}, {**assignments,ids[0]:'3'},
                            {**assignments,ids[0]:True}):
                with self.assertRaises(ValueError): evaluator(bank,'train',global_assignments=invalid)
            manual=evaluation_variant(bank.sha256,global_assignments=assignments)
            natural=evaluation_variant(bank.sha256)
            forced=evaluation_variant(bank.sha256,forced_card={'role':'global','card_id':'1'})
            abstaining=evaluation_variant(bank.sha256,global_assignments={**assignments,ids[0]:None})
            self.assertEqual(len({manual,natural,forced,abstaining}),4)
            self.assertEqual(manual,evaluation_variant(bank.sha256,global_assignments=dict(reversed(list(assignments.items())))))
            with self.assertRaises(ValueError):
                evaluator(bank,'train',forced_card={'role':'global','card_id':'1'},global_assignments=assignments)


if __name__=='__main__': unittest.main()
