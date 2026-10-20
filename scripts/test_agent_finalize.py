"""CPU regression for merging the current per-question records with CCQA scores."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'eval/agent_eval'))
from finalize_results import CROSSVID_TASK_ORDER, REPORT_NAME, _merge_deferred_judge


class DeferredJudgeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.rows = []
        for sid, points in [(1, ['a']), (2, ['b', 'c', 'd'])]:
            path = self.root/f'records/crossvid/crossvid:CCQA:{sid}/result.json'
            path.parent.mkdir(parents=True)
            row = dict(sample_id=f'crossvid:CCQA:{sid}', status='ok', scoring_status='deferred',
                       prediction=f'answer {sid}', ground_truth=points)
            path.write_text(json.dumps(row))
            self.rows.append(path)
        self.judge = dict(samples=[
            dict(id=1, status='ok', prediction='answer 1', coverage=[True], correctness=[True], score=2),
            dict(id=2, status='ok', prediction='answer 2', coverage=[False]*3, correctness=[False]*3, score=0)],
            official_score=0.25, judge=dict(model='Qwen3-30B-A3B-Instruct-2507'), updated_at_utc='test')
        self.judge_path = self.root/'score'/REPORT_NAME
        self.judge_path.parent.mkdir()
        self.judge_path.write_text(json.dumps(self.judge))
        self.summary = dict(total_deferred=2, total_completed=18, datasets=dict(crossvid=dict(
            expected=20, completed=18, deferred=2, score_sum=18,
            by_task={task:dict(accuracy=1, total=2) for task in CROSSVID_TASK_ORDER if task!='CCQA'},
            by_task_family={})))

    def test_current_records_weighted_score_and_unchanged_raw(self):
        before = [p.read_bytes() for p in self.rows]
        result = _merge_deferred_judge(self.root, copy.deepcopy(self.summary))
        cross = result['datasets']['crossvid']
        self.assertEqual(cross['by_task']['CCQA']['accuracy'], .25)
        self.assertEqual(cross['by_task']['CCQA']['question_mean'], .5)
        self.assertEqual(cross['official_score'], .925)
        self.assertEqual(result['total_completed'], 20)
        self.assertEqual(result['total_deferred'], 0)
        self.assertEqual(result['external_judge']['requested_model'], self.judge['judge']['model'])
        self.assertEqual(before, [p.read_bytes() for p in self.rows])

    def test_judgement_for_different_answer_is_rejected(self):
        self.judge['samples'][0]['prediction'] = 'different answer'
        self.judge_path.write_text(json.dumps(self.judge))
        with self.assertRaises(AssertionError):
            _merge_deferred_judge(self.root, copy.deepcopy(self.summary))


if __name__ == '__main__':
    unittest.main()
