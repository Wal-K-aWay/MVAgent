"""CPU checks for structured public feedback; run in the remote test environment."""
from copy import deepcopy
import json
import unittest

from skill_evolution.infra.feedback import format_feedback


def global_view(history='(none)'):
    return {'question': '比较“杯子”的位置；原话是 "left"。',
            'videos': {'video_1': {'duration_sec': 9.5}, 'video_2': {'duration_sec': 12}},
            'history': history, 'answer': {'answer': 'A', 'reason': '嵌套 {"x": "引号"}'},
            'selected_cards': [['1']]}


def example(parent, candidate=None):
    value = {'parent': parent, 'feedback': {'parent_question_score': 0.0}}
    if candidate is not None:
        value.update(candidate=candidate)
        value['feedback']['candidate_question_score'] = 1.0
    return value


class FeedbackTests(unittest.TestCase):
    def test_identical_views_are_not_duplicated_and_input_is_unchanged(self):
        view = global_view('Event 1 — watch_videos\nResult: "里面有\\斜线和中文"。')
        source = example(view, deepcopy(view)); original = deepcopy(source)
        result = format_feedback(source, 12000)
        self.assertEqual(source, original)
        self.assertTrue(result['visible_views_identical'])
        self.assertEqual(result['parent'], {})
        self.assertEqual(result['candidate'], {})
        self.assertEqual(result['shared']['question'], view['question'])
        self.assertEqual(result['shared']['history']['events'][0]['event'], view['history'])
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)

    def test_exact_prefix_is_shared_without_aligning_later_events(self):
        common = 'Event 1 — analyze_videos\nSummary: 初始观察。'
        parent = global_view(common + '\n\nEvent 2 — watch_videos\nResult: 父证据。')
        candidate = global_view(common + '\n\nEvent 2 — analyze_videos\nSummary: 新证据。\n\nEvent 3 — watch_videos\nResult: 末次证据。')
        result = format_feedback(example(parent, candidate), 12000)
        self.assertEqual(result['shared_event_prefixes']['history']['events'][0]['event'], common)
        self.assertEqual([e['index'] for e in result['parent']['history']['events']], [2])
        self.assertEqual([e['index'] for e in result['candidate']['history']['events']], [2, 3])
        self.assertNotEqual(result['parent']['history']['events'][0]['event'],
                            result['candidate']['history']['events'][0]['event'])

    def test_complete_last_evidence_survives_and_omissions_are_explicit(self):
        blocks = [f'Event {i} — watch_videos\nResult: ' + ('长证据。' * 250 if i in (2, 3) else f'完整证据{i}。')
                  for i in range(1, 5)]
        view = global_view('\n\n'.join(blocks))
        result = format_feedback(example(view), 1300)
        history = result['parent']['history']
        self.assertEqual([e['index'] for e in history['events']], [1, 4])
        self.assertEqual(history['events'][-1]['event'], blocks[-1])
        self.assertEqual(history['omitted_ranges'], [[2, 3]])
        self.assertEqual(history['event_count'], 4)
        for field in ('question', 'videos', 'answer', 'selected_cards'):
            self.assertEqual(result['parent'][field], view[field])
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, indent=2)), 1300)

    def test_video_preserves_context_and_whole_feedback_events(self):
        parent = {'instruction': '本视频里手的位置？', 'duration_sec': 2.0, 'prior_memory': '同视频旧证据',
                  'actions': [{'action': 'observe', 'parameters': {'what': '手？', 'where': [[0, 2]], 'fps': 1},
                               'result': '左边。'}], 'report': '左边', 'status': 'ok', 'selected_cards': [['1']],
                  'request_feedback': [{'step': 2, 'action': 'finish', 'terminal': True}], 'error': ''}
        after = deepcopy(parent); after['report'] = '右边'; after['actions'][0]['result'] = '右边。'
        source = {'parent': parent, 'candidate_same_local_context': after,
                  'feedback': {'parent_question_score': 0, 'candidate_question_score': 1,
                               'scope': 'whole question; NOT local correctness'}}
        result = format_feedback(source, 2500)
        self.assertEqual(result['shared']['prior_memory'], parent['prior_memory'])
        self.assertEqual(result['shared']['request_feedback']['events'][0]['event'], parent['request_feedback'][0])
        self.assertEqual(result['candidate_same_local_context']['report'], '右边')
        for view in (result['shared'], result['parent'], result['candidate_same_local_context']):
            self.assertNotIn('question', view)
            self.assertNotIn('videos', view)
        self.assertEqual(result['feedback'], source['feedback'])

    def test_unmatched_candidate_is_not_fabricated(self):
        source = example(global_view()); source['candidate_context_changed'] = True
        result = format_feedback(source, 12000)
        self.assertTrue(result['candidate_context_changed'])
        self.assertNotIn('candidate', result)
        self.assertNotIn('candidate_same_local_context', result)

    def test_unknown_history_stays_one_whole_event(self):
        text = '没有运行时事件标记。\n引号内的 "Step 3" 不是标题。' * 100
        result = format_feedback(example(global_view(text)), 1000)
        self.assertEqual(result['parent']['history']['events'], [])
        self.assertEqual(result['parent']['history']['omitted_ranges'], [[1, 1]])

    def test_protected_context_overflow_and_private_or_truncated_inputs_fail(self):
        view = global_view(); view['question'] = '不可截断' * 1000
        with self.assertRaisesRegex(ValueError, 'Protected'):
            format_feedback(example(view), 1000)
        for field in ('ground_truth', 'sibling_private', 'trace'):
            view = global_view(); view[field] = 'must not silently forward'
            with self.assertRaisesRegex(ValueError, 'untruncated public view'):
                format_feedback(example(view), 12000)
        for budget in (0, True, 1.5):
            with self.assertRaises(ValueError):
                format_feedback(example(global_view()), budget)


if __name__ == '__main__':
    unittest.main()
