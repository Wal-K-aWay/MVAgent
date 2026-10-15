"""Direct Global answers, bounded evidence decisions, and forced finalization."""
from copy import deepcopy
from types import SimpleNamespace
import unittest

from models.utils import validate_json_schema
from mvagent.agents.global_agent.agent import GlobalAgent
from mvagent.agents.global_agent.prompts import GLOBAL_AGENT_SYSTEM_PROMPT, build_global_decision_prompt
from mvagent.agents.global_agent.schema import build_global_decision_schema
from mvagent.engine import MVAgentEngine


def answer(text='B', reason='The evidence supports this judgment.'):
    return dict(reason=reason, action='answer', parameters=dict(answer=text))


def analyze(reason='Check the visible feature.'):
    return dict(reason=reason, action='analyze_videos', parameters=dict(
        videoagent_request=[dict(video_id='video_1', instruction='Describe the visible feature.')]))


class Model:
    def __init__(self, *values):
        self.values = iter(values)
        self.requests = []

    def json_chat(self, **request):
        self.requests.append(request)
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return dict(status='ok', value=deepcopy(value))


def agent(model, skill=''):
    return GlobalAgent(video_ids=['video_1'], question='Question', model=model, decision_skill=skill)


def engine(max_steps=1):
    result = MVAgentEngine.__new__(MVAgentEngine)
    result.cfg = SimpleNamespace(global_agent=SimpleNamespace(max_steps=max_steps))
    result._log = lambda message: None

    def execute(**kwargs):
        kwargs['global_agent'].add_action(action='analyze_videos',
            parameters=dict(videoagent_request=kwargs['videoagent_request']), status='ok',
            outcomes=[dict(video_id='video_1', instruction='Describe the visible feature.',
                           request_id='observation-1', status='ok', report='Summary: A visible feature supports B.')])
    result._execute_analyze_videos_action = execute
    return result


class DirectAnswerTests(unittest.TestCase):
    def test_decoder_compiles_both_action_contracts(self):
        import json
        from models.vlm.api.providers.openai_compatible import _compact_vllm_grammar, _vllm_generation_schema
        for names in [['answer'], ['answer', 'analyze_videos']]:
            grammar = _compact_vllm_grammar(json.dumps(_vllm_generation_schema(build_global_decision_schema(names))))
            self.assertIn('root', grammar)

    def test_answer_is_open_nonblank_and_reason_is_unbounded(self):
        schema = build_global_decision_schema(['answer', 'analyze_videos'])
        for text in ['A free-form answer', '}', '1.5,3.5']:
            validate_json_schema(answer(text, 'Evidence. '*200), schema)
        for value in [answer(' '), answer('', 'Evidence'), answer('B', ' '),
                      dict(reason='Evidence', action='answer', parameters={})]:
            with self.assertRaises(ValueError):
                validate_json_schema(value, schema)

    def test_other_decision_reason_stays_bounded(self):
        schema = build_global_decision_schema(['answer', 'analyze_videos'])
        validate_json_schema(analyze(), schema)
        with self.assertRaises(ValueError):
            validate_json_schema(analyze('x'*1201), schema)

    def test_forced_schema_disallows_another_observation(self):
        schema = build_global_decision_schema(['answer'])
        validate_json_schema(answer(), schema)
        with self.assertRaises(ValueError):
            validate_json_schema(analyze(), schema)

    def test_localizer_accepts_answer_parameter_fault_only_for_editable_step(self):
        from importlib import import_module
        module = import_module('skill_evolution.algorithms.alternating.global.adaptor.prompts.localizer.schema')
        schema = module.build_schema(dict(steps=[
            dict(step=1, editable=True, decision=dict(action='answer')),
            dict(step=2, editable=False, decision=dict(action='answer'))]))
        value = dict(status='located', reason='The submitted label contradicts retained evidence.',
            fault_chain=[dict(step=1, fault_type='action_parameter_error', evidence_reason='Prior evidence supports B.',
                             improvement_principle='Preserve the evidence-to-option mapping.')])
        validate_json_schema(value, schema)
        value['fault_chain'][0]['step'] = 2
        with self.assertRaises(ValueError):
            validate_json_schema(value, schema)

    def test_prompt_and_schema_match_each_action_budget(self):
        prompt = build_global_decision_prompt(question='Question', videos=['video_1'],
            action_history_view='Evidence', available_action_names=['answer', 'analyze_videos'])
        final_block = prompt.split('### Action: answer',1)[1].split('### Action: analyze_videos',1)[0]
        self.assertIn('parameters.answer', final_block)
        self.assertNotIn('1200 characters', final_block)
        self.assertIn('2400 characters', final_block)
        self.assertIn('1200 characters', prompt.split('### Action: analyze_videos',1)[1])

    def test_answer_only_keeps_system_evidence_and_skill(self):
        model = Model(answer()); coordinator = agent(model, 'Compare the retained evidence.')
        coordinator.add_invalid_decision(error='Retained feedback')
        result = coordinator.decide(answer_only=True)
        self.assertEqual(result['decision']['parameters']['answer'], 'B')
        request = model.requests[0]
        self.assertEqual(request['schema_name'], 'global_decision')
        self.assertEqual(request['messages'][0]['content'], GLOBAL_AGENT_SYSTEM_PROMPT)
        self.assertIn('Retained feedback', request['messages'][1]['content'])
        self.assertIn('Compare the retained evidence.', request['messages'][1]['content'])
        self.assertIn('No further evidence collection', request['messages'][1]['content'])
        self.assertNotIn('### Action: analyze_videos', request['messages'][1]['content'])

    def test_normal_answer_needs_only_one_model_call(self):
        model = Model(answer(' B ')); trajectory = []
        result, stop = engine()._run_global_loop(global_agent=agent(model), video_agents={}, trajectory=trajectory)
        self.assertEqual(result, dict(answer='B', reason='The evidence supports this judgment.', status='answered'))
        self.assertEqual(stop, result['reason'])
        self.assertEqual(len(model.requests), 1)
        self.assertEqual([r['action'] for r in trajectory], ['decide'])
        self.assertEqual(trajectory[0]['output']['parameters']['answer'], 'B')

    def test_loop_limit_uses_same_decision_and_preserves_result_interface(self):
        model = Model(analyze(), answer()); trajectory = []
        result, stop = engine()._run_global_loop(global_agent=agent(model), video_agents={}, trajectory=trajectory)
        self.assertEqual(result['answer'], 'B')
        self.assertEqual(result['status'], 'forced_with_gaps')
        self.assertEqual(stop, 'GlobalAgent reached max_steps.')
        self.assertEqual([r['schema_name'] for r in model.requests], ['global_decision']*2)
        self.assertIn('A visible feature supports B.', model.requests[-1]['messages'][1]['content'])
        self.assertEqual(trajectory[-1]['action'], 'terminal_answer')
        self.assertEqual(trajectory[-1]['output']['parameters']['answer'], 'B')

    def test_invalid_empty_parameters_retry_without_answerer(self):
        model = Model(dict(reason='Evidence',action='answer',parameters={}), answer()); trajectory = []
        result, _ = engine(max_steps=2)._run_global_loop(global_agent=agent(model),video_agents={},trajectory=trajectory)
        self.assertEqual(result['answer'], 'B')
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(trajectory[0]['output']['status'], 'invalid')

    def test_failed_forced_decision_keeps_existing_failure_record(self):
        for value in [answer(' '), RuntimeError('service failed')]:
            with self.subTest(value=str(value)):
                trajectory=[];model=Model(analyze(),value)
                result, stop=engine()._run_global_loop(global_agent=agent(model),video_agents={},trajectory=trajectory)
                self.assertEqual(result['answer'], '')
                self.assertEqual(result['status'], 'forced_with_gaps')
                self.assertEqual(trajectory[-1]['action'], 'terminal_answer')
                self.assertEqual(trajectory[-1]['output']['status'], 'error')

    def test_ordinary_infrastructure_error_still_propagates(self):
        with self.assertRaisesRegex(RuntimeError, 'service failed'):
            engine()._run_global_loop(global_agent=agent(Model(RuntimeError('service failed'))),video_agents={},trajectory=[])


if __name__ == '__main__':
    unittest.main()
