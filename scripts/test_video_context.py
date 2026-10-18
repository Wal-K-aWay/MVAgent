"""Question context reaches both Video paths without becoming visual evidence."""
import unittest
from unittest.mock import Mock

from models.vlm import VLMClient
from mvagent.agents.video_agent.agent import VideoAgent
from mvagent.agents.video_agent.prompts import VIDEO_PLANNER_SYSTEM_PROMPT
from test_direct_answer import Model

QUESTION = 'Which video has more wall paintings? Exclude tabletop photos.\nA. video_1\nB. video_2\nKeep {criteria} unchanged.'
INSTRUCTION = 'Count paintings in this video.'
OBSERVE = dict(action='observe', parameters=dict(what='Count wall paintings.',where=[[0,2]],fps=1))


def make_agent(model, question=QUESTION):
    observer=Mock(spec=VLMClient);observer.max_video_frames_per_request=512
    return VideoAgent(original_question=question,video_id='video_2',video_path='/unused.mp4',
        duration_sec=10,planner_model=model,observer_model=observer,logger=lambda message:None)


class VideoContextTests(unittest.TestCase):
    def test_planner_and_forced_finish_keep_exact_context_once(self):
        model=Model(OBSERVE,OBSERVE,dict(summary='Two wall paintings; tabletop photos excluded.'))
        agent=make_agent(model);request=agent.memory.begin_request(INSTRUCTION)
        for _ in range(2):
            self.assertEqual(agent._call_planner(instruction=INSTRUCTION,request_id=request)['status'],'ok')
        agent.memory.add_action(dict(action='observe',parameters=OBSERVE['parameters'],
            result=dict(status='ok',observations=[dict(text='Two wall paintings.',time_range=[0,2],fps=1)])),
            request_id=request)
        result=agent._request_terminal_finish(instruction=INSTRUCTION,request_id=request)
        self.assertEqual(result['status'],'ok')
        self.assertIn('Two wall paintings',result['report'])
        self.assertEqual([r['schema_name'] for r in model.requests],['video_action','video_action','video_finish'])
        for request in model.requests:
            system,user=request['messages']
            self.assertEqual(system['content'],VIDEO_PLANNER_SYSTEM_PROMPT)
            self.assertEqual(user['content'].count(QUESTION),1)
            self.assertIn('Assigned source video ID: video_2',user['content'])
            self.assertIn(INSTRUCTION,user['content'])
        self.assertNotIn('## Available actions',model.requests[-1]['messages'][1]['content'])
        self.assertNotIn(QUESTION,str(agent.memory.to_dict()))

    def test_question_does_not_allow_finishing_without_observation(self):
        model=Model();agent=make_agent(model)
        request=agent.memory.begin_request(INSTRUCTION)
        result=agent._request_terminal_finish(instruction=INSTRUCTION,request_id=request)
        self.assertEqual(result['status'],'error')
        self.assertFalse(model.requests)
        self.assertFalse(agent.memory.has_observations)


if __name__=='__main__':unittest.main()
