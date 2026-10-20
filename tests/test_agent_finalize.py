"""CPU regression for merging the current per-question records with CCQA scores."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'eval/agent_eval'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from finalize_results import (
    CROSSVID_TASK_ORDER, REPORT_NAME, CVBENCH_TASKS_PATH, CVBENCH_TASK_CATEGORY,
    _cvbench_category_table, _merge_deferred_judge,
)
from scripts.prepare_cvbench_mvu_qas import DEFAULT_CVBENCH_SOURCE, cvbench_rows


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

    def test_cvbench_annotations_still_prepare_and_classify_records(self):
        self.assertEqual(DEFAULT_CVBENCH_SOURCE, CVBENCH_TASKS_PATH)
        rows = cvbench_rows(DEFAULT_CVBENCH_SOURCE)
        self.assertEqual(len(rows), 1000)
        representatives = {}
        for row in rows:
            category = CVBENCH_TASK_CATEGORY[row["task_type"]]
            representatives.setdefault(category, row)
        self.assertEqual(len(representatives), 3)
        for row in representatives.values():
            sid = f"cvbench:{row['id']}"
            path = self.root / "records/cvbench" / sid / "result.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(dataset="cvbench", sample_id=sid,
                                           status="ok", correct=True)))
        stats, correct, total = _cvbench_category_table(self.root)
        self.assertEqual((correct, total), (3, 3))
        self.assertEqual(set(stats), set(representatives))
        self.assertTrue(all(s["correct"] == s["total"] == 1 for s in stats.values()))

    def test_finalize_cli_without_e2e_checkout(self):
        before = [p.read_bytes() for p in self.rows]
        summary = copy.deepcopy(self.summary)
        summary["datasets"]["crossvid"].update(errors=0, pending=0)
        (self.root / "summary.json").write_text(json.dumps(summary))
        (self.root / "run_manifest.json").write_text("{}")
        (self.root / "input_config.yaml").write_text(
            "model_name: test\nmax_video_frames_per_request: 512\nenabled: false\n")
        script = Path(__file__).resolve().parents[1] / "eval/agent_eval/finalize_results.py"
        subprocess.run([sys.executable, str(script), "--output", str(self.root)],
                       check=True, capture_output=True, text=True)
        scored = json.loads((self.root / "summary_scored.json").read_text())
        self.assertEqual(scored["datasets"]["crossvid"]["official_score"], .925)
        self.assertIn("92.50", (self.root / "benchmark_results.md").read_text())
        self.assertEqual(before, [p.read_bytes() for p in self.rows])


if __name__ == '__main__':
    unittest.main()
