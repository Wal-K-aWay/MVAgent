"""Optimizer references the actual consumer contract without exposing credentials."""
import json
import unittest

from mvagent.skills.bank import SkillBank
from mvagent.skills.prompts import build_selector_system_prompt
from skill_evolution.algorithms.rolewise.prompts import messages


class OptimizerPromptTests(unittest.TestCase):
    def test_consumer_and_selector_contract(self):
        runtime = {'models': {'actor': {
            'model_name': 'Qwen3.5-9B', 'temperature': 0, 'top_p': 1,
            'max_tokens': 2048, 'enable_thinking': False,
            'api_key': 'PRIVATE_CREDENTIAL', 'api_base': 'PRIVATE_ENDPOINT',
            'max_videos_per_request': 8, 'max_video_frames_per_request': 512,
        }}, 'agents': {
            'global_agent': {'model': {'model_type': 'actor'}, 'max_steps': 5,
                             'max_videos_per_watch': 4},
            'video_agent': {'planner': {'model_type': 'actor'},
                            'observer': {'model_type': 'actor'}, 'max_steps': 5,
                            'max_ranges_per_action': 8},
        }}
        for role in ('global', 'video'):
            payload = messages(runtime, role, SkillBank(()), [], 8,
                               train_summary={'samples': 80, 'parent_score': .3})
            text = payload[1]['content']
            self.assertIn(build_selector_system_prompt(role), text)
            body = json.loads(text[text.rfind('\n\n{') + 2:])
            self.assertEqual(body['consumer_model']['max_tokens'], 2048)
            self.assertIs(body['consumer_model']['enable_thinking'], False)
            self.assertEqual(body['train_summary']['samples'], 80)
            self.assertNotIn('PRIVATE_CREDENTIAL', text)
            self.assertNotIn('PRIVATE_ENDPOINT', text)
            self.assertIn('not a representative estimate', payload[0]['content'])


if __name__ == '__main__':
    unittest.main()
