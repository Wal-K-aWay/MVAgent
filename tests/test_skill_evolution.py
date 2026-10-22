"""Role isolation, controlled edits, held-out acceptance and saved-call resume."""
from copy import deepcopy
from pathlib import Path
import json,tempfile,unittest

from models.execution import emit_event
from mvagent.agents.video_agent.memory import VideoAgentMemory
from mvagent.skills.bank import SkillBank
from mvagent.utils.io import hash_json
from skill_evolution.configs.evolution import EvolutionConfig
from skill_evolution.infra.banks import apply_edit,freeze_bank,runtime_with_bank
from skill_evolution.infra.evaluation import Evaluation
from skill_evolution.infra.trajectory import global_view,video_views,examples
from skill_evolution.infra.llm import call_json
from skill_evolution.algorithms.rolewise.optimizer import evolve
from skill_evolution.algorithms.rolewise.prompts import SCHEMA


def edit(role='global'):
    return {'operation':'add','target_id':'','when_to_use':f'A {role} comparison request.',
            'strategy':'Compare visible evidence and report supported differences.',
            'hypothesis':'The report may omit a discriminating feature; inspect and compare it.'}


def row():
    observation={'action':'observe','parameters':{'what':'Which tool is used?', 'where':[[0,2]], 'fps':1},
                 'result':{'status':'ok','observations':[{'time_range':[0,2],'fps':1,'text':'PRIVATE_VIDEO_OBSERVATION'}]}}
    return {'sample_id':'PRIVATE_SAMPLE_ID','native_task':'PRIVATE_TASK_CODE','ground_truth':['PRIVATE_GT'],
            'score':0.0,'events':[], 'result':{
                'input':{'question':'GLOBAL_ONLY_QUESTION','videos':{'video_1':'PRIVATE_MEDIA_PATH'}},
                'video_metadata':{'video_1':{'duration_sec':8,'file':'PRIVATE_MEDIA_PATH'},'video_2':{'duration_sec':9}},
                'action_history':[], 'answer':{'answer':'A','reason':'Supported evidence','hidden':'PRIVATE_GT'},
                'trajectory':[{'agent':'VideoAgent','video_id':'video_1','input':{'instruction':'Which tool?','global_round':1},
                    'output':{'request_id':'req_1','status':'ok','report':'The tool is a spoon.','steps':[observation]}},
                    {'agent':'VideoAgent','video_id':'video_2','input':{'instruction':'SIBLING_PRIVATE_INSTRUCTION'},
                    'output':{'request_id':'req_1','status':'ok','report':'SIBLING_PRIVATE_REPORT','steps':[]}}]}}


def train(rows):
    return Evaluation('train','a'*64,0.5,len(rows),'identity',tuple(rows))


class SkillsTest(unittest.TestCase):
    def test_edit_preserves_other_role_and_cap(self):
        empty=SkillBank.from_dict({'schema_version':3,'skills':[]})
        global_bank=apply_edit(empty,'global',edit(),8)
        both=apply_edit(global_bank,'video',edit('video'),8)
        self.assertEqual(both.cards[0],global_bank.cards[0])
        with self.assertRaises(ValueError): apply_edit(both,'video',{**edit(),'operation':'revise','target_id':'1'},8)
        with self.assertRaises(ValueError): apply_edit(global_bank,'global',edit(),1)
        with self.assertRaises(ValueError): apply_edit(empty,'global',{**edit(),'extra':None},8)
        self.assertFalse(empty.cards)

    def test_freeze_runtime_and_tamper(self):
        runtime={'agents':{'global_agent':{'skill':{'enabled':False}},'video_agent':{'skill':{'enabled':True,'path':'old'}}},'models':{'fixed':{'seed':0}}}
        bank=apply_edit(SkillBank(()),'global',edit(),8)
        with tempfile.TemporaryDirectory() as folder:
            snap=freeze_bank(bank,folder); cfg=runtime_with_bank(runtime,snap)
            self.assertTrue(cfg['agents']['global_agent']['skill']['enabled'])
            self.assertFalse(cfg['agents']['video_agent']['skill']['enabled'])
            self.assertEqual(cfg['models'],runtime['models'])
            self.assertTrue(runtime['agents']['video_agent']['skill']['enabled'])
            snap.path.write_text('{}')
            with self.assertRaises(ValueError): snap.load()

    def test_role_views_exclude_hidden_and_future_data(self):
        source=row(); original=deepcopy(source)
        global_text=json.dumps(global_view(source))
        self.assertIn('GLOBAL_ONLY_QUESTION',global_text)
        for secret in ('PRIVATE_VIDEO_OBSERVATION','PRIVATE_GT','PRIVATE_MEDIA_PATH','PRIVATE_SAMPLE_ID','PRIVATE_TASK_CODE'):
            self.assertNotIn(secret,global_text)
        views=list(video_views(source)); local=json.dumps(views[0][1])
        self.assertIn('PRIVATE_VIDEO_OBSERVATION',local)
        for secret in ('GLOBAL_ONLY_QUESTION','SIBLING_PRIVATE','PRIVATE_GT','PRIVATE_MEDIA_PATH'):
            self.assertNotIn(secret,local)
        self.assertEqual(source,original)
        # Prior observations persist only within this video's later requests.
        source['result']['trajectory'].append({'agent':'VideoAgent','video_id':'video_1','input':{'instruction':'Check the handle'},
            'output':{'request_id':'req_2','status':'ok','report':'It is wooden.','steps':[]}})
        self.assertIn('PRIVATE_VIDEO_OBSERVATION',list(video_views(source))[-1][1]['prior_memory'])
        self.assertNotIn('SIBLING_PRIVATE',list(video_views(source))[-1][1]['prior_memory'])

    def test_only_train_can_cross_prompt_boundary(self):
        with self.assertRaises(ValueError): Evaluation('gate','a'*64,0.5,1,'x',(row(),))
        with self.assertRaises(ValueError): examples(Evaluation('cal','a'*64,0.5,1,'x'),'global',EvolutionConfig())
        text=json.dumps(examples(train([row()]),'global',EvolutionConfig()))
        for secret in ('PRIVATE_SAMPLE_ID','PRIVATE_TASK_CODE','PRIVATE_GT','PRIVATE_VIDEO_OBSERVATION'):
            self.assertNotIn(secret,text)

    def test_video_invalid_attempts_are_request_local_not_persistent_memory(self):
        source=row(); first=source['result']['trajectory'][0]
        first['output'].update(status='error', report='', error='No supported summary.')
        first['output']['steps']=[
            {'action':'observe','parameters':{'what':'Which tool?', 'fps':'invalid'},
             'result':{'status':'invalid','error':'FPS must be numeric.', 'raw_response':'PRIVATE_RAW_RESPONSE'}},
            {'action':'finish','parameters':{'summary':'unsupported'},
             'result':{'status':'invalid','error':'Observe evidence is required.'}},
            {'action':'finish','parameters':{},
             'result':{'status':'error','error':'No supported summary.','terminal':True}}]
        source['result']['trajectory'].append({'agent':'VideoAgent','video_id':'video_1',
            'input':{'instruction':'Check the handle'},
            'output':{'request_id':'req_2','status':'ok','report':'It is wooden.','steps':[]}})
        original=deepcopy(source); views=list(video_views(source)); first_view=views[0][1]
        self.assertEqual(first_view['actions'],[])
        self.assertEqual([item['action'] for item in first_view['request_feedback']],['observe','finish','finish'])
        self.assertEqual(first_view['request_feedback'][0]['error'],'FPS must be numeric.')
        self.assertTrue(first_view['request_feedback'][-1]['terminal'])
        self.assertEqual(first_view['error'],'No supported summary.')
        memory=VideoAgentMemory(); memory.begin_request('Which tool?')
        request=memory.begin_request('Check the handle')
        prior=memory.render_planner_view(request_id=request)
        self.assertEqual(views[-1][1]['prior_memory'],prior)
        self.assertEqual(views[-1][0],hash_json({'video_id':'video_1','instruction':'Check the handle','prior_memory':prior}))
        for secret in ('FPS must be numeric.','Observe evidence is required.','No supported summary.'):
            self.assertNotIn(secret,prior)
        for secret in ('PRIVATE_RAW_RESPONSE','PRIVATE_GT','GLOBAL_ONLY_QUESTION','SIBLING_PRIVATE'):
            self.assertNotIn(secret,json.dumps(first_view))
        self.assertEqual(source,original)

    def test_video_tool_errors_and_observations_remain_in_persistent_memory(self):
        source=row(); first=source['result']['trajectory'][0]
        failed={'action':'observe','parameters':{'what':'Find the handle','where':[[3,3]],'fps':1},
                'result':{'status':'error','error':'Observe range must have positive duration.'}}
        first['output']['steps'].append(failed)
        first['output']['steps'].append({'action':'finish','parameters':{'summary':'The tool is a spoon.'},
            'result':{'status':'ok','terminal':True,'report':'The tool is a spoon.'}})
        source['result']['trajectory'].append({'agent':'VideoAgent','video_id':'video_1',
            'input':{'instruction':'Check the handle'},
            'output':{'request_id':'req_2','status':'ok','report':'It is wooden.','steps':[]}})
        views=list(video_views(source)); first_view=views[0][1]
        self.assertEqual(len(first_view['actions']),2)
        self.assertIn('PRIVATE_VIDEO_OBSERVATION',first_view['actions'][0]['result'])
        self.assertIn(failed['result']['error'],first_view['actions'][1]['result'])
        self.assertTrue(first_view['request_feedback'][0]['terminal'])
        memory=VideoAgentMemory(); request=memory.begin_request('Which tool?')
        for step in first['output']['steps'][:2]:
            memory.add_action(step,request_id=request)
        request=memory.begin_request('Check the handle')
        prior=memory.render_planner_view(request_id=request)
        self.assertEqual(views[-1][1]['prior_memory'],prior)
        self.assertIn(failed['result']['error'],prior)
        self.assertIn('PRIVATE_VIDEO_OBSERVATION',prior)
        self.assertNotIn('SIBLING_PRIVATE',prior)

    def test_video_counterfactual_requires_same_context(self):
        before=row(); after=deepcopy(before); after['score']=1.0
        after['result']['trajectory'][0]['input']['instruction']='A different request'
        evidence=examples(train([before]),'video',EvolutionConfig(seed=1),candidate=train([after]))
        value=evidence[0]
        self.assertEqual(json.loads(value['parent']['trace'])['instruction'],'Which tool?')
        self.assertTrue(value['candidate_context_changed'])
        self.assertNotIn('candidate_same_local_context',value)
        for part in ('cal','gate'):
            with self.assertRaises(ValueError): examples(train([before]),'global',EvolutionConfig(),candidate=Evaluation(part,'a'*64,0.5,1,'x'))

    def test_long_traces_keep_both_arms_and_feedback(self):
        before=row(); before['result']['input']['question']='Long question ' * 1000
        after=deepcopy(before); after['score']=1.0
        evidence=examples(train([before]),'global',EvolutionConfig(max_example_chars=800),candidate=train([after]))[0]
        self.assertEqual(evidence['feedback'],{'parent_question_score':0.0,'candidate_question_score':1.0})
        self.assertTrue(evidence['parent']['truncated']); self.assertTrue(evidence['candidate']['truncated'])
        self.assertIn('selected_cards',evidence['parent']['trace'])
        self.assertIn('selected_cards',evidence['candidate']['trace'])

    def test_video_sampling_filters_eligible_questions_before_applying_budget(self):
        rows=[]
        for index in range(4):
            item=row(); item['sample_id']=f'private-{index}'
            if index<2:
                item['result']['trajectory']=[]
            else:
                item['score']=1.0
            rows.append(item)
        evidence=examples(train(rows),'video',EvolutionConfig(examples_per_proposal=2))
        self.assertEqual(len(evidence),2)
        self.assertTrue(all(e['feedback']['parent_question_score']==1 for e in evidence))
        self.assertEqual(examples(train(rows[:2]),'video',EvolutionConfig()),[])

    def test_unused_role_is_recorded_and_does_not_stop_other_role(self):
        import yaml
        runtime=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/inference/modal_qwen35_35b_a3b_no_skill.yaml').read_text())
        class Client:
            api_key='test-secret'
            calls=0
            def chat(self,*args,**kwargs):
                self.calls+=1; emit_event('model_response',finish_reason='stop')
                return json.dumps(edit())
        def evaluate(bank,partition):
            score=0.6 if bank.load().cards else 0.4
            sample=row(); sample['result']['trajectory']=[]; sample['score']=score
            return Evaluation(partition,bank.sha256,score,1,'identity',(sample,) if partition=='train' else ())
        client=Client()
        with tempfile.TemporaryDirectory() as folder:
            result=evolve(client=client,runtime=runtime,
                config=EvolutionConfig(roles=('video','global'),candidates_per_round=1),evaluator=evaluate,output=folder)
            skipped=json.loads((Path(folder)/'rounds/000-video/decision.json').read_text())
            self.assertEqual(skipped['reason'],'no_role_visible_train_examples')
            self.assertFalse(skipped['accepted'])
            self.assertEqual(client.calls,1)
            self.assertEqual(result['accepted_rounds'],1)
            self.assertFalse((Path(folder)/'rounds/000-video/proposal-00/request.json').exists())

    def test_saved_api_attempt_is_not_repeated_and_invalid_output_is_retained(self):
        class Client:
            api_key='test-secret'
            count=0
            def chat(self,*args,**kwargs):
                self.count+=1; emit_event('model_response',finish_reason='stop')
                return json.dumps(edit())
        client=Client()
        with tempfile.TemporaryDirectory() as folder:
            request=[{'role':'user','content':'A request'}]
            first=call_json(client,request,SCHEMA,folder,'edit')
            self.assertEqual(call_json(client,request,SCHEMA,folder,'edit'),first)
            self.assertEqual(client.count,1)
            with self.assertRaises(ValueError): call_json(client,[{'role':'user','content':'changed'}],SCHEMA,folder,'edit')
        client.chat=lambda *a,**k: '{bad JSON'
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): call_json(client,[],SCHEMA,folder,'edit')
            self.assertEqual(json.loads((Path(folder)/'response.json').read_text())['raw_response'],'{bad JSON')

    def test_cal_gain_cannot_bypass_gate_and_resume_keeps_lineage(self):
        import yaml
        runtime=yaml.safe_load((Path(__file__).resolve().parents[1]/'configs/inference/modal_qwen35_35b_a3b_no_skill.yaml').read_text())
        class Client:
            api_key='test-secret'
            calls=0
            prompts=[]
            def chat(self,messages,**kwargs):
                self.calls+=1; self.prompts.append(json.dumps(messages))
                emit_event('model_response',finish_reason='stop')
                return json.dumps(edit('global' if self.calls==1 else 'video'))
        def evaluate(bank,partition):
            roles={c.role for c in bank.load().cards}
            score=0.4 if not roles else (0.4 if partition=='gate' and roles=={'global'} else 0.6)
            sample=row(); sample['score']=score
            return Evaluation(partition,bank.sha256,score,1,hash_json([bank.sha256,partition]),(sample,) if partition=='train' else ())
        client=Client(); config=EvolutionConfig(rounds=2,candidates_per_round=1)
        with tempfile.TemporaryDirectory() as folder:
            result=evolve(client=client,runtime=runtime,config=config,evaluator=evaluate,output=folder)
            self.assertEqual(result['accepted_rounds'],1)
            self.assertEqual([c.role for c in SkillBank.load(path=result['bank_path'],sha256=result['bank_sha256']).cards],['video'])
            first=json.loads((Path(folder)/'rounds/000-global/decision.json').read_text())
            self.assertEqual(first['reason'],'gate_not_improved')
            resumed=evolve(client=client,runtime=runtime,config=config,evaluator=evaluate,output=folder)
            self.assertEqual(resumed,result); self.assertEqual(client.calls,2)
            for prompt in client.prompts:
                self.assertNotIn('PRIVATE_GT',prompt)
                self.assertNotIn('PRIVATE_SAMPLE_ID',prompt)
                self.assertNotIn('PRIVATE_TASK_CODE',prompt)

    def test_configuration_rejects_unknown_and_invalid_budgets(self):
        for value in ({'rounds':0},{'max_cards_per_role':9},{'rounds':True},{'roles':['global','global']},{'typo':1}):
            with self.assertRaises(ValueError): EvolutionConfig.from_dict(value)


if __name__=='__main__': unittest.main()
